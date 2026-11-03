"""``ventulus-diag report`` — run, list, show, export and compare PWM Test Reports.

The run drives the same pure :class:`~ventulus.services.pwm_report.runner.ReportRunner`
the GUI drove, through the same call executor, and saves to the same reports
folder, so a report is the same document whichever produced it (DEC-503). This
module owns only the loop: a worker thread for the daemon calls (a verify blocks
for about six seconds), a 1 Hz ``/poll`` for the trace and the thermal state,
checkpoints, and the interrupts.
"""

from __future__ import annotations

import json
import platform
import queue
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from ventulus.api.errors import DaemonError, DaemonTimeout, DaemonUnavailable
from ventulus.constants import APP_VERSION
from ventulus.diag.confirm import (
    confirm_fan_stops,
    confirm_writes,
    describe,
)
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
from ventulus.paths import load_json_capped
from ventulus.services.diagnostic_estimates import duration_words
from ventulus.services.pwm_report import catalog as cat
from ventulus.services.pwm_report import document as d
from ventulus.services.pwm_report import store
from ventulus.services.pwm_report.executor import OwnedClient, ReportCallExecutor, cancel_slot
from ventulus.services.pwm_report.runner import (
    REASON_CANCELLED,
    Call,
    CallOutcome,
    ReportRunner,
    build_plan,
)
from ventulus.services.pwm_report.setup_facts import coerce_cooler_notes, coerce_hardware_notes
from ventulus.services.pwm_report.trace import TraceRecorder
from ventulus.services.pwm_report.view import build_report_view, step_status

CLIENT_NAME = "ventulus-diag"
REASON_TOOL_STOPPED = "ventulus-diag was stopped during the run."
#: Consecutive failed ``/poll`` reads before the daemon is treated as gone. The
#: runner's own slot polls also count failures; this covers a verify, which
#: makes no slot poll.
MAX_POLL_FAILURES = 5
#: How long the stop-at-once path may spend telling the daemon to cancel.

TEST_NAMES = {
    "verify": cat.TEST_VERIFY,
    "pairing": cat.TEST_PAIRING,
    "sweep": cat.TEST_SWEEP,
}

_STATE_EXIT = {
    d.STATE_COMPLETE: EXIT_OK,
    d.STATE_CANCELLED: EXIT_CANCELLED,
    d.STATE_ABORTED: EXIT_ABORTED,
    d.STATE_INTERRUPTED: EXIT_INTERRUPTED,
}


# ── Planning ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RunRequest:
    headers: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    stall_probe: tuple[str, ...] = ()
    allow_fan_stop: tuple[str, ...] = ()
    snapshot_only: bool = False
    notes_file: Path | None = None
    confirmed_by_flag: bool = False
    dry_run: bool = False


def select(
    channels: list[cat.Channel], capabilities: object | None, request: RunRequest
) -> tuple[dict[str, frozenset[str]], list[str]]:
    """The tests to run per header, and a line for each requested test not offered.

    No ``--header``: the GUI's default (decision 5) — the chosen tests on every
    writable header with a fan turning. ``--header``: those headers only, fan or
    not. A requested stall probe that is not offered refuses the run.
    """
    by_id = {c.channel_id: c for c in channels}
    for hid in (*request.headers, *request.stall_probe):
        if hid not in by_id:
            raise DiagError(
                EXIT_REFUSED,
                f"No channel has the id {hid!r}. Run ventulus-diag headers to list them.",
            )
    if request.snapshot_only:
        return {}, []
    tests = [TEST_NAMES[t] for t in request.tests] or [cat.TEST_VERIFY, cat.TEST_PAIRING]
    if request.headers:
        targets = [by_id[h] for h in request.headers]
    else:
        targets = [c for c in channels if c.is_hwmon and c.writable and c.fan_detected]
    selection: dict[str, set[str]] = {}
    skipped: list[str] = []
    for ch in targets:
        for test in tests:
            avail = cat.availability(ch, test, capabilities)
            if avail.available:
                selection.setdefault(ch.channel_id, set()).add(test)
            elif request.headers or request.tests:
                skipped.append(f"{ch.name} — {cat.SPECS[test].title}: {avail.reason}")
    for hid in request.stall_probe:
        ch = by_id[hid]
        avail = cat.availability(ch, cat.TEST_PROBE, capabilities)
        if not avail.available:
            raise DiagError(
                EXIT_REFUSED, f"The stall/restart probe is not offered on {ch.name}: {avail.reason}"
            )
        selection.setdefault(hid, set()).add(cat.TEST_PROBE)
    if not selection and (request.headers or request.tests):
        raise DiagError(
            EXIT_REFUSED,
            "Nothing you asked for can run:\n"
            + "\n".join(f"  {line}" for line in skipped)
            + "\nUse --snapshot-only for a read-only report.",
        )
    return {k: frozenset(v) for k, v in selection.items()}, skipped


