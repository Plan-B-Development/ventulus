"""``ventulus-diag validation`` — AIO validation, lifecycle recording and thermal
observation sessions (DEC-317/335, moved out of the GUI by DEC-503).

A session records a cooling device's telemetry and, when asked, has the daemon
run its own diagnostics on the device's members. A session that runs none is a
passive recording and needs no confirmation; one that runs any drives fans and
needs the same confirmation as every other test here. The daemon owns every
rule a session follows: the pump floor, the thermal refusal, the lease and the
restore.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from ventulus.api.client import DaemonClient
from ventulus.api.errors import DaemonError, DaemonTimeout, DaemonUnavailable
from ventulus.api.models import (
    VALIDATION_KIND_LIFECYCLE,
    VALIDATION_KIND_THERMAL,
    VALIDATION_KIND_VALIDATION,
    VALIDATION_STATE_CANCELLED,
    VALIDATION_STATE_COMPLETED,
    ValidationSession,
)
from ventulus.diag.confirm import confirm_writes, describe
from ventulus.diag.console import (
    EXIT_CANCELLED,
    EXIT_FAILED,
    EXIT_INTERRUPTED,
    EXIT_OK,
    EXIT_REFUSED,
    EXIT_STOPPED,
    Console,
    DiagError,
    Interrupts,
)
from ventulus.diag.daemon import Daemon, start_refusal
from ventulus.services.characterization_view import ENGINE_PAUSE_WARNING, PUMP_STARTUP_WARNING
from ventulus.services.pump_protection import header_is_pump_protected
from ventulus.services.pwm_report.executor import cancel_slot, poll_slot
from ventulus.services.thermal_view import build_startup_views, build_steady_state_view
from ventulus.services.validation_view import build_validation_session_view, format_elapsed

KINDS = {
    "validation": VALIDATION_KIND_VALIDATION,
    "lifecycle": VALIDATION_KIND_LIFECYCLE,
    "thermal": VALIDATION_KIND_THERMAL,
}
#: CLI name → (wire token, the capability that must be advertised for it).
DIAGNOSTICS = {
    "verify": ("pwm_verify", None),
    "characterization": ("pwm_characterization", "pwm_characterization"),
    "behaviour": ("pwm_behaviour_characterization", "pwm_behaviour_characterization"),
    "control-path": ("control_path_discovery", "control_path_discovery"),
}
#: How often a followed session is read back.
FOLLOW_INTERVAL_S = 2.0
#: How often a followed session prints its progress when nothing else changed.
PROGRESS_EVERY_S = 30.0
MAX_POLL_FAILURES = 5


@dataclass(frozen=True)
class StartRequest:
    device_id: str
    kind: str = "validation"
    diagnostics: tuple[str, ...] = ()
    sweep_members: tuple[str, ...] = ()
    metadata: tuple[str, ...] = ()
    auto_stop: bool = False
    detach: bool = False
    confirmed_by_flag: bool = False


def _metadata(pairs: Iterable[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key.strip():
            raise DiagError(EXIT_REFUSED, f"--meta takes KEY=VALUE, got {pair!r}.")
        out[key.strip()] = value.strip()
    return out


def render(console: Console, session: ValidationSession, daemon: Daemon) -> None:
    view = build_validation_session_view(session, display_name=daemon.name_of)
    console.out(f"Session {view.session_id} — {view.device_name}: {view.state_label}")
    console.out(f"  Kind: {view.kind}; {view.elapsed_text}; {view.sample_count} samples")
    console.out(f"  Diagnostics: {view.diagnostics_note}")
    for note in (view.interrupted_note, view.limit_note):
        if note:
            console.out(f"  ! {note}")
    for f in view.findings:
        detail = f" — {f.detail}" if f.detail else ""
        console.out(f"  {f.state_label}: {f.check_text}{detail}")
    for e in view.evidence:
        console.out(f"  Evidence: {e.label} ({e.member_label}): {e.outcome_label}")
    for m in view.members:
        console.out(
            f"  {m.label} [{m.role_label}]: requested {m.requested_range}, readback "
            f"{m.readback_range}, RPM {m.rpm_range}"
        )
    # DEC-335 §3 and §1: a thermal observation's steady state, and each
    # member's startup behaviour. The daemon decides both; this prints them.
    steady = build_steady_state_view(session.steady_state)
    if steady is not None:
        console.out(f"  Steady state: {steady.verdict_label}")
        for row in steady.rows:
            console.out(f"    {row.label}: {row.value}")
        if steady.criterion:
            console.out(f"    Rule: {steady.criterion}")
    for startup in build_startup_views(session.startup_fingerprints, display_name=daemon.name_of):
        console.out(f"  Startup: {startup.interpretation_label}")
        for row in startup.rows:
            console.out(f"    {row.label}: {row.value}")


def devices_cmd(console: Console, daemon: Daemon) -> int:
    daemon.require("validation_sessions")
    inventory = daemon.client.get_cooling_devices()
    if not inventory.cooling_devices:
        console.out(
            "No cooling devices are configured. Configure one with Configure AIO… on the "
            "Ventulus app's Controls page or, on a machine without the app, with "
            "POST /config/cooling-device (see the daemon's User Guide)."
        )
        return EXIT_OK
    for dev in inventory.cooling_devices:
        pump = daemon.name_of(dev.pump_member) if dev.pump_member else "none"
        radiators = ", ".join(daemon.name_of(m) for m in dev.radiator_members) or "none"
        console.out(f"{dev.id}  {dev.name} ({dev.kind}) — pump: {pump}; radiators: {radiators}")
    return EXIT_OK


def start_cmd(
    console: Console,
    daemon: Daemon,
    request: StartRequest,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    daemon.require("validation_sessions")
    kind = KINDS[request.kind]
    if kind == VALIDATION_KIND_THERMAL:
        daemon.require("thermal_observation")
    if request.auto_stop:
        daemon.require("validation_auto_stop")
        if not request.diagnostics:
            raise DiagError(EXIT_REFUSED, "--auto-stop needs at least one --diagnostic.")
    tokens: list[str] = []
    for name in request.diagnostics:
        token, feature = DIAGNOSTICS[name]
        if feature is not None:
            daemon.require(feature)
        tokens.append(token)
    devices = {d.id: d for d in daemon.client.get_cooling_devices().cooling_devices}
    device = devices.get(request.device_id)
    if device is None:
        known = ", ".join(devices) or "none"
        raise DiagError(
            EXIT_REFUSED,
            f"No cooling device has the id {request.device_id!r}. Known ids: {known}",
        )
    metadata = _metadata(request.metadata)
    reasons = start_refusal(daemon.status())
    if tokens and reasons:
        raise DiagError(EXIT_REFUSED, "Cannot start now:\n" + "\n".join(f"  {r}" for r in reasons))
    if tokens:
        members = list(request.sweep_members) or (
            [device.pump_member] if device.pump_member else []
        )
        swept = ", ".join(f"{daemon.name_of(m)} ({m})" for m in members) or "none"
        # The device's pump, or any swept header the daemon protects as a pump
        # (the union, never the display role, DEC-312).
        headers = {h.id: h for h in daemon.headers}
        pumps = [
            m
            for m in members
            if m == device.pump_member
            or header_is_pump_protected(headers.get(m), daemon.capabilities)
        ]
        warnings = [ENGINE_PAUSE_WARNING]
        if pumps:
            named = ", ".join(daemon.name_of(m) for m in pumps)
            warnings.append(
                f"Swept as a pump: {named}. A pump is never driven below its pump floor "
                "and never stopped."
            )
            warnings.append(PUMP_STARTUP_WARNING)
        describe(
            console,
            f"This session runs diagnostics on {device.name} ({device.id}):",
            [
                f"Diagnostics: {', '.join(request.diagnostics)}",
                "Members swept: "
                + (swept if request.sweep_members else f"{swept} (the daemon's default)"),
            ],
            warnings,
        )
        refusal = confirm_writes(console, flag_given=request.confirmed_by_flag)
        if refusal:
            raise DiagError(EXIT_REFUSED, refusal)
    # Counted from before the start request, as for a single-header test.
    with Interrupts() as signals:
        try:
            session = daemon.client.start_validation_session(
                device.id,
                kind=kind,
                diagnostics=tokens or None,
                sweep_members=list(request.sweep_members) or None,
                metadata=metadata or None,
                stop_when_diagnostics_complete=request.auto_stop,
            )
        except DaemonTimeout as e:
            # It may have started: end it rather than leave it running unseen.
            daemon.best_effort(lambda c: _end(console, c, bool(tokens)))
            raise DiagError(
                EXIT_INTERRUPTED,
                f"No answer from the daemon ({e.message}). A cancel was attempted in case "
                "the session started; check with ventulus-diag validation status.",
            ) from e
        except DaemonUnavailable as e:
            raise DiagError(EXIT_INTERRUPTED, f"No answer from the daemon ({e.message}).") from e
        except DaemonError as e:
            raise DiagError(
                EXIT_REFUSED, f"The daemon did not start the session: {e.message}"
            ) from e
        console.out(f"Session {session.session_id} started.")
        if request.detach and signals.count == 0:
            console.out(
                "It records until it is stopped. ventulus-diag validation status shows it; "
                "ventulus-diag validation stop ends it."
            )
            return EXIT_OK
        return follow(
            console,
            daemon,
            session.session_id,
            active=bool(tokens),
            signals=signals,
            clock=clock,
            sleep=sleep,
        )


def follow(
    console: Console,
    daemon: Daemon,
    session_id: str,
    *,
    active: bool,
    signals: Interrupts,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Read the session back until it ends. The first interrupt ends it: an
    active session is cancelled (and its running diagnostic with it), a passive
    one is stopped. A second leaves without waiting."""
    action = "cancels the session and its running test" if active else "stops the recording"
    console.out(f"Following it. Ctrl-C {action}; the daemon puts any header back.")
    ended_by_us = False
    failures = 0
    next_read = clock()
    last_progress = clock()
    seen_evidence = 0
    while True:
        if signals.count >= 2:
            if not ended_by_us:  # both signals came before the loop could end it
                ended_by_us = True
                daemon.best_effort(lambda c: _end(console, c, active))
            console.out("Stopped waiting. The daemon finishes on its own.")
            return EXIT_STOPPED
        if signals.count == 1 and not ended_by_us:
            ended_by_us = True
            _end(console, daemon.client, active)
        if clock() >= next_read:
            next_read = clock() + FOLLOW_INTERVAL_S
            try:
                session = daemon.client.validation_session()
            except (DaemonUnavailable, DaemonTimeout, DaemonError, OSError):
                session = None
            # No answer and "no session" count alike: either way this session
            # cannot be followed, and the daemon ends it on its own.
            if session is None:
                failures += 1
                if failures >= MAX_POLL_FAILURES:
                    console.out("The daemon stopped reporting this session. It ends it on its own.")
                    return EXIT_INTERRUPTED
            else:
                failures = 0
            if session is not None and session.session_id != session_id:
                console.out("Another session replaced this one.")
                return EXIT_INTERRUPTED
            if session is not None:
                if not session.is_recording:
                    console.out("")
                    render(console, session, daemon)
                    if session.state == VALIDATION_STATE_CANCELLED:
                        return EXIT_CANCELLED
                    return EXIT_OK if session.state == VALIDATION_STATE_COMPLETED else EXIT_FAILED
                if (
                    len(session.evidence) != seen_evidence
                    or clock() - last_progress >= PROGRESS_EVERY_S
                ):
                    seen_evidence = len(session.evidence)
                    last_progress = clock()
                    elapsed = format_elapsed(
                        session.samples[-1].elapsed_ms if session.samples else 0
                    )
                    console.out(
                        f"  {elapsed}: {len(session.samples)} samples, "
                        f"{seen_evidence} diagnostic result(s)"
                    )
        sleep(0.2)


