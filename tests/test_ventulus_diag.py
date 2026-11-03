"""``ventulus-diag`` (DEC-503): the diagnostic CLI.

What these pin, in order of consequence:

* nothing that drives fans starts without confirmation, and a refused start
  sends no write — the fake clients here have no write methods unless a test
  gives them one, so a stray call fails the test;
* a stall probe is acknowledged per header, and only an acknowledged header
  carries ``acknowledge_below_floor``;
* the run loop turns the first interrupt into the daemon's cancel, the second
  into an immediate stop that still cancels the running slot, a lost daemon
  into ``interrupted`` and thermal protection into ``aborted`` — and saves the
  report in every case;
* the GUI's settings file is read and never written or moved;
* the CLI's call worker runs the shared executor (one code path with the GUI).
"""

from __future__ import annotations

import io
import json
import os
import signal
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.pwm_report_fixtures import (
    CPU,
    SYS,
    bundle,
    channel,
    fan,
    header,
    new_doc,
    ok,
    sweep_run,
    verify_body,
)
from ventulus.api.errors import DaemonError, DaemonTimeout, DaemonUnavailable
from ventulus.api.models import (
    parse_capabilities,
    parse_characterization_run,
    parse_cooling_devices,
    parse_fans,
    parse_hwmon_headers,
    parse_preflight_report,
    parse_status,
    parse_validation_session,
)
from ventulus.diag import cli, report, sweeps, validation
from ventulus.diag.confirm import ALLOW_STOP_FLAG, CONFIRM_FLAG, confirm_fan_stops, confirm_writes
from ventulus.diag.console import (
    EXIT_ABORTED,
    EXIT_CANCELLED,
    EXIT_INCOMPATIBLE,
    EXIT_INTERRUPTED,
    EXIT_OK,
    EXIT_REFUSED,
    EXIT_STOPPED,
    EXIT_UNAVAILABLE,
    Console,
    DiagError,
    Interrupts,
)
from ventulus.diag.daemon import Daemon, GuiSettings, connect, read_gui_settings
from ventulus.services.pwm_report import document as d
from ventulus.services.pwm_report.catalog import TEST_PROBE, TEST_SWEEP, TEST_VERIFY
from ventulus.services.pwm_report.runner import ReportRunner, build_plan

READY = {"verdict": "ready", "checks": [], "blocking": []}
CAPS = {
    "daemon_version": "5.4.0",
    "api_version": 1,
    "control": {
        "autonomous_control": True,
        "stall_probe": True,
        "pwm_characterization": True,
        "pwm_behaviour_characterization": True,
        "control_path_discovery": True,
        "diagnostic_preflight": True,
        "validation_sessions": True,
        "validation_auto_stop": True,
    },
}


def console(answers: list[str] | None = None, *, interactive: bool = False):
    out, err = io.StringIO(), io.StringIO()
    stdin = io.StringIO("".join(f"{a}\n" for a in answers or []))
    return Console(stdin, out, err, interactive=interactive), out, err


# ── Confirmation ─────────────────────────────────────────────────────────────


def test_writes_need_a_typed_yes_or_the_flag_and_nothing_else_passes():
    c, _, _ = console()
    refusal = confirm_writes(c, flag_given=False)
    assert refusal and CONFIRM_FLAG in refusal, "off a terminal the flag is the only way"
    assert confirm_writes(c, flag_given=True) == ""
    c, _, _ = console(["yes"], interactive=True)
    assert confirm_writes(c, flag_given=False) == ""
    for answer in (["y"], ["no"], []):  # anything else, and end of input, refuse
        c, _, _ = console(answer, interactive=True)
        assert confirm_writes(c, flag_given=False) != ""


def test_each_fan_stop_is_acknowledged_per_header():
    targets = {CPU: "CPU_FAN", SYS: "SYS_FAN1"}
    c, _, _ = console()
    acks, refusal = confirm_fan_stops(c, targets, allowed=[CPU])
    assert acks == frozenset() and ALLOW_STOP_FLAG in refusal and SYS in refusal
    acks, refusal = confirm_fan_stops(c, targets, allowed=[CPU, SYS])
    assert refusal == "" and acks == {CPU, SYS}
    c, _, _ = console(["stop"], interactive=True)
    acks, refusal = confirm_fan_stops(c, targets, allowed=[CPU])
    assert refusal == "" and acks == {CPU, SYS}
    c, _, _ = console(["yes"], interactive=True)  # "yes" is not "stop"
    acks, refusal = confirm_fan_stops(c, {SYS: "SYS_FAN1"}, allowed=[])
    assert acks == frozenset() and refusal


