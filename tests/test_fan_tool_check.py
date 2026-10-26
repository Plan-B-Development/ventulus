"""Other fan-control software on this machine (``fan_tool_check``).

The probe reads systemd and ``/run/fancontrol.pid`` and nothing else; the System
State page shows what it found on the Interference Monitor, re-read on every
show; the support bundle carries it. ``tests/conftest.py`` pins
``probe_fan_tools`` to "could not check" for every other test.
"""

from __future__ import annotations

import json
import subprocess
import threading
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QLabel, QPushButton

from ventulus.api.models import (
    ConnectionState,
    HardwareDiagnosticsResult,
    HwmonChipInfo,
    HwmonDiagnostics,
    OperationMode,
    ThermalSafetyInfo,
)
from ventulus.services import fan_tool_check
from ventulus.services.app_state import AppState
from ventulus.services.diagnostics_service import DiagnosticsService
from ventulus.services.duty_drift import NO_DRIFT
from ventulus.services.fan_tool_check import (
    KNOWN_FAN_TOOL_UNITS,
    MIGRATING_GUIDE_URL,
    FanToolState,
    FanToolUnit,
    check_fan_tools,
    fan_tools_line,
)
from ventulus.services.system_state_view import build_system_state_vm

_UNITS = [unit for unit, _ in KNOWN_FAN_TOOL_UNITS]


def _block(load: str, active: str = "inactive", file_state: str = "") -> str:
    return f"LoadState={load}\nActiveState={active}\nUnitFileState={file_state}"


def _show_output(**states: tuple[str, str, str]) -> str:
    """``systemctl show`` output for every known unit; the ones named are
    installed with (LoadState, ActiveState, UnitFileState), the rest not-found."""
    blocks = [
        _block(*states[unit.removesuffix(".service")])
        if unit.removesuffix(".service") in states
        else _block("not-found")
        for unit in _UNITS
    ]
    return "\n\n".join(blocks) + "\n"


def _runner(stdout: str = "", returncode: int = 0, calls: list | None = None):
    def run(args, **kwargs):
        if calls is not None:
            calls.append(args)
        return SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)

    return run


def _check(tmp_path, run, **kwargs) -> FanToolState:
    kwargs.setdefault("pid_file", tmp_path / "fancontrol.pid")
    kwargs.setdefault("proc_dir", tmp_path / "proc")
    return check_fan_tools(systemctl_path="/usr/bin/systemctl", run=run, **kwargs)


# ── The probe ────────────────────────────────────────────────────────────────


def test_one_systemctl_show_over_the_fixed_allow_list(tmp_path):
    calls: list = []
    _check(tmp_path, _runner(_show_output(), calls=calls))
    assert calls == [
        [
            "/usr/bin/systemctl",
            "show",
            "--property=LoadState,ActiveState,UnitFileState",
            "--",
            *_UNITS,
        ]
    ]


def test_installed_units_are_read_and_missing_ones_skipped(tmp_path):
    out = _show_output(
        coolercontrold=("loaded", "active", "enabled"),
        fan2go=("loaded", "inactive", "enabled"),
        fancontrol=("loaded", "inactive", "disabled"),
        thinkfan=("masked", "inactive", "masked"),
    )
    state = _check(tmp_path, _runner(out))
    assert state.systemd_checked
    assert [u.unit for u in state.units] == [
        "fancontrol.service",
        "coolercontrold.service",
        "fan2go.service",
        "thinkfan.service",
    ], "lactd.service is not installed"
    assert [u.name for u in state.running] == ["CoolerControl"]
    assert [u.name for u in state.starting_at_boot] == ["fan2go"]
    assert state.any_running and state.found_anything


def test_nothing_running_or_enabled_is_found_clean(tmp_path):
    state = _check(tmp_path, _runner(_show_output(fancontrol=("loaded", "inactive", "disabled"))))
    assert state.systemd_checked and state.units
    assert not state.any_running and not state.found_anything
    assert fan_tools_line(state) == (
        "No known fan-control service is running or set to start at boot."
    )


@pytest.mark.parametrize(
    "run",
    [
        _runner("", returncode=1),  # e.g. "System has not been booted with systemd"
        _runner("LoadState=loaded\n"),  # fewer blocks than units: misaligned
    ],
)
def test_an_answer_that_cannot_be_trusted_is_not_checked(tmp_path, run):
    state = _check(tmp_path, run)
    assert not state.systemd_checked and state.units == ()
    assert fan_tools_line(state) == ""