def _end(console: Console, client: DaemonClient, active: bool) -> None:
    """End the session: cancel an active one and the diagnostic it is running
    (the session itself only stops between diagnostics), or stop a passive one.
    Each request is tried on its own, so a refused one does not skip the rest."""
    if active:
        console.out("Cancelling the session…")
        steps = [
            ("session", client.cancel_validation_session),
            ("characterisation", lambda: _cancel_running(client, "characterization")),
            ("control-path discovery", lambda: _cancel_running(client, "control_path")),
        ]
    else:
        console.out("Stopping the recording…")
        steps = [("session", client.stop_validation_session)]
    for what, step in steps:
        try:
            step()
        except DaemonError as e:
            console.out(f"  {what}: {e.message}")


def _cancel_running(client: DaemonClient, slot: str) -> bool:
    """Cancel the run in *slot* if one is running; True when a cancel was sent."""
    status = poll_slot(client, slot)
    run = getattr(status, "run", status)  # control-path wraps its run
    if run is None or run.state != "running":
        return False
    cancel_slot(client, slot)
    return True


def status_cmd(console: Console, daemon: Daemon) -> int:
    daemon.require("validation_sessions")
    session = daemon.client.validation_session()
    if session is None:
        console.out("No validation session has been run.")
        return EXIT_OK
    render(console, session, daemon)
    return EXIT_OK