# ── A fake daemon (reads only, unless a test adds a write) ───────────────────


class ReadOnlyClient:
    """Answers the reads a plan needs. Has no method that writes."""

    def __init__(self, *, thermal: str = "normal", verify_active: bool = False) -> None:
        self.calls: list[str] = []
        self._status = parse_status({"thermal_state": thermal, "verify_active": verify_active})
        self._headers = parse_hwmon_headers({"headers": [header(CPU), header(SYS)]})
        self._fans = parse_fans({"fans": [fan(CPU), fan(SYS)]})

    def __getattr__(self, name):  # any unknown method is a write we did not expect
        raise AssertionError(f"unexpected daemon call: {name}")

    def status(self):
        self.calls.append("status")
        return self._status

    def fans(self):
        self.calls.append("fans")
        return self._fans

    def hwmon_headers(self):
        return self._headers

    def active_profile(self):
        return None

    def close(self):
        pass


def make_daemon(client, *, caps: dict | None = None) -> Daemon:
    daemon = Daemon(
        client=client,
        socket_path="/nonexistent/test.sock",
        capabilities=parse_capabilities(caps or CAPS),
        settings=GuiSettings(),
        # The short-timeout client used on the way out is the same fake, so a
        # cancel sent while leaving is counted like any other.
        stop_client_factory=lambda _path: client,
    )
    daemon.headers = parse_hwmon_headers({"headers": [header(CPU), header(SYS)]})
    return daemon


def test_an_unconfirmed_report_off_a_terminal_starts_nothing():
    client = ReadOnlyClient()
    c, out, _ = console()
    with pytest.raises(DiagError) as exc:
        report.run_report(c, make_daemon(client), report.RunRequest())
    assert exc.value.code == EXIT_REFUSED and CONFIRM_FLAG in exc.value.message
    assert "This report changes fan speeds" in out.getvalue(), "the plan is shown first"


def test_a_stall_probe_without_its_acknowledgement_refuses_the_whole_run():
    client = ReadOnlyClient()
    c, _, _ = console()
    request = report.RunRequest(stall_probe=(CPU,), confirmed_by_flag=True)
    with pytest.raises(DiagError) as exc:
        report.run_report(c, make_daemon(client), request)
    assert exc.value.code == EXIT_REFUSED and ALLOW_STOP_FLAG in exc.value.message


@pytest.mark.parametrize(
    ("kwargs", "needle"),
    [({"thermal": "emergency"}, "thermal protection"), ({"verify_active": True}, "Another")],
)
def test_a_confirmed_report_is_refused_while_the_daemon_is_not_ready(kwargs, needle):
    client = ReadOnlyClient(**kwargs)
    c, _, _ = console()
    with pytest.raises(DiagError) as exc:
        report.run_report(c, make_daemon(client), report.RunRequest(confirmed_by_flag=True))
    assert exc.value.code == EXIT_REFUSED and needle in exc.value.message


def test_selection_defaults_to_the_guis_and_honours_header_and_test_choices():
    caps = parse_capabilities(CAPS)
    from ventulus.services.pwm_report import catalog as cat

    channels = cat.build_channels(
        parse_hwmon_headers({"headers": [header(CPU), header(SYS)]}),
        parse_fans({"fans": [fan(CPU), fan(SYS, rpm=0)]}),
        caps,
        name_of=lambda cid: cid,
    )
    selection, _ = report.select(channels, caps, report.RunRequest())
    assert set(selection) == {CPU}, "the default skips a header with no fan turning"
    selection, _ = report.select(
        channels, caps, report.RunRequest(headers=(SYS,), tests=("verify",))
    )
    assert selection == {SYS: frozenset({TEST_VERIFY})}
    assert report.select(channels, caps, report.RunRequest(snapshot_only=True))[0] == {}
    with pytest.raises(DiagError):
        report.select(channels, caps, report.RunRequest(headers=("hwmon:nope",)))