@pytest.mark.parametrize("exc", [subprocess.TimeoutExpired("systemctl", 1.5), OSError("gone")])
def test_a_failed_systemctl_is_not_checked(tmp_path, exc):
    def run(*a, **k):
        raise exc

    assert not _check(tmp_path, run).systemd_checked


def test_no_systemctl_is_not_checked(tmp_path, monkeypatch):
    monkeypatch.setattr(fan_tool_check.shutil, "which", lambda _name: None)
    called: list = []
    state = check_fan_tools(
        pid_file=tmp_path / "none", proc_dir=tmp_path, run=_runner(calls=called)
    )
    assert not state.systemd_checked and called == []


# ── fancontrol's PID file ────────────────────────────────────────────────────


def _proc(tmp_path, pid: str, comm: str) -> None:
    d = tmp_path / "proc" / pid
    d.mkdir(parents=True)
    (d / "comm").write_text(comm + "\n")


@pytest.mark.parametrize(
    ("pid_text", "comm", "expected"),
    [
        (None, None, "absent"),
        ("4242\n", "fancontrol", "running"),
        ("4242\n", "bash", "stale"),  # the PID was reused
        ("4242\n", None, "stale"),  # nothing has that PID
        ("garbage", None, "stale"),
    ],
)
def test_the_pid_file_names_a_live_fancontrol_or_is_left_over(tmp_path, pid_text, comm, expected):
    if pid_text is not None:
        (tmp_path / "fancontrol.pid").write_text(pid_text)
    if comm is not None:
        _proc(tmp_path, "4242", comm)
    state = _check(tmp_path, _runner(_show_output()))
    assert state.fancontrol_pid == expected


def test_fancontrol_by_hand_is_reported_and_its_service_is_not_counted_twice(tmp_path):
    (tmp_path / "fancontrol.pid").write_text("4242\n")
    _proc(tmp_path, "4242", "fancontrol")
    by_hand = _check(tmp_path, _runner(_show_output()))
    assert by_hand.fancontrol_by_hand and by_hand.any_running
    assert "fancontrol (started by hand)" in fan_tools_line(by_hand)

    as_service = _check(tmp_path, _runner(_show_output(fancontrol=("loaded", "active", "enabled"))))
    assert not as_service.fancontrol_by_hand, "the service wrote that PID file"
    line = fan_tools_line(as_service)
    assert "fancontrol (fancontrol.service)" in line and "started by hand" not in line


# ── The reading ──────────────────────────────────────────────────────────────


def _unit(name: str, unit: str, active: str, file_state: str) -> FanToolUnit:
    return FanToolUnit(unit=unit, name=name, active_state=active, unit_file_state=file_state)


_CC_RUNNING = _unit("CoolerControl", "coolercontrold.service", "active", "enabled")
_FAN2GO_AT_BOOT = _unit("fan2go", "fan2go.service", "inactive", "enabled")


def test_the_line_names_what_runs_what_starts_at_boot_and_what_to_do():
    line = fan_tools_line(FanToolState(True, (_CC_RUNNING, _FAN2GO_AT_BOOT)))
    assert "running: CoolerControl (coolercontrold.service)." in line
    assert "Set to start at boot: fan2go (fan2go.service)." in line
    assert "stop them, or keep them off every fan Ventulus drives" in line
    one = fan_tools_line(FanToolState(True, (_CC_RUNNING,)))
    assert "stop it, or keep it off" in one


def test_a_killed_fancontrol_is_named_even_when_systemd_cannot_be_read():
    line = fan_tools_line(FanToolState(False, fancontrol_pid="stale"))
    assert "did not exit cleanly" in line and "reboot" in line


# ── The System State view model ──────────────────────────────────────────────


def _diag() -> HardwareDiagnosticsResult:
    return HardwareDiagnosticsResult(
        hwmon=HwmonDiagnostics(
            chips_detected=[
                HwmonChipInfo(chip_name="nct6798", expected_driver="nct6775", header_count=5)
            ],
            total_headers=2,
            writable_headers=2,
        ),
        thermal_safety=ThermalSafetyInfo(state="normal", cpu_sensor_found=True),
    )


def _interference(fan_tools):
    return build_system_state_vm(_diag(), duty_drift=NO_DRIFT, fan_tools=fan_tools).interference