def end_cmd(console: Console, daemon: Daemon, *, cancel: bool) -> int:
    daemon.require("validation_sessions")
    try:
        session = (
            daemon.client.cancel_validation_session()
            if cancel
            else daemon.client.stop_validation_session()
        )
    except DaemonError as e:
        raise DiagError(EXIT_REFUSED, e.message) from e
    render(console, session, daemon)
    return EXIT_OK


def marker_cmd(console: Console, daemon: Daemon, text: str | None, member: str | None) -> int:
    daemon.require("validation_sessions")
    try:
        daemon.client.add_validation_marker(text, member)
    except DaemonError as e:
        raise DiagError(EXIT_REFUSED, e.message) from e
    console.out("Marker recorded.")
    return EXIT_OK


def measure_cmd(
    console: Console,
    daemon: Daemon,
    kind: str,
    value: float,
    *,
    unit: str,
    member: str | None,
    note: str | None,
) -> int:
    daemon.require("validation_sessions")
    try:
        daemon.client.add_validation_measurement(
            kind, value, unit=unit, member_id=member, note=note
        )
    except DaemonError as e:
        raise DiagError(EXIT_REFUSED, e.message) from e
    console.out("Measurement recorded (kept as evidence; nothing acts on it).")
    return EXIT_OK


def list_cmd(console: Console, daemon: Daemon) -> int:
    daemon.require("validation_sessions")
    entries = daemon.client.validation_sessions()
    if not entries:
        console.out("No saved sessions.")
        return EXIT_OK
    for e in entries:
        console.out(
            f"{e.session_id}  {e.kind:<18}  {e.state:<11}  {e.device_name}  "
            f"{e.sample_count} samples"
        )
    return EXIT_OK