def test_a_stall_probe_on_a_header_it_is_not_offered_on_is_refused():
    caps = parse_capabilities(CAPS)
    from ventulus.services.pwm_report import catalog as cat

    channels = cat.build_channels(
        parse_hwmon_headers({"headers": [header(CPU, role="cpu_fan")]}),
        parse_fans({"fans": [fan(CPU)]}),
        caps,
        name_of=lambda cid: cid,
    )
    with pytest.raises(DiagError) as exc:
        report.select(channels, caps, report.RunRequest(stall_probe=(CPU,)))
    assert "CPU fan" in exc.value.message


# ── The run loop ─────────────────────────────────────────────────────────────


class Clock:
    def __init__(self) -> None:
        self.t = 0.0
        self.hooks: list = []
        self._steps = 0

    def now(self) -> float:
        return self.t

    def sleep(self, dt: float) -> None:
        self.t += dt
        self._steps += 1
        assert self._steps < 20_000, "the run loop did not end"
        for hook in self.hooks:
            hook()


class FakeWorker:
    """Answers each call at once from *answer*; ``None`` leaves it pending."""

    def __init__(self, answer) -> None:
        self.answer = answer
        self.sent: list = []
        self._ready: list = []

    def submit(self, calls) -> None:
        for call in calls:
            self.sent.append(call)
            out = self.answer(call)
            if out is not None:
                self._ready.append((call.req_id, out))

    def drain(self):
        ready, self._ready = self._ready, []
        return ready

    def kinds(self) -> list[str]:
        return [c.kind for c in self.sent]


def _status(thermal: str = "normal"):
    return SimpleNamespace(thermal_state=thermal)


def _answers(sweep_states: list[str]):
    """verify then a sweep whose polls walk through *sweep_states*; the last repeats."""
    states = list(sweep_states)

    def answer(call):
        if call.kind == "snapshot":
            return ok(bundle(fans=[fan(CPU)], headers=[header(CPU)]))
        if call.kind == "preflight":
            return ok(READY)
        if call.kind == "verify":
            return ok(verify_body())
        if call.kind == "start_sweep":
            return ok(sweep_run("running"))
        if call.kind == "poll":
            state = states.pop(0) if len(states) > 1 else states[0]
            return ok(sweep_run(state))
        if call.kind == "cancel":
            states[:] = ["cancelled"]
            return ok(sweep_run("running"))
        raise AssertionError(call.kind)

    return answer


def _run(tmp_path, answer, *, poll=None, hooks=(), selection=None):
    selection = selection or {CPU: {TEST_VERIFY, TEST_SWEEP}}
    runner = ReportRunner(new_doc([channel(CPU)]), build_plan(selection))
    clock = Clock()
    worker = FakeWorker(answer)
    interrupts = Interrupts()
    cancelled_now: list[str] = []
    c, out, _err = console()
    run = report.ReportRun(
        c,
        runner,
        worker=worker,
        poll=poll or (lambda: (_status(), [], [SimpleNamespace(id=CPU, rpm=900)])),
        cancel_now=cancelled_now.append,
        interrupts=interrupts,
        directory=tmp_path,
        clock=clock.now,
        sleep=clock.sleep,
    )
    for hook in hooks:
        clock.hooks.append(lambda hook=hook: hook(runner, interrupts))
    rc = run.run()
    return rc, runner, worker, run, cancelled_now, out.getvalue()


def _saved(run) -> dict:
    assert run.path is not None and run.path.exists()
    return json.loads(run.path.read_text())


def test_a_run_to_the_end_saves_a_complete_report_with_a_trace(tmp_path):
    rc, _runner, worker, run, _, out = _run(tmp_path, _answers(["running", "complete"]))
    assert rc == EXIT_OK
    doc = _saved(run)
    assert doc["state"] == d.STATE_COMPLETE
    assert [s["status"] for s in doc["steps"]] == [d.STEP_COMPLETE, d.STEP_COMPLETE]
    assert doc["trace"]["samples"] > 0, "the 1 Hz poll feeds the trace"
    assert "cancel" not in worker.kinds()
    assert "Saved:" in out