def plan_lines(
    channels: Iterable[cat.Channel], selection: Mapping[str, Iterable[str]]
) -> list[str]:
    """The plain-words plan the user confirms — also saved in the report."""
    names = {c.channel_id: c.name for c in channels}
    lines: list[str] = []
    for step in build_plan(selection):
        spec = cat.SPECS[step.test]
        name = names.get(step.channel_id, step.channel_id)
        lines.append(
            f"{name} ({step.channel_id}) — {spec.title}: {spec.consent.format(name=name)} "
            f"(up to {duration_words(spec.worst_s)})"
        )
    return lines


def read_notes(path: Path | None, daemon: Daemon) -> tuple[dict, dict]:
    """``(headers, cooler)`` setup facts: from *path* when given, else the GUI's
    saved answers. Coerced like the GUI's settings key (an untrusted mapping)."""
    if path is None:
        return dict(daemon.settings.hardware_notes), dict(daemon.settings.cooler_notes)
    try:
        raw = load_json_capped(path)  # bounded size; a bad file is a clean error
    except (OSError, ValueError) as e:
        raise DiagError(EXIT_REFUSED, f"Could not read the notes file {path}: {e}") from e
    if not isinstance(raw, dict):
        raise DiagError(EXIT_REFUSED, f"The notes file {path} is not a JSON object.")
    return coerce_hardware_notes(raw.get("headers")), coerce_cooler_notes(raw.get("cooler"))


def channel_dict(ch: cat.Channel) -> dict:
    return {
        "channel_id": ch.channel_id,
        "source": ch.source,
        "name": ch.name,
        "role": ch.role,
        "role_source": ch.role_source,
        "writable": ch.writable,
        "rpm_available": ch.rpm_available,
        "rpm": ch.rpm,
        "in_profile": ch.in_profile,
        "pump_protected": ch.pump_protected,
        "effective_min_pwm_pct": ch.effective_min_pwm_pct,
        "stop_permitted": ch.stop_permitted,
    }


def client_facts() -> dict:
    return {
        "client": CLIENT_NAME,
        "gui_version": APP_VERSION,
        "kernel": platform.release(),
        "python": platform.python_version(),
    }


# ── The call worker ──────────────────────────────────────────────────────────