def _session(daemon: Daemon, session_id: str) -> ValidationSession:
    daemon.require("validation_sessions")
    session = daemon.client.validation_session_by_id(session_id)
    if session is None:
        raise DiagError(EXIT_REFUSED, f"No saved session has the id {session_id!r}.")
    return session


def show_cmd(console: Console, daemon: Daemon, session_id: str) -> int:
    render(console, _session(daemon, session_id), daemon)
    return EXIT_OK


def export_cmd(console: Console, daemon: Daemon, session_id: str, fmt: str, output: Path) -> int:
    from ventulus.paths import atomic_write
    from ventulus.services.validation_export import (
        session_events_csv,
        session_findings_csv,
        session_json,
        session_samples_csv,
    )

    session = _session(daemon, session_id)
    try:
        if fmt == "json":
            atomic_write(output, session_json(session))
            console.out(f"Wrote {output}")
            return EXIT_OK
        output.mkdir(parents=True, exist_ok=True)
        for name, fn in (
            ("samples", session_samples_csv),
            ("events", session_events_csv),
            ("findings", session_findings_csv),
        ):
            target = output / f"validation-{session.session_id}-{name}.csv"
            atomic_write(target, fn(session))
            console.out(f"Wrote {target}")
    except OSError as e:
        raise DiagError(EXIT_FAILED, f"Could not write {output}: {e}") from e
    return EXIT_OK