def _when_sweeping(count: int):
    def hook(runner, interrupts):
        if runner.active_slot == "characterization" and runner.step_phase == "running":
            interrupts.count = max(interrupts.count, count)

    return hook


def test_the_first_interrupt_sends_the_daemons_cancel_once_and_waits_for_it(tmp_path):
    rc, _runner, worker, run, cancelled_now, _ = _run(
        tmp_path, _answers(["running"]), hooks=[_when_sweeping(1)]
    )
    assert worker.kinds().count("cancel") == 1
    assert cancelled_now == [], "a cancel is not the stop-at-once path"
    assert rc == EXIT_CANCELLED and _saved(run)["state"] == d.STATE_CANCELLED
    assert worker.kinds()[-1] == "snapshot", "the final state is still read after a cancel"


def test_a_second_interrupt_stops_at_once_and_still_cancels_the_running_slot(tmp_path):
    rc, _runner, _worker, run, cancelled_now, out = _run(
        tmp_path, _answers(["running"]), hooks=[_when_sweeping(2)]
    )
    assert rc == EXIT_STOPPED
    assert cancelled_now == ["characterization"]
    doc = _saved(run)
    assert doc["state"] == d.STATE_INTERRUPTED and doc["snapshots"]["final"] is None
    assert "puts its header back" in out


def test_a_daemon_that_stops_answering_ends_the_run_interrupted(tmp_path):
    def poll():
        raise DaemonUnavailable("gone")

    rc, _runner, _, run, _, _ = _run(tmp_path, _answers(["running"]), poll=poll)
    assert rc == EXIT_INTERRUPTED and _saved(run)["state"] == d.STATE_INTERRUPTED


def test_thermal_protection_during_a_run_aborts_it(tmp_path):
    hot = {"on": False}

    def poll():
        return (_status("emergency" if hot["on"] else "normal"), [], [])

    def heat(runner, _interrupts):
        if runner.active_slot == "characterization" and runner.step_phase == "running":
            hot["on"] = True

    rc, _, worker, run, _, _ = _run(tmp_path, _answers(["running"]), poll=poll, hooks=[heat])
    assert "cancel" in worker.kinds()
    assert rc == EXIT_ABORTED and _saved(run)["state"] == d.STATE_ABORTED


def test_a_probe_is_sent_with_the_acknowledgement_only_for_an_acknowledged_header(tmp_path):
    """The CLI hands its acknowledgements to the runner; this pins the hand-off."""
    runner = ReportRunner(
        new_doc([channel(CPU), channel(SYS)]),
        build_plan({CPU: {TEST_PROBE}, SYS: {TEST_PROBE}}),
        probe_consent=frozenset({SYS}),
    )
    sent = []

    def answer(call):
        sent.append(call)
        if call.kind == "snapshot":
            return ok(bundle(fans=[fan(CPU), fan(SYS)], headers=[header(CPU), header(SYS)]))
        if call.kind == "preflight":
            return ok(READY)
        if call.kind == "start_probe":
            return ok({"run_id": "p", "state": "running"})
        if call.kind == "poll":
            return ok({"run_id": "p", "state": "complete", "restore_outcome": "restored"})
        raise AssertionError(call.kind)

    clock = Clock()
    c, _, _ = console()
    report.ReportRun(
        c,
        runner,
        worker=FakeWorker(answer),
        poll=lambda: (_status(), [], []),
        cancel_now=lambda _s: None,
        interrupts=Interrupts(),
        directory=tmp_path,
        clock=clock.now,
        sleep=clock.sleep,
    ).run()
    probes = [c for c in sent if c.kind == "start_probe"]
    assert [(p.header_id, p.args.get("acknowledge_below_floor")) for p in probes] == [
        (SYS, True)
    ], "an unacknowledged header is never started"


# ── The worker runs the shared executor ──────────────────────────────────────