def test_a_running_tool_takes_the_no_interference_headline_and_offers_the_guide():
    clean = _interference(FanToolState(True))
    assert clean.title == "No Interference Detected", "precondition: the clean headline"
    assert clean.fan_tools_line and clean.fan_tools_doc_url == ""

    running = _interference(FanToolState(True, (_CC_RUNNING,)))
    assert running.title == "No BIOS/EC Reclaim Detected"
    assert running.fan_tools_line == fan_tools_line(FanToolState(True, (_CC_RUNNING,)))
    assert running.fan_tools_doc_url == MIGRATING_GUIDE_URL
    # Only a running tool changes the headline; one that starts at boot is a
    # finding with the guide, not a writer now.
    at_boot = _interference(FanToolState(True, (_FAN2GO_AT_BOOT,)))
    assert at_boot.title == "No Interference Detected"
    assert at_boot.fan_tools_doc_url == MIGRATING_GUIDE_URL


def test_nothing_read_yet_leaves_the_card_as_it_was():
    vm = _interference(None)
    assert vm.title == "No Interference Detected"
    assert vm.fan_tools_line == "" and vm.fan_tools_doc_url == ""


# ── The page: read off the GUI thread, on every show ─────────────────────────


class _SocketOnly:
    socket_path = "/nonexistent/ventulus.sock"


def _page(qtbot):
    from ventulus.ui.pages.system_state_page import SystemStatePage

    state = AppState()
    state.set_connection(ConnectionState.CONNECTED)
    state.set_mode(OperationMode.AUTOMATIC)
    diag = DiagnosticsService(state)
    diag.set_hw_diagnostics(_diag())  # rendered from cache: no daemon fetch
    page = SystemStatePage(state=state, diagnostics_service=diag, client=_SocketOnly())
    qtbot.addWidget(page)
    return page


def test_showing_the_page_reads_the_tools_off_the_gui_thread_and_again_on_return(
    qtbot, monkeypatch
):
    answers = [FanToolState(True, (_CC_RUNNING,)), FanToolState(True)]
    threads: list[threading.Thread] = []

    def probe():
        threads.append(threading.current_thread())
        return answers[len(threads) - 1]

    monkeypatch.setattr(fan_tool_check, "probe_fan_tools", probe)
    page = _page(qtbot)
    label = page.findChild(QLabel, "SystemState_Label_fanTools")
    button = page.findChild(QPushButton, "SystemState_Btn_fanToolsDoc")
    title = page.findChild(QLabel, "SystemState_Label_contentionTitle")
    try:
        assert not label.isVisibleTo(page), "precondition: nothing read yet"
        page.show()
        qtbot.waitUntil(lambda: page._fan_tools is answers[0])
        assert threads[0] is not threading.main_thread()
        assert label.isVisibleTo(page)
        assert "CoolerControl (coolercontrold.service)" in label.text()
        assert button.isVisibleTo(page)
        assert title.text() == "No BIOS/EC Reclaim Detected"

        # The user stops it and comes back to the page.
        page.hide()
        page.show()
        qtbot.waitUntil(lambda: page._fan_tools is answers[1])
        assert label.text() == fan_tools_line(answers[1])
        assert not button.isVisibleTo(page)
        assert title.text() == "No Interference Detected"
    finally:
        page.cleanup()


# ── The support bundle ───────────────────────────────────────────────────────


def test_the_bundle_carries_unit_states_and_the_pid_file(tmp_path, monkeypatch):
    found = FanToolState(True, (_CC_RUNNING,), fancontrol_pid="stale")
    monkeypatch.setattr(fan_tool_check, "probe_fan_tools", lambda: found)
    monkeypatch.setattr(DiagnosticsService, "collect_kernel_modules", staticmethod(lambda: ""))
    monkeypatch.setattr(DiagnosticsService, "fetch_kernel_log_amdgpu", staticmethod(lambda: ""))
    svc = DiagnosticsService(state=AppState())
    monkeypatch.setattr(svc, "fetch_journal_entries", lambda: "")
    out = tmp_path / "support.json"
    svc.export_support_bundle(out)
    section = json.loads(out.read_text())["system"]["fan_control_software"]
    assert section == {
        "systemd_checked": True,
        "units": [
            {
                "unit": "coolercontrold.service",
                "active_state": "active",
                "unit_file_state": "enabled",
            }
        ],
        "fancontrol_pid_file": "stale",
    }
