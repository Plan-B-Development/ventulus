"""``ventulus-diag`` command line (DEC-503). See ``man ventulus-diag``."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path

from ventulus.api.errors import DaemonError, DaemonTimeout, DaemonUnavailable
from ventulus.constants import APP_VERSION, DEFAULT_SOCKET_PATH
from ventulus.diag import report, sweeps, validation
from ventulus.diag.confirm import ALLOW_STOP_FLAG, CONFIRM_FLAG
from ventulus.diag.console import (
    EXIT_FAILED,
    EXIT_INCOMPATIBLE,
    EXIT_OK,
    EXIT_REFUSED,
    EXIT_UNAVAILABLE,
    Console,
    DiagError,
)
from ventulus.diag.daemon import Daemon, connect, start_refusal, unreachable_message
from ventulus.services.pwm_report import catalog as cat
from ventulus.services.pwm_report.executor import SLOTS

DESCRIPTION = (
    "Diagnostics for Ventulus. Read-only commands inspect; test commands change fan "
    "speeds through the daemon and need confirmation. Every test is performed and "
    "undone by ventulusd, which puts each header back when a test ends, even if this "
    "tool is killed."
)

_PREFLIGHT_TESTS = {
    "verify": cat.SPECS[cat.TEST_VERIFY].diagnostic,
    "pairing": cat.SPECS[cat.TEST_PAIRING].diagnostic,
    "sweep": cat.SPECS[cat.TEST_SWEEP].diagnostic,
    "probe": cat.SPECS[cat.TEST_PROBE].diagnostic,
}


def _add_confirm(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        CONFIRM_FLAG,
        dest="confirmed",
        action="store_true",
        help="confirm that this test may change fan speeds (needed when not on a terminal)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ventulus-diag", description=DESCRIPTION)
    parser.add_argument("--socket", default=DEFAULT_SOCKET_PATH, help="daemon socket path")
    parser.add_argument("--version", action="version", version=f"ventulus-diag {APP_VERSION}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    sub.add_parser("status", help="daemon, thermal state and any running test (read-only)")
    sub.add_parser("headers", help="motherboard headers and the tests each offers (read-only)")
    sub.add_parser(
        "cancel",
        help="cancel a running characterisation, discovery or stall probe, whoever started it",
    )
    p = sub.add_parser("preflight", help="the daemon's safety verdict for one test (read-only)")
    p.add_argument("header", help="header id (see: headers)")
    p.add_argument("test", choices=sorted(_PREFLIGHT_TESTS))

    # ── report ──────────────────────────────────────────────────────────────
    rp = sub.add_parser("report", help="the PWM Test Report: run, list, show, export, compare")
    rsub = rp.add_subparsers(dest="report_command", required=True, metavar="ACTION")
    run = rsub.add_parser("run", help="run a report (changes fan speeds unless --snapshot-only)")
    run.add_argument("--header", action="append", default=[], help="test only this header (repeat)")
    run.add_argument(
        "--test",
        action="append",
        default=[],
        choices=sorted(report.TEST_NAMES),
        help="tests to run on each header (repeat; default: verify and pairing)",
    )
    run.add_argument(
        "--stall-probe",
        action="append",
        default=[],
        metavar="HEADER",
        help="also run the stall/restart probe on HEADER; the fan may stop (repeat)",
    )
    run.add_argument(
        ALLOW_STOP_FLAG,
        dest="allow_fan_stop",
        action="append",
        default=[],
        metavar="HEADER",
        help="allow the stall/restart probe to stop the fan on HEADER without a prompt",
    )
    run.add_argument(
        "--snapshot-only", action="store_true", help="read-only: record state, test nothing"
    )
    run.add_argument("--notes", type=Path, help="JSON file with your setup facts")
    run.add_argument("--dry-run", action="store_true", help="print the plan and exit")
    _add_confirm(run)
    rsub.add_parser("list", help="saved reports, newest first")
    show = rsub.add_parser("show", help="print a saved report")
    show.add_argument("report", help="report id, unique id prefix, or path")
    exp = rsub.add_parser("export", help="write a saved report to a file")
    exp.add_argument("report")
    exp.add_argument("--format", choices=report.EXPORT_FORMATS, default="markdown")
    exp.add_argument("--output", "-o", type=Path, required=True, help="file (a folder for csv)")
    cmp = rsub.add_parser("compare", help="compare two saved reports")
    cmp.add_argument("first")
    cmp.add_argument("second")
    cmp.add_argument("--format", choices=("markdown", "html"), default="markdown")
    cmp.add_argument("--output", "-o", type=Path)

    # ── single-header tests ─────────────────────────────────────────────────
    for name, help_text in (
        ("characterise", "sweep one header's PWM response (changes fan speeds)"),
        ("discover", "find which tach follows one header (changes fan speeds)"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("header", help="header id (see: headers)")
        _add_confirm(p)

    # ── validation sessions ─────────────────────────────────────────────────
    vp = sub.add_parser("validation", help="AIO validation, lifecycle and thermal sessions")
    vsub = vp.add_subparsers(dest="validation_command", required=True, metavar="ACTION")
    vsub.add_parser("devices", help="configured cooling devices")
    st = vsub.add_parser("start", help="start a session (changes fan speeds with --diagnostic)")
    st.add_argument("--device", required=True, help="cooling device id (see: devices)")
    st.add_argument("--kind", choices=sorted(validation.KINDS), default="validation")
    st.add_argument(
        "--diagnostic",
        action="append",
        default=[],
        choices=sorted(validation.DIAGNOSTICS),
        help="a diagnostic the daemon runs on the swept members (repeat)",
    )
    st.add_argument(
        "--sweep-member",
        action="append",
        default=[],
        metavar="MEMBER",
        help="member to sweep (repeat; default: the device's pump)",
    )
    st.add_argument("--meta", action="append", default=[], metavar="KEY=VALUE")
    st.add_argument(
        "--auto-stop", action="store_true", help="end the session when the diagnostics finish"
    )
    st.add_argument("--detach", action="store_true", help="start it and return at once")
    _add_confirm(st)
    vsub.add_parser("status", help="the current or most recent session")
    vsub.add_parser("stop", help="stop the recording session and save it")
    vsub.add_parser("cancel", help="end the session as cancelled (it is still saved)")
    mk = vsub.add_parser("marker", help="mark the session timeline")
    mk.add_argument("text", nargs="?")
    mk.add_argument("--member")
    ms = vsub.add_parser("measure", help="attach an external reading (evidence only)")
    ms.add_argument("kind")
    ms.add_argument("value", type=float)
    ms.add_argument("--unit", default="")
    ms.add_argument("--member")
    ms.add_argument("--note")
    vsub.add_parser("list", help="saved sessions")
    vs = vsub.add_parser("show", help="print a saved session")
    vs.add_argument("session")
    ve = vsub.add_parser("export", help="write a saved session to files")
    ve.add_argument("session")
    ve.add_argument("--format", choices=("json", "csv"), default="json")
    ve.add_argument("--output", "-o", type=Path, required=True)
    return parser


# ── read-only commands ───────────────────────────────────────────────────────


def status_cmd(console: Console, daemon: Daemon) -> int:
    status = daemon.status()
    caps = daemon.capabilities
    console.out(f"ventulusd {caps.daemon_version} at {daemon.socket_path}")
    console.out(f"Thermal state: {status.thermal_state}")
    console.out(f"A diagnostic holds the slot: {'yes' if status.verify_active else 'no'}")
    session = getattr(status, "validation_session", None)
    if session is not None and session.is_recording:
        console.out(f"Validation session recording: {session.session_id}")
    reasons = start_refusal(status)
    console.out(
        "A test could start now."
        if not reasons
        else "A test cannot start now: " + "; ".join(reasons)
    )
    return EXIT_OK


def headers_cmd(console: Console, daemon: Daemon) -> int:
    channels = cat.build_channels(
        daemon.headers,
        daemon.client.fans(),
        daemon.capabilities,
        name_of=daemon.name_of,
        profile_member_ids=daemon.profile_member_ids(),
    )
    hwmon = [ch for ch in channels if ch.is_hwmon]
    if not hwmon:
        console.out(
            "The daemon reports no motherboard fan headers. If your board has some, the "
            "driver for its fan chip may not be loaded: see Drivers and Other Fan Software "
            "in the manual's Administration section."
        )
        return EXIT_OK
    for ch in hwmon:
        rpm = "—" if ch.rpm is None else str(ch.rpm)
        # `effective_min_pwm_pct` is the header-level floor (device policy, pump
        # backstop). The CPU fan floor is a profile-level rule the field does not
        # carry, so a 0 there for a CPU fan would read as "may stop": show it only
        # where it is the pump floor.
        pump_floor = (
            f"pump floor {ch.effective_min_pwm_pct}%"
            if ch.pump_protected and ch.effective_min_pwm_pct is not None
            else ("pump-protected" if ch.pump_protected else "")
        )
        flags = [
            "writable" if ch.writable else "read-only",
            pump_floor,
            "in profile" if ch.in_profile else "",
        ]
        console.out(f"{ch.channel_id}  {ch.name}")
        console.out(
            f"    role {ch.role} ({ch.role_source}); rpm {rpm}; " + ", ".join(f for f in flags if f)
        )
        offered = [
            name
            for name, test in (*report.TEST_NAMES.items(), ("stall-probe", cat.TEST_PROBE))
            if cat.availability(ch, test, daemon.capabilities).available
        ]
        console.out(f"    tests: {', '.join(offered) or 'none'}")
    return EXIT_OK


_SLOT_NAMES = {
    "characterization": "characterisation",
    "control_path": "control-path discovery",
    "stall_probe": "stall/restart probe",
}


def cancel_cmd(console: Console, daemon: Daemon) -> int:
    """Cancel whatever single-header test is running, from any client. Needs no
    confirmation: a cancel only ever ends a test, and the daemon restores the
    header. The PWM control test (verify) is not cancellable: it ends by itself
    within seconds."""
    from ventulus.diag.validation import _cancel_running

    sent = []
    for slot in SLOTS:
        try:
            if _cancel_running(daemon.client, slot):
                sent.append(_SLOT_NAMES.get(slot, slot))
        except DaemonError as e:
            console.err(f"{_SLOT_NAMES.get(slot, slot)}: {e.message}")
    if not sent:
        console.out("Nothing to cancel: no characterisation, discovery or probe is running.")
        return EXIT_OK
    for what in sent:
        console.out(f"Cancelled the {what}; the daemon puts the header back.")
    return EXIT_OK


def preflight_cmd(console: Console, daemon: Daemon, header_id: str, test: str) -> int:
    """Probed rather than gated (``P8-as``): only an older daemon answers 404."""
    header = daemon.header(header_id)
    try:
        report_ = daemon.client.diagnostic_preflight(header.id, _PREFLIGHT_TESTS[test])
    except DaemonError as e:
        if e.status == 404:
            raise DiagError(EXIT_INCOMPATIBLE, "This daemon has no safety preflight.") from e
        raise
    console.out(f"{daemon.name_of(header.id)} — {test}: {report_.verdict}")
    for check in report_.checks:
        console.out(f"  {check.state:<14} {check.check_id}: {check.detail}")
    return EXIT_REFUSED if report_.is_blocked else EXIT_OK


# ── dispatch ─────────────────────────────────────────────────────────────────


def _offline(args: argparse.Namespace) -> bool:
    """Saved-report commands need no daemon."""
    return args.command == "report" and args.report_command in ("list", "show", "export", "compare")


def dispatch(
    args: argparse.Namespace, console: Console, daemon_factory: Callable[[str], Daemon]
) -> int:
    if _offline(args):
        rc = args.report_command
        if rc == "list":
            return report.list_cmd(console)
        if rc == "show":
            return report.show_cmd(console, args.report)
        if rc == "export":
            return report.export_cmd(console, args.report, args.format, args.output)
        return report.compare_cmd(console, args.first, args.second, args.format, args.output)
    daemon = daemon_factory(args.socket)
    try:
        return _with_daemon(args, console, daemon)
    finally:
        daemon.close()


def _with_daemon(args: argparse.Namespace, console: Console, daemon: Daemon) -> int:
    cmd = args.command
    if cmd == "status":
        return status_cmd(console, daemon)
    if cmd == "headers":
        return headers_cmd(console, daemon)
    if cmd == "cancel":
        return cancel_cmd(console, daemon)
    if cmd == "preflight":
        return preflight_cmd(console, daemon, args.header, args.test)
    if cmd == "report":
        return report.run_report(
            console,
            daemon,
            report.RunRequest(
                headers=tuple(args.header),
                tests=tuple(dict.fromkeys(args.test)),
                stall_probe=tuple(dict.fromkeys(args.stall_probe)),
                allow_fan_stop=tuple(args.allow_fan_stop),
                snapshot_only=args.snapshot_only,
                notes_file=args.notes,
                confirmed_by_flag=args.confirmed,
                dry_run=args.dry_run,
            ),
        )
    if cmd in ("characterise", "discover"):
        kind = sweeps.CHARACTERISE if cmd == "characterise" else sweeps.DISCOVER
        return sweeps.run_sweep(
            console, daemon, args.header, kind, confirmed_by_flag=args.confirmed
        )
    vc = args.validation_command
    if vc == "devices":
        return validation.devices_cmd(console, daemon)
    if vc == "start":
        return validation.start_cmd(
            console,
            daemon,
            validation.StartRequest(
                device_id=args.device,
                kind=args.kind,
                diagnostics=tuple(dict.fromkeys(args.diagnostic)),
                sweep_members=tuple(args.sweep_member),
                metadata=tuple(args.meta),
                auto_stop=args.auto_stop,
                detach=args.detach,
                confirmed_by_flag=args.confirmed,
            ),
        )
    if vc == "status":
        return validation.status_cmd(console, daemon)
    if vc in ("stop", "cancel"):
        return validation.end_cmd(console, daemon, cancel=vc == "cancel")
    if vc == "marker":
        return validation.marker_cmd(console, daemon, args.text, args.member)
    if vc == "measure":
        return validation.measure_cmd(
            console,
            daemon,
            args.kind,
            args.value,
            unit=args.unit,
            member=args.member,
            note=args.note,
        )
    if vc == "list":
        return validation.list_cmd(console, daemon)
    if vc == "show":
        return validation.show_cmd(console, daemon, args.session)
    return validation.export_cmd(console, daemon, args.session, args.format, args.output)


def main(
    argv: Sequence[str] | None = None,
    *,
    console: Console | None = None,
    daemon_factory: Callable[[str], Daemon] = connect,
) -> int:
    args = build_parser().parse_args(argv)
    console = console or Console()
    try:
        return dispatch(args, console, daemon_factory)
    except DiagError as e:
        console.err(e.message)
        return e.code
    except (DaemonUnavailable, DaemonTimeout) as e:
        console.err(unreachable_message(args.socket, e))
        return EXIT_UNAVAILABLE
    except DaemonError as e:
        console.err(f"The daemon answered with an error: {e.message}")
        return EXIT_FAILED
    except KeyboardInterrupt:
        # Only reachable before a test starts (a run installs its own handler):
        # nothing was asked of the daemon.
        console.err("Interrupted before anything started.")
        return EXIT_REFUSED