def test_the_call_worker_answers_every_call_even_with_no_daemon(tmp_path):
    from ventulus.services.pwm_report.runner import Call

    worker = report.CallWorker(str(tmp_path / "no.sock"))
    try:
        worker.submit([Call(req_id=7, kind="verify", header_id=CPU)])
        deadline = time.monotonic() + 5
        got: list = []
        while not got and time.monotonic() < deadline:
            got = worker.drain()
            time.sleep(0.01)
    finally:
        worker.close()
    assert got, "the runner waits on every call: the worker must answer"
    [(req_id, outcome)] = got
    assert req_id == 7 and outcome.ok is False and outcome.category == "unavailable"


# ── Single-header tests ──────────────────────────────────────────────────────


class SweepClient(ReadOnlyClient):
    def __init__(self, states: list[str], *, blocked: bool = False) -> None:
        super().__init__()
        self.states = states
        self.blocked = blocked
        self.started = 0
        self.cancels = 0

    def diagnostic_preflight(self, header_id, diagnostic):
        verdict = "blocked" if self.blocked else "ready"
        return parse_preflight_report(
            {
                "header_id": header_id,
                "diagnostic": diagnostic,
                "verdict": verdict,
                "checks": [],
                "blocking": [],
            }
        )

    def start_characterization(self, header_id, **_kw):
        self.started += 1
        return parse_characterization_run(sweep_run("running"))

    def characterization_status(self):
        state = self.states.pop(0) if len(self.states) > 1 else self.states[0]
        return parse_characterization_run(sweep_run(state))

    def cancel_characterization(self):
        self.cancels += 1
        self.states[:] = ["cancelled"]
        return parse_characterization_run(sweep_run("running"))


def _sweep(client, *, confirmed=True, interrupts=None, hook=None):
    clock = Clock()
    if hook is not None:
        clock.hooks.append(hook)
    c, out, _ = console()
    rc = sweeps.run_sweep(
        c,
        make_daemon(client),
        CPU,
        sweeps.CHARACTERISE,
        confirmed_by_flag=confirmed,
        interrupts=interrupts,
        clock=clock.now,
        sleep=clock.sleep,
    )
    return rc, out.getvalue()


def test_a_characterisation_runs_to_its_result():
    client = SweepClient(["running", "running", "complete"])
    rc, out = _sweep(client)
    assert rc == EXIT_OK and client.started == 1 and client.cancels == 0
    assert "Curve control for every fan is paused" in out


def test_an_unconfirmed_or_preflight_blocked_characterisation_never_starts():
    client = SweepClient(["complete"])
    with pytest.raises(DiagError) as exc:
        _sweep(client, confirmed=False)
    assert exc.value.code == EXIT_REFUSED and client.started == 0
    client = SweepClient(["complete"], blocked=True)
    with pytest.raises(DiagError) as exc:
        _sweep(client)
    assert "preflight blocked" in exc.value.message and client.started == 0


def test_an_interrupted_characterisation_is_cancelled_then_followed_to_its_end():
    client = SweepClient(["running"])
    interrupts = Interrupts()

    def press():
        if client.started and interrupts.count == 0:
            interrupts.count = 1

    rc, _ = _sweep(client, interrupts=interrupts, hook=press)
    assert client.cancels == 1 and rc == EXIT_CANCELLED


def test_a_second_interrupt_leaves_a_characterisation_to_the_daemon():
    client = SweepClient(["running"])
    interrupts = Interrupts()

    def press():
        if client.started:
            interrupts.count = 2

    rc, out = _sweep(client, interrupts=interrupts, hook=press)
    assert rc == EXIT_STOPPED and "puts the header back" in out
    assert client.cancels == 1, "two signals at once still send the daemon's cancel"


# ── Validation sessions ──────────────────────────────────────────────────────

DEVICE = {
    "cooling_devices": [
        {
            "id": "aio",
            "name": "NL-LC1",
            "kind": "aio",
            "pump_member": SYS,
            "radiator_members": [CPU],
        }
    ]
}