class CallWorker:
    """Runs the runner's calls one at a time on a daemon thread.

    A daemon thread, so stopping at once does not wait for a verify still
    blocked in its six-second request: the daemon finishes and restores that
    header whatever this process does.
    """

    def __init__(self, socket_path: str) -> None:
        self._owned = OwnedClient(socket_path)
        self._executor = ReportCallExecutor(self._owned.get, self._owned.drop)
        self._owned.set_observer(self._executor.observe)
        self._requests: queue.Queue[Call | None] = queue.Queue()
        self._results: queue.Queue[tuple[int, CallOutcome]] = queue.Queue()
        self._thread = threading.Thread(target=self._loop, name="ventulus-diag-calls", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while True:
            call = self._requests.get()
            if call is None:
                return
            try:
                outcome = self._executor.execute(
                    call.kind, {"header_id": call.header_id, "args": dict(call.args)}
                )
            except Exception as e:  # the runner waits on every call: always answer
                outcome = CallOutcome(ok=False, category="error", error_message=str(e))
            self._results.put((call.req_id, outcome))

    def submit(self, calls: Iterable[Call]) -> None:
        for call in calls:
            self._requests.put(call)

    def drain(self) -> list[tuple[int, CallOutcome]]:
        out: list[tuple[int, CallOutcome]] = []
        while True:
            try:
                out.append(self._results.get_nowait())
            except queue.Empty:
                return out

    def close(self) -> None:
        self._requests.put(None)
        self._thread.join(timeout=0.5)
        if not self._thread.is_alive():
            self._owned.close()


# ── The run ──────────────────────────────────────────────────────────────────


class ReportRun:
    """One run, start to saved report. Inputs are injectable for tests."""

    def __init__(
        self,
        console: Console,
        runner: ReportRunner,
        *,
        worker: CallWorker,
        poll: Callable[[], tuple],
        cancel_now: Callable[[str], None],
        interrupts: Interrupts,
        directory: Path | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        names: Mapping[str, str] | None = None,
    ) -> None:
        self.console = console
        self.runner = runner
        self.worker = worker
        self._poll = poll
        self._cancel_now = cancel_now
        self.interrupts = interrupts
        self.directory = directory
        self._clock = clock
        self._sleep = sleep
        self._names = dict(names or {})
        self.trace = TraceRecorder()
        self.path: Path | None = None
        self.save_error = ""
        self._seen: dict[str, str] = {}
        self._saved = (-1, "")
        self._poll_failures = 0
        self._cancel_announced = False

    def run(self) -> int:
        start = self._clock()
        self.worker.submit(self.runner.start(start))
        next_tick = start
        while not self.runner.finished:
            now = self._clock()
            for req_id, outcome in self.worker.drain():
                self.worker.submit(self.runner.on_outcome(req_id, outcome, now))
            if self.interrupts.count >= 2:
                return self._stop_at_once(now)
            if self.interrupts.count == 1 and not self._cancel_announced:
                self._cancel_announced = True
                self.console.out(
                    f"Cancelling ({self.interrupts.name()}): the daemon ends the running test "
                    "and puts the header back. Interrupt again to stop at once."
                )
                self.worker.submit(self.runner.request_cancel(now, REASON_CANCELLED))
            if now >= next_tick:
                self._observe(now, start)
                self.worker.submit(self.runner.on_tick(now))
                next_tick = now + 1.0
            self._report_progress()
            self._checkpoint()
            if not self.runner.finished:
                self._sleep(0.1)
        self._report_progress()
        self._checkpoint(force=True)
        return self._finish()

    def _observe(self, now: float, start: float) -> None:
        try:
            status, sensors, fans = self._poll()
        except (DaemonUnavailable, DaemonTimeout, DaemonError, OSError):
            self._poll_failures += 1
            if self._poll_failures >= MAX_POLL_FAILURES:
                self.worker.submit(self.runner.observe(now, connected=False, thermal_state=""))
            return
        self._poll_failures = 0
        thermal = getattr(status, "thermal_state", "normal") or "normal"
        self.trace.add_sample(
            int((now - start) * 1000), thermal_state=thermal, fans=fans, sensors=sensors
        )
        self.worker.submit(self.runner.observe(now, connected=True, thermal_state=thermal))

    def _stop_at_once(self, now: float) -> int:
        slot = self.runner.active_slot
        if slot:
            try:
                self._cancel_now(slot)
            except Exception as e:  # best effort: the daemon restores regardless
                self.console.err(f"The cancel was not confirmed ({e}).")
        self.runner.abandon(now, REASON_TOOL_STOPPED)
        self._checkpoint(force=True)
        self.console.out(
            "Stopped. Any test still running ends on its own and the daemon puts its header back."
        )
        if self.path is not None:
            self.console.out(f"Partial report saved: {self.path}")
        return EXIT_STOPPED

    def _report_progress(self) -> None:
        done, total = self.runner.progress()
        for step in self.runner.doc["steps"]:
            sid, status = step["step_id"], step["status"]
            if self._seen.get(sid) == status:
                continue
            self._seen[sid] = status
            name = self._names.get(step["channel_id"], step["channel_id"])
            title = cat.SPECS[step["test"]].title if step["test"] in cat.SPECS else step["test"]
            if status == d.STEP_PENDING:
                continue
            if status == d.STEP_RUNNING:
                self.console.out(f"[{done + 1}/{total}] {name} — {title}: running…")
                continue
            label, _tone = step_status(status)
            line = f"[{done}/{total}] {name} — {title}: {label}"
            if step.get("reason"):
                line += f" — {step['reason']}"
            restore = step.get("restore_outcome")
            if restore:
                line += f" (header: {restore.replace('_', ' ')})"
            self.console.out(line)

    def _checkpoint(self, *, force: bool = False) -> None:
        done, _total = self.runner.progress()
        key = (done, self.runner.phase)
        if not force and key == self._saved:
            return
        self._saved = key
        self.runner.doc["trace"] = self.trace.to_dict()
        try:
            self.path = store.save_report(self.runner.doc, self.directory)
            self.save_error = ""
        except (OSError, ValueError) as e:
            self.save_error = str(e)

    def _finish(self) -> int:
        doc = self.runner.doc
        view = build_report_view(doc)
        self.console.out("")
        self.console.out(f"Report {view.report_id}: {view.state_label}")
        if view.state_reason:
            self.console.out(f"  {view.state_reason}")
        for line in view.summary_lines:
            self.console.out(f"  {line}")
        for row in view.attention:
            self.console.out(f"  ! {row.statement}")
        if self.save_error:
            self.console.err(f"The report could not be saved: {self.save_error}")
            return EXIT_FAILED
        if self.path is not None:
            self.console.out(f"Saved: {self.path}")
            self.console.out(f"Read it with: ventulus-diag report show {view.report_id}")
        return _STATE_EXIT.get(str(doc.get("state")), EXIT_FAILED)


def run_report(console: Console, daemon: Daemon, request: RunRequest) -> int:
    caps = daemon.capabilities
    fans = daemon.client.fans()
    channels = cat.build_channels(
        daemon.headers,
        fans,
        caps,
        name_of=daemon.name_of,
        profile_member_ids=daemon.profile_member_ids(),
    )
    selection, skipped = select(channels, caps, request)
    for line in skipped:
        console.out(f"Not offered: {line}")
    lines = plan_lines(channels, selection)
    typical, worst = cat.estimate_seconds(selection)
    if request.dry_run:
        describe(
            console,
            "The report would run:" if lines else "A read-only snapshot (nothing is written).",
            lines,
            [cat.consent_safety_text(caps)] if lines else [],
        )
        return EXIT_OK
    reasons = start_refusal(daemon.status())
    if reasons:
        raise DiagError(EXIT_REFUSED, "Cannot start now:\n" + "\n".join(f"  {r}" for r in reasons))
    consent: frozenset[str] = frozenset()
    if lines:
        describe(
            console,
            f"This report changes fan speeds (about {duration_words(typical)}, "
            f"up to {duration_words(worst)}):",
            lines,
            [cat.consent_safety_text(caps)],
        )
        probes = {
            hid: next(c.name for c in channels if c.channel_id == hid)
            for hid in request.stall_probe
        }
        consent, refusal = confirm_fan_stops(console, probes, allowed=request.allow_fan_stop)
        if refusal:
            raise DiagError(EXIT_REFUSED, refusal)
        refusal = confirm_writes(console, flag_given=request.confirmed_by_flag)
        if refusal:
            raise DiagError(EXIT_REFUSED, refusal)
    else:
        console.out("A read-only snapshot: nothing is written.")
    headers_facts, cooler = read_notes(request.notes_file, daemon)
    unavailable = {
        ch.channel_id: {
            t: a.reason
            for t in cat.TEST_ORDER
            if not (a := cat.availability(ch, t, caps)).available
        }
        for ch in channels
    }
    now = d.utc_now_iso()
    doc = d.new_document(
        report_id=d.new_report_id(now),
        created_at=now,
        gui_facts=client_facts(),
        channels=[channel_dict(ch) for ch in channels],
        user_facts={
            "cooler": cooler,
            "headers": {
                cid: f
                for cid, f in headers_facts.items()
                if any(c.channel_id == cid for c in channels)
            },
        },
        plan={
            "selections": {cid: sorted(t) for cid, t in sorted(selection.items())},
            "probe_consent": sorted(consent),
            "consent_text": lines,
            "confirmed_at": now,
            "estimate_s": [typical, worst],
            "unavailable": {cid: v for cid, v in unavailable.items() if v},
        },
    )
    runner = ReportRunner(doc, build_plan(selection), probe_consent=consent)
    poll_client = OwnedClient(daemon.socket_path)
    worker = CallWorker(daemon.socket_path)

    def cancel_now(slot: str) -> None:
        refusal = daemon.best_effort(lambda c: cancel_slot(c, slot))
        if refusal:
            raise DaemonError("cancel", refusal)

    def poll() -> tuple:
        try:
            return poll_client.get().poll()
        except DaemonUnavailable:
            poll_client.drop()
            raise

    names = {c.channel_id: c.name for c in channels}
    try:
        with Interrupts() as interrupts:
            return ReportRun(
                console,
                runner,
                worker=worker,
                poll=poll,
                cancel_now=cancel_now,
                interrupts=interrupts,
                names=names,
            ).run()
    finally:
        worker.close()
        poll_client.close()


# ── Saved reports ────────────────────────────────────────────────────────────


def _resolve(ref: str, directory: Path | None = None) -> Path:
    """A saved report by id, unique id prefix, or path."""
    path = Path(ref)
    if path.suffix == ".json" and path.exists():
        return path
    entries = [e for e in store.list_reports(directory) if e.report_id.startswith(ref)]
    exact = [e for e in entries if e.report_id == ref]
    if exact:
        return exact[0].path
    if len(entries) == 1:
        return entries[0].path
    if not entries:
        raise DiagError(
            EXIT_REFUSED, f"No saved report matches {ref!r}. See ventulus-diag report list."
        )
    ids = ", ".join(e.report_id for e in entries[:8])
    raise DiagError(EXIT_REFUSED, f"{ref!r} matches several reports: {ids}")


def load(ref: str, directory: Path | None = None) -> dict:
    path = _resolve(ref, directory)
    try:
        doc, _recovered = store.load_report(path)
    except (OSError, ValueError) as e:
        raise DiagError(EXIT_FAILED, f"Could not read {path}: {e}") from e
    return doc


def list_cmd(console: Console, directory: Path | None = None) -> int:
    # Read-only: no recover_cut_off_reports here. Another process (the GUI, or
    # a second ventulus-diag) may be running the report that reads in_progress.
    entries = store.list_reports(directory)
    if not entries:
        console.out(f"No saved reports in {directory or store.reports_dir()}.")
        return EXIT_OK
    for e in entries:
        if e.error:
            console.out(f"{e.path.name}  unreadable: {e.error}")
            continue
        console.out(f"{e.report_id}  {e.started_at}  {e.state:<11}  {e.tests}  — {e.machine}")
    return EXIT_OK


def render_text(doc: Mapping) -> list[str]:
    """A saved report as plain text for a terminal, from the same view model the
    exports use. ``export --format markdown`` is the version for an issue."""
    view = build_report_view(doc)
    lines = [f"{view.title} {view.report_id} — {view.state_label}", view.when_line]
    if view.state_reason:
        lines.append(view.state_reason)
    lines += ["", *view.summary_lines]
    for heading, rows in (
        ("Needs attention", view.attention),
        ("Observations", view.observations),
        ("Not tested", view.not_tested),
        ("Restoration", view.restoration),
    ):
        if rows:
            lines += ["", f"{heading}:"]
            lines += [f"  • {r.statement} [{r.result_label}]" for r in rows]
    for section in view.channels:
        lines += ["", f"{section.name} ({section.channel_id}) — {section.subtitle}"]
        lines += [f"  {label}: {value}" for label, value in section.facts]
        for t in section.tests:
            reason = f" — {t.reason}" if t.reason else ""
            lines.append(f"  {t.title}: {t.status_label}{reason}")
        lines += [f"  • {f.statement} [{f.result_label}]" for f in section.findings]
    lines += ["", "Environment:"]
    lines += [f"  {label}: {value}" for label, value in view.environment]
    if view.trace_note:
        lines += ["", view.trace_note]
    return lines


def show_cmd(console: Console, ref: str, directory: Path | None = None) -> int:
    for line in render_text(load(ref, directory)):
        console.out(line)
    return EXIT_OK


EXPORT_FORMATS = ("markdown", "html", "json", "csv")


def export_cmd(
    console: Console, ref: str, fmt: str, output: Path, directory: Path | None = None
) -> int:
    from ventulus.paths import atomic_write
    from ventulus.services.pwm_report.export_csv import csv_file_name, csv_tables
    from ventulus.services.pwm_report.export_html import report_html
    from ventulus.services.pwm_report.export_markdown import report_markdown

    doc = load(ref, directory)
    try:
        if fmt == "csv":
            tables = csv_tables(doc)
            if not tables:
                console.out("This report has no sweep, probe or trace data to export as CSV.")
                return EXIT_OK
            output.mkdir(parents=True, exist_ok=True)
            for table, text in tables.items():
                target = output / csv_file_name(doc, table)
                atomic_write(target, text)
                console.out(f"Wrote {target}")
            return EXIT_OK
        text = {
            "markdown": report_markdown,
            "html": report_html,
            "json": lambda doc: json.dumps(doc, indent=2, allow_nan=False),
        }[fmt](doc)
        atomic_write(output, text)
    except OSError as e:
        raise DiagError(EXIT_FAILED, f"Could not write {output}: {e}") from e
    console.out(f"Wrote {output}")
    return EXIT_OK


def compare_cmd(
    console: Console,
    first: str,
    second: str,
    fmt: str,
    output: Path | None,
    directory: Path | None = None,
) -> int:
    from ventulus.paths import atomic_write
    from ventulus.services.pwm_report.compare import compare_reports
    from ventulus.services.pwm_report.export_html import comparison_html
    from ventulus.services.pwm_report.export_markdown import comparison_markdown

    cmp = compare_reports(load(first, directory), load(second, directory))
    text = comparison_html(cmp) if fmt == "html" else comparison_markdown(cmp)
    if output is None:
        console.out(text)
        return EXIT_OK
    try:
        atomic_write(output, text)
    except OSError as e:
        raise DiagError(EXIT_FAILED, f"Could not write {output}: {e}") from e
    console.out(f"Wrote {output}")
    return EXIT_OK
