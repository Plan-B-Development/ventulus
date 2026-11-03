"""``ventulus-diag characterise`` and ``ventulus-diag discover`` (DEC-503).

One header, one daemon diagnostic, followed to its end. The daemon owns the
duties, the pump floor, every guard and the restore; this module asks for the
run, polls it once a second, and prints the same result the GUI's dialog drew,
from the same Qt-free view models.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ventulus.api.errors import DaemonError, DaemonTimeout, DaemonUnavailable
from ventulus.api.models import (
    DIAGNOSTIC_CHARACTERIZATION,
    DIAGNOSTIC_CONTROL_PATH,
    HwmonHeader,
)
from ventulus.diag.confirm import confirm_writes, describe
from ventulus.diag.console import (
    EXIT_ABORTED,
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
from ventulus.services import diagnostic_estimates as est
from ventulus.services.characterization_view import (
    build_characterization_view,
    pre_run_warnings,
)
from ventulus.services.control_path_view import build_control_path_view
from ventulus.services.daemon_features import daemon_supports
from ventulus.services.preflight_view import build_preflight_view
from ventulus.services.pump_protection import header_is_pump_protected

#: Consecutive failed status reads before the run is treated as lost.
MAX_POLL_FAILURES = 5

_STATE_EXIT = {
    "complete": EXIT_OK,
    "cancelled": EXIT_CANCELLED,
    "aborted": EXIT_ABORTED,
    "failed": EXIT_FAILED,
}


@dataclass(frozen=True)
class SweepKind:
    """What differs between the two commands."""

    name: str
    feature_id: str
    diagnostic: str
    start: Callable[[Any, str, bool], Any]
    status: Callable[[Any], Any]
    cancel: Callable[[Any], Any]
    render: Callable[[Console, Any, str], None]
    description: Callable[[str], str]
    seconds: Callable[[bool], int]


def _run_of(status: Any) -> Any:
    """``GET /diagnostics/control-path`` wraps its run; characterisation does not."""
    return getattr(status, "run", status)


def _render_characterization(console: Console, run: Any, label: str) -> None:
    view = build_characterization_view(run, header_label=label)
    console.out(f"{label}: {view.status_text}")
    for chip in view.verdicts:
        console.out(f"  {chip.label}: {chip.value}")
    if view.observed_range:
        console.out(f"  Observed range: {view.observed_range}")
    for row in view.summary_rows:
        console.out(f"  {row.label}: {row.value}")
    if view.rows:
        console.out("")
        console.out("  Duty   Readback  RPM      Result")
        for r in view.rows:
            console.out(f"  {r.pwm:<6} {r.readback:<9} {r.rpm:<8} {r.result}")
    for note in view.notes:
        console.out(f"  Note: {note}")
    if view.override_warning:
        console.out(f"  ! {view.override_warning}")


def _render_control_path(console: Console, run: Any, label: str) -> None:
    view = build_control_path_view(run, header_label=label)
    console.out(f"{label}: {view.status_text}")
    if view.relationship_word:
        console.out(f"  Relationship: {view.relationship_word} ({view.confidence_word})")
    if view.perturbation_text:
        console.out(f"  {view.perturbation_text}")
    for c in view.candidates:
        console.out(
            f"  Responds: {c.label} ({c.tach_id}) — {c.direction_text}, {c.baseline_text} → "
            f"{c.perturbed_text} ({c.change_text}), {c.confidence_word}"
        )
    for q in view.quiet:
        console.out(f"  No response: {q.label} ({q.tach_id})")
    for note in view.notes:
        console.out(f"  Note: {note}")
    if view.restore_warning:
        console.out(f"  ! {view.restore_warning}")


CHARACTERISE = SweepKind(
    name="characterisation",
    feature_id="pwm_characterization",
    diagnostic=DIAGNOSTIC_CHARACTERIZATION,
    # Tuning arguments left to the daemon, as the GUI's dialog did: it owns the
    # point list, the settle window and the pump floor. The bidirectional walk is
    # asked for only where the daemon serves it (DEC-334 Q3).
    start=lambda c, h, behaviour: c.start_characterization(
        h, bidirectional=True if behaviour else None
    ),
    status=lambda c: c.characterization_status(),
    cancel=lambda c: c.cancel_characterization(),
    render=_render_characterization,
    description=lambda name: (
        f"Walks {name} across the daemon's duty points and holds each while RPM "
        "settles, then puts it back."
    ),
    seconds=lambda behaviour: est.characterization_seconds(
        est.CHARACTERIZATION_DEFAULT_POINT_COUNT, bidirectional=behaviour, stability=False
    ),
)

DISCOVER = SweepKind(
    name="control-path discovery",
    feature_id="control_path_discovery",
    diagnostic=DIAGNOSTIC_CONTROL_PATH,
    start=lambda c, h, _behaviour: c.start_control_path_discovery(h),
    status=lambda c: c.control_path_status(),
    cancel=lambda c: c.cancel_control_path_discovery(),
    render=_render_control_path,
    description=lambda name: (
        f"Nudges {name} up or down by a few points, twice, and watches every fan's RPM "
        "to see which one follows it, then puts it back."
    ),
    seconds=lambda _behaviour: est.discovery_seconds(worst_case=True),
)


def _preflight(console: Console, daemon: Daemon, header: HwmonHeader, kind: SweepKind) -> None:
    """Print the daemon's verdict; a ``blocked`` one refuses. Advice only: the
    start's own guards still run.

    Probed, not gated on ``diagnostic_preflight`` (``P8-as``): the route answers
    only 200 or 400, so a 404 can only mean a daemon without it.
    """
    try:
        report = daemon.client.diagnostic_preflight(header.id, kind.diagnostic)
    except DaemonError as e:
        if e.status == 404:
            console.out("This daemon has no safety preflight; its own guards still run.")
        else:
            console.out(
                f"The safety preflight could not be read ({e.message}); "
                "the daemon's own guards still run."
            )
        return
    # The GUI's rendering, so a blocker the daemon names in `blocking` refuses
    # even under a verdict token this version does not know (fails safe).
    view = build_preflight_view(report)
    console.out(f"Daemon preflight: {view.verdict_word}")
    for row in view.rows:
        if row.state not in ("pass", "not_applicable"):
            console.out(f"  {row.state_word}: {row.label} — {row.detail}")
    if not view.can_start:
        reasons = "".join(f"\n  {r}" for r in view.blocking_reasons)
        raise DiagError(
            EXIT_REFUSED, f"Not started: the daemon's safety preflight blocked this test.{reasons}"
        )


def run_sweep(
    console: Console,
    daemon: Daemon,
    header_id: str,
    kind: SweepKind,
    *,
    confirmed_by_flag: bool,
    interrupts: Interrupts | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    daemon.require(kind.feature_id)
    header = daemon.header(header_id)
    name = daemon.name_of(header.id)
    if not header.is_writable:
        raise DiagError(EXIT_REFUSED, f"{name} is read-only, so nothing can drive it.")
    reasons = start_refusal(daemon.status())
    if reasons:
        raise DiagError(EXIT_REFUSED, "Cannot start now:\n" + "\n".join(f"  {r}" for r in reasons))
    _preflight(console, daemon, header, kind)
    behaviour = daemon_supports("pwm_behaviour_characterization", daemon.capabilities) is True
    is_pump = header_is_pump_protected(header, daemon.capabilities)
    describe(
        console,
        f"This runs {kind.name} on {name} ({header.id}), up to "
        f"{est.duration_words(kind.seconds(behaviour))}:",
        [kind.description(name)],
        pre_run_warnings(header, is_pump=is_pump),
    )
    refusal = confirm_writes(console, flag_given=confirmed_by_flag)
    if refusal:
        raise DiagError(EXIT_REFUSED, refusal)
    # Interrupts are counted from before the start request: a Ctrl-C while it is
    # in flight then becomes the daemon's cancel once the run exists, rather than
    # an exit that leaves a run the user believes never started.
    with interrupts if interrupts is not None else Interrupts() as signals:
        try:
            started = kind.start(daemon.client, header.id, behaviour)
        except DaemonTimeout as e:
            # It may have started: cancel rather than leave it running unseen.
            problem = daemon.best_effort(kind.cancel)
            sent = "a cancel was sent" if not problem else f"a cancel could not be sent ({problem})"
            raise DiagError(
                EXIT_INTERRUPTED,
                f"No answer from the daemon ({e.message}); {sent}. If the test started, "
                "the daemon puts the header back when it ends.",
            ) from e
        except DaemonUnavailable as e:
            raise DiagError(
                EXIT_INTERRUPTED,
                f"No answer from the daemon ({e.message}). If the test started, the daemon "
                "puts the header back when it ends.",
            ) from e
        except DaemonError as e:
            raise DiagError(EXIT_REFUSED, f"The daemon did not start it: {e.message}") from e
        run_id = getattr(started, "run_id", "")
        return _follow(console, daemon, kind, name, run_id, signals, clock, sleep)


def _follow(
    console: Console,
    daemon: Daemon,
    kind: SweepKind,
    name: str,
    run_id: str,
    signals: Interrupts,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
) -> int:
    console.out(f"Started {kind.name} on {name}. Ctrl-C to stop it.")
    cancel_sent = False
    failures = 0
    last_progress = ""
    next_poll = clock()
    while True:
        if signals.count >= 2:
            if not cancel_sent:  # both signals came before the loop could send it
                cancel_sent = True
                problem = daemon.best_effort(kind.cancel)
                console.out(
                    "Sent the daemon's cancel." if not problem else f"Cancel not sent: {problem}"
                )
            console.out(
                "Stopped at once. The daemon ends the test on its own and puts the header back."
            )
            return EXIT_STOPPED
        if signals.count == 1 and not cancel_sent:
            cancel_sent = True
            console.out(
                f"Cancelling ({signals.name()}): the daemon finishes the step it is on and "
                "puts the header back. Interrupt again to stop waiting."
            )
            try:
                kind.cancel(daemon.client)
            except DaemonError as e:  # 409 = it had already ended; the poll shows it
                console.out(f"  ({e.message})")
        if clock() >= next_poll:
            next_poll = clock() + 1.0
            try:
                run = _run_of(kind.status(daemon.client))
                failures = 0
            except (DaemonUnavailable, DaemonTimeout, DaemonError, OSError):
                failures += 1
                if failures >= MAX_POLL_FAILURES:
                    console.out(
                        "The daemon stopped answering. It puts the header back when its test ends."
                    )
                    return EXIT_INTERRUPTED
                run = None
            if run is not None:
                if run_id and run.run_id and run.run_id != run_id:
                    console.out("Another diagnostic took the daemon's diagnostic slot.")
                    return EXIT_INTERRUPTED
                state = run.state
                if state != "running":
                    console.out("")
                    kind.render(console, run, name)
                    return _STATE_EXIT.get(state, EXIT_FAILED)
                progress = _progress(run)
                if progress and progress != last_progress:
                    last_progress = progress
                    console.out(f"  {progress}")
        sleep(0.1)


def _progress(run: Any) -> str:
    """One line when what the daemon is doing changes: the phase and duty of its
    current step, and how many sweep points are done."""
    parts: list[str] = []
    points = getattr(run, "points", None)
    requested = getattr(run, "requested_points_pct", None)
    if points is not None and requested:
        parts.append(f"{len(points)} of {len(requested)} points measured")
    step = getattr(run, "current_step", None)
    if step is not None and getattr(step, "phase", ""):
        parts.append(f"{step.phase.replace('_', ' ')} at {step.duty_pct}%")
    return "; ".join(parts)