class SessionClient(ReadOnlyClient):
    def __init__(self) -> None:
        super().__init__()
        self.start_kwargs: dict | None = None
        self.state = "recording"
        self.cancelled = 0
        self.sweep_cancelled = 0

    def get_cooling_devices(self):
        return parse_cooling_devices(DEVICE)

    def start_validation_session(self, device_id, **kwargs):
        self.start_kwargs = {"device_id": device_id, **kwargs}
        return self._session()

    def _session(self):
        return parse_validation_session(
            {"session_id": "s1", "state": self.state, "metadata": {"cooling_device_id": "aio"}}
        )

    def validation_session(self):
        return self._session()

    def cancel_validation_session(self):
        self.cancelled += 1
        self.state = "cancelled"
        return self._session()

    def characterization_status(self):
        return parse_characterization_run(sweep_run("running"))

    def cancel_characterization(self):
        self.sweep_cancelled += 1

    def control_path_status(self):
        return None


def test_a_passive_session_needs_no_confirmation_and_an_active_one_does():
    client = SessionClient()
    c, _, _ = console()
    rc = validation.start_cmd(
        c, make_daemon(client), validation.StartRequest(device_id="aio", detach=True)
    )
    assert rc == EXIT_OK and client.start_kwargs["diagnostics"] is None
    client = SessionClient()
    with pytest.raises(DiagError) as exc:
        validation.start_cmd(
            c,
            make_daemon(client),
            validation.StartRequest(
                device_id="aio", diagnostics=("characterization",), detach=True
            ),
        )
    assert exc.value.code == EXIT_REFUSED and client.start_kwargs is None


def test_interrupting_an_active_session_cancels_it_and_its_running_sweep():
    client = SessionClient()
    interrupts = Interrupts()
    clock = Clock()
    clock.hooks.append(lambda: setattr(interrupts, "count", max(interrupts.count, 1)))
    c, _, _ = console()
    rc = validation.follow(
        c,
        make_daemon(client),
        "s1",
        active=True,
        signals=interrupts,
        clock=clock.now,
        sleep=clock.sleep,
    )
    assert client.cancelled == 1 and client.sweep_cancelled == 1
    assert rc == EXIT_CANCELLED


# ── Connecting, settings, signals, the command line ──────────────────────────


def test_an_unreachable_daemon_is_exit_3_with_no_permission_advice():
    def factory(_path):
        raise DiagError(EXIT_UNAVAILABLE, "unreachable")

    def unreachable(path):
        client = SimpleNamespace(
            capabilities=lambda: (_ for _ in ()).throw(DaemonUnavailable("refused")),
            close=lambda: None,
        )
        return connect(path, client_factory=lambda _p: client, settings=GuiSettings())

    c, _, err = console()
    rc = cli.main(["status"], console=c, daemon_factory=unreachable)
    assert rc == EXIT_UNAVAILABLE
    message = err.getvalue()
    assert "systemctl status ventulusd" in message
    for unsafe in ("sudo", "chmod", "usermod", "group"):
        assert unsafe not in message


def test_a_daemon_without_daemon_side_control_is_refused():
    client = SimpleNamespace(
        capabilities=lambda: parse_capabilities({"daemon_version": "1.9.0", "control": {}}),
        close=lambda: None,
    )
    with pytest.raises(DiagError) as exc:
        connect("/x", client_factory=lambda _p: client, settings=GuiSettings())
    assert exc.value.code == EXIT_INCOMPATIBLE


def test_the_guis_settings_are_read_and_never_written_or_moved(tmp_path):
    good = tmp_path / "app_settings.json"
    good.write_text(
        json.dumps(
            {
                "fan_aliases": {CPU: "Front intake", SYS: "  "},
                "hardware_notes": {CPU: {"connected": "fan", "notes": "hub"}},
                "cooler_notes": {"model": "NL-LC1"},
            }
        )
    )
    before = good.stat().st_mtime_ns
    settings = read_gui_settings(lambda: good)
    assert settings.fan_aliases == {CPU: "Front intake"}, "a blank alias is no alias"
    assert settings.cooler_notes == {"model": "NL-LC1", "pump_switch": ""}
    assert good.stat().st_mtime_ns == before
    bad = tmp_path / "broken.json"
    bad.write_text("{not json")
    assert read_gui_settings(lambda: bad) == GuiSettings()
    assert bad.read_text() == "{not json"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["app_settings.json", "broken.json"], (
        "an unreadable file is not quarantined: that is the GUI's call"
    )


def test_a_real_signal_is_counted_and_the_previous_handler_restored():
    previous = signal.getsignal(signal.SIGTERM)
    with Interrupts() as interrupts:
        os.kill(os.getpid(), signal.SIGTERM)
        deadline = time.monotonic() + 2
        while interrupts.count == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert interrupts.count == 1 and interrupts.name() == "SIGTERM"
    assert signal.getsignal(signal.SIGTERM) is previous


def test_saved_reports_list_show_and_export_without_a_daemon(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    from tests.pwm_report_fixtures import complete_doc
    from ventulus.services.pwm_report import store

    doc = complete_doc()
    store.save_report(doc)

    def no_daemon(_path):
        raise AssertionError("an offline command connected to the daemon")

    c, out, _ = console()
    assert cli.main(["report", "list"], console=c, daemon_factory=no_daemon) == EXIT_OK
    assert doc["report_id"] in out.getvalue()
    c, out, _ = console()
    prefix = doc["report_id"][:12]
    assert cli.main(["report", "show", prefix], console=c, daemon_factory=no_daemon) == EXIT_OK
    assert doc["report_id"] in out.getvalue()
    target = tmp_path / "r.html"
    rc = cli.main(
        ["report", "export", prefix, "--format", "html", "-o", str(target)],
        console=c,
        daemon_factory=no_daemon,
    )
    assert rc == EXIT_OK and target.read_text().startswith("<!DOCTYPE html>")


def test_a_cli_run_report_names_its_client_not_the_gui():
    from ventulus.services.pwm_report.view import build_report_view

    doc = new_doc([channel(CPU)])
    doc["environment"] = {"gui": report.client_facts()}
    rows = dict(build_report_view(doc).environment)
    assert "Ventulus (ventulus-diag)" in rows and "Ventulus GUI" not in rows
    assert "Qt" not in rows
    gui = new_doc([channel(CPU)])
    gui["environment"] = {"gui": {"gui_version": "5.5.0", "qt": "6.11"}}
    assert "Ventulus GUI" in dict(build_report_view(gui).environment), (
        "an old report reads as before"
    )


def test_the_package_imports_without_qt():
    import subprocess
    import sys

    code = (
        "import sys; import ventulus.diag.cli; "
        "bad = [m for m in sys.modules if m.startswith(('PySide6', 'pyqtgraph', 'numpy'))]; "
        "print(bad); sys.exit(1 if bad else 0)"
    )
    src = str(Path(__file__).resolve().parents[1] / "src")
    env = {**os.environ, "PYTHONPATH": src}
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_a_daemon_error_from_a_write_is_a_refusal_not_a_crash():
    class Refusing(SweepClient):
        def start_characterization(self, header_id, **_kw):
            raise DaemonError("validation_error", "busy", status=409)

    with pytest.raises(DiagError) as exc:
        _sweep(Refusing(["complete"]))
    assert exc.value.code == EXIT_REFUSED and "busy" in exc.value.message


def test_a_daemon_without_a_preflight_route_still_runs_the_test():
    """Probed, not gated (`P8-as`): a 404 says "no preflight", and the start's
    own guards still run."""

    class NoPreflight(SweepClient):
        def diagnostic_preflight(self, header_id, diagnostic):
            raise DaemonError("not_found", "no route", status=404)

    client = NoPreflight(["complete"])
    rc, out = _sweep(client)
    assert rc == EXIT_OK and client.started == 1
    assert "no safety preflight" in out


def test_a_ctrl_c_while_the_start_is_in_flight_becomes_the_daemons_cancel():
    """A real SIGINT delivered while the start request is out. Counted from
    before it, so the run the daemon did start is cancelled — not a
    KeyboardInterrupt that exits saying nothing ran while the test goes on."""

    class PressedDuringStart(SweepClient):
        def start_characterization(self, header_id, **kw):
            os.kill(os.getpid(), signal.SIGINT)
            return super().start_characterization(header_id, **kw)

    client = PressedDuringStart(["running"])
    rc, _ = _sweep(client)  # run_sweep installs its own handlers
    assert client.started == 1 and client.cancels == 1 and rc == EXIT_CANCELLED


def test_following_a_session_the_daemon_stops_reporting_ends_bounded():
    class Vanished(SessionClient):
        def validation_session(self):
            return None

    clock = Clock()
    c, _, _ = console()
    rc = validation.follow(
        c,
        make_daemon(Vanished()),
        "s1",
        active=False,
        signals=Interrupts(),
        clock=clock.now,
        sleep=clock.sleep,
    )
    assert rc == EXIT_INTERRUPTED


def test_an_explicit_request_nothing_can_satisfy_is_refused_not_a_snapshot():
    from ventulus.services.pwm_report import catalog as cat

    caps = parse_capabilities(CAPS)
    channels = cat.build_channels(
        parse_hwmon_headers({"headers": [header(CPU, writable=False)]}),
        parse_fans({"fans": [fan(CPU)]}),
        caps,
        name_of=lambda cid: cid,
    )
    with pytest.raises(DiagError) as exc:
        report.select(channels, caps, report.RunRequest(headers=(CPU,), tests=("sweep",)))
    assert exc.value.code == EXIT_REFUSED and "--snapshot-only" in exc.value.message


def test_two_signals_before_a_session_loop_runs_still_end_the_session():
    client = SessionClient()
    interrupts = Interrupts()
    interrupts.count = 2  # both arrived while the start request was out
    clock = Clock()
    c, _, _ = console()
    rc = validation.follow(
        c,
        make_daemon(client),
        "s1",
        active=True,
        signals=interrupts,
        clock=clock.now,
        sleep=clock.sleep,
    )
    assert rc == EXIT_STOPPED
    assert client.cancelled == 1 and client.sweep_cancelled == 1


def test_a_start_that_times_out_is_cancelled_in_case_it_started():
    class TimesOut(SweepClient):
        def start_characterization(self, header_id, **_kw):
            self.started += 1
            raise DaemonTimeout("no answer")

    client = TimesOut(["running"])
    with pytest.raises(DiagError) as exc:
        _sweep(client)
    assert exc.value.code == EXIT_INTERRUPTED and client.cancels == 1
    assert "a cancel was sent" in exc.value.message


def test_a_start_the_daemon_refused_outright_sends_no_cancel():
    class Unreachable(SweepClient):
        def start_characterization(self, header_id, **_kw):
            raise DaemonUnavailable("connection refused")

    client = Unreachable(["running"])
    with pytest.raises(DiagError):
        _sweep(client)
    assert client.cancels == 0, "never cancel a run that may be another client's"


def test_cancel_ends_whatever_single_header_test_is_running():
    class Busy(SweepClient):
        def control_path_status(self):
            return None

        def stall_probe_status(self):
            return None

    client = Busy(["running"])
    c, out, _ = console()
    assert cli.cancel_cmd(c, make_daemon(client)) == EXIT_OK
    assert client.cancels == 1 and "characterisation" in out.getvalue()
    client.states[:] = ["complete"]
    c, out, _ = console()
    assert cli.cancel_cmd(c, make_daemon(client)) == EXIT_OK
    assert client.cancels == 1 and "Nothing to cancel" in out.getvalue()


def test_a_hostile_notes_file_is_a_clean_refusal(tmp_path):
    deep = tmp_path / "deep.json"
    deep.write_text("[" * 200_000)
    with pytest.raises(DiagError) as exc:
        report.read_notes(deep, make_daemon(ReadOnlyClient()))
    assert exc.value.code == EXIT_REFUSED


def test_listing_reports_leaves_a_running_report_alone(tmp_path, monkeypatch):
    """Another process may be running it: list is read-only."""
    from tests.pwm_report_fixtures import complete_doc
    from ventulus.services.pwm_report import store

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    doc = complete_doc()
    doc["state"] = d.STATE_IN_PROGRESS
    path = store.save_report(doc)
    before = path.read_bytes()
    c, out, _ = console()
    assert report.list_cmd(c) == EXIT_OK
    assert path.read_bytes() == before
    assert "in_progress" in out.getvalue() or "in progress" in out.getvalue()
