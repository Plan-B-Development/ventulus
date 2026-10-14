"""GUI audit 2026-10-14, batch C: run gating.

Every diagnostic entry point takes the gate its sibling entry points take, and a
diagnostic window shows the daemon-side run it is about:

- #6/#7: System State's Health-card "Test fan control" runs the same sweep as
  "Verify All Writable", so it stands down while a PWM Test Report runs or a
  verify is in flight, and it reports progress and results on the card itself.
- The GPU restore button stays disabled until its restore is answered.
- #17: the characterisation, control-path and OpenFan calibration windows read
  the daemon's run once when they open: they adopt their own running run, show
  their own finished one, and wait (saying why) while another header's run holds
  the slot. Characterise and Discover ask before closing mid-run, as calibration
  does, and a failed stop-on-close is reported by the page.
- The cooling-device card's two diagnostics take their other entry points'
  gates.

Standing rules: `.click()` where a button exists, `isVisibleTo`, relationships
over literals, presence before absence.
"""

from __future__ import annotations

import threading

import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton, QWidget

from ventulus.api.errors import DaemonError
from ventulus.api.models import (
    Capabilities,
    CharacterizationRun,
    ConnectionState,
    ControlCapability,
    ControlPathRun,
    ControlPathStatus,
    CoolingDevice,
    CoolingDeviceInventory,
    FanReading,
    GpuDiagnosticsInfo,
    GpuFanResetResult,
    HardwareDiagnosticsResult,
    HwmonHeader,
    HwmonVerifyResult,
    OpenFanCalibrationRun,
    OperationMode,
    parse_preflight_report,
)
from ventulus.services.app_state import AppState
from ventulus.services.daemon_features import unsupported_feature_message
from ventulus.services.diagnostics_service import DiagnosticsService
from ventulus.services.header_inspector_view import build_header_inspector_view
from ventulus.services.openfan_calibration_view import build_channel_options
from ventulus.services.pwm_report.runner import RUN_ACTIVE_REASON
from ventulus.services.run_reply_ledger import ReplyRoute, RunReplyLedger
from ventulus.ui.components.dialog import CLOSE_KEEP, CLOSE_STAY, CLOSE_STOP, ask_close_mid_run
from ventulus.ui.pages.diagnostics_workers import (
    _CharacterizationWorker,
    _ControlPathWorker,
    _OpenFanCalibrationWorker,
)
from ventulus.ui.pages.hardware_page import VERIFY_ACTIVE_REASON, HardwarePage
from ventulus.ui.pages.system_state_page import SystemStatePage
from ventulus.ui.widgets.control_path_dialog import ControlPathDiscoveryDialog
from ventulus.ui.widgets.cooling_device_card import CoolingDeviceCard
from ventulus.ui.widgets.openfan_calibration_dialog import OpenFanCalibrationDialog
from ventulus.ui.widgets.pwm_characterization_dialog import PwmCharacterizationDialog

# ── fixtures ─────────────────────────────────────────────────────────────────

PUMP_ID = "hwmon:nct6799:isa-0a20:pwm5:AIO_PUMP"
FAN_ID = "hwmon:nct6799:isa-0a20:pwm1:CPU_FAN"


def _caps(**control) -> Capabilities:
    control.setdefault("autonomous_control", True)
    control.setdefault("header_roles", True)
    control.setdefault("pwm_characterization", True)
    control.setdefault("control_path_discovery", True)
    control.setdefault("cooling_devices", True)
    control.setdefault("validation_sessions", True)
    return Capabilities(daemon_version="5.0.0", control=ControlCapability(**control))


def _pump(**kw) -> HwmonHeader:
    base = {
        "id": PUMP_ID,
        "label": "AIO_PUMP",
        "chip_name": "nct6799",
        "device_id": "isa-0a20",
        "pwm_index": 5,
        "supports_enable": True,
        "rpm_available": True,
        "is_writable": True,
        "role": "pump",
        "role_source": "label",
        "effective_min_pwm_pct": 30,
        "stop_permitted": False,
    }
    base.update(kw)
    return HwmonHeader(**base)


def _fan(**kw) -> HwmonHeader:
    base = {
        "id": FAN_ID,
        "label": "CPU_FAN",
        "chip_name": "nct6799",
        "device_id": "isa-0a20",
        "pwm_index": 1,
        "supports_enable": True,
        "rpm_available": True,
        "is_writable": True,
        "role": "cpu_fan",
        "role_source": "label",
    }
    base.update(kw)
    return HwmonHeader(**base)


def _device(**kw) -> CoolingDevice:
    base = {
        "id": "aio0",
        "name": "AIO Cooling System",
        "kind": "aio_liquid",
        "pump_member": PUMP_ID,
        "radiator_members": [FAN_ID],
        "coolant_telemetry": "unavailable",
    }
    base.update(kw)
    return CoolingDevice(**base)


def _state(*, caps=None, headers=None, mode=OperationMode.AUTOMATIC) -> AppState:
    state = AppState()
    state.set_connection(ConnectionState.CONNECTED)
    state.set_mode(mode)
    state.set_capabilities(caps or _caps())
    state.set_hwmon_headers(headers if headers is not None else [_pump(), _fan()])
    return state


class _SocketOnly:
    socket_path = "/nonexistent/ventulus.sock"


_NO_CLIENT = object()


def _system_state(qtbot, state=None, *, client=_NO_CLIENT):
    state = state or _state()
    client = _SocketOnly() if client is _NO_CLIENT else client
    page = SystemStatePage(
        state=state, diagnostics_service=DiagnosticsService(state), client=client
    )
    qtbot.addWidget(page)
    page._populate_verify_combo()
    page._ensure_verify_worker = lambda: True  # type: ignore[method-assign]  # no real thread
    return page, state


def _hardware(qtbot, state=None, *, devices=None):
    state = state or _state()
    if devices is not None:
        state.set_cooling_devices(CoolingDeviceInventory(cooling_devices=devices))
    page = HardwarePage(state=state, diagnostics_service=DiagnosticsService(state), client=None)
    qtbot.addWidget(page)
    for name in ("_ensure_char_worker", "_ensure_discover_worker", "_ensure_verify_worker"):
        setattr(page, name, lambda: True)
    return page, state


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text)


# ── #6 / #7: the Health card's sweep ─────────────────────────────────────────


def _health_btn(page) -> QPushButton:
    return page._health_card.findChild(QPushButton, "SystemState_Btn_verifyBoardNotes")


def _health_status(page) -> QLabel:
    return page._health_card.findChild(QLabel, "SystemState_Label_verifyBoardNotesStatus")


def _open_board_notes(page) -> None:
    """Where the user is when they click: the notes shown and expanded."""
    section = page._health_card._notes_section
    section.setVisible(True)
    section.set_expanded(True)


class TestHealthCardSweepGate:
    def test_a_report_run_stands_the_health_button_down(self, qtbot):
        page, _ = _system_state(qtbot)
        requested: list[str] = []
        page._verify_request.connect(requested.append)
        page.set_pwm_report_active(True)

        button = _health_btn(page)
        assert button.isEnabled() is False
        assert button.toolTip() == RUN_ACTIVE_REASON
        # The entry point holds the rule too: the card's signal is what any
        # future path into the sweep would use.
        page._health_card.verify_requested.emit()
        assert requested == []
        assert _health_status(page).text() == RUN_ACTIVE_REASON

        page.set_pwm_report_active(False)
        assert button.isEnabled() is True
        button.click()
        assert requested == [PUMP_ID]

    def test_a_single_verify_in_flight_stands_the_health_button_down(self, qtbot):
        page, _ = _system_state(qtbot)
        requested: list[str] = []
        page._verify_request.connect(requested.append)
        page._verify_btn.click()
        assert len(requested) == 1, "precondition: the single verify was sent"

        assert _health_btn(page).isEnabled() is False
        page._health_card.verify_requested.emit()
        assert len(requested) == 1, "a sweep must not queue behind a verify in flight"
        assert "already running" in _health_status(page).text()

        page._on_verify_ok(HwmonVerifyResult(header_id=requested[0], result="effective"), "")
        assert _health_btn(page).isEnabled() is True

    def test_the_card_shows_the_sweep_from_start_to_summary(self, qtbot):
        page, _ = _system_state(qtbot)
        requested: list[str] = []
        page._verify_request.connect(requested.append)
        _open_board_notes(page)
        button = _health_btn(page)
        status = _health_status(page)
        assert status.isVisibleTo(page._health_card) is False

        button.click()
        assert requested == [PUMP_ID]
        assert button.isEnabled() is False
        assert button.text() == "Testing..."
        assert status.isVisibleTo(page._health_card)
        assert status.text() == page._verify_all_progress_label.text()
        assert status.text().startswith("Testing 1/2")

        page._on_verify_ok(HwmonVerifyResult(header_id=PUMP_ID, result="effective"), PUMP_ID)
        page._on_verify_ok(HwmonVerifyResult(header_id=FAN_ID, result="effective"), FAN_ID)
        assert page._verify_all_total == 0
        assert "2/2 tested" in status.text()
        assert status.text() == page._verify_all_progress_label.text()
        assert status.property("class") == page._verify_all_progress_label.property("class")
        assert button.isEnabled() is True
        assert button.text() == "Test fan control"

    def test_a_refusal_is_shown_on_the_card(self, qtbot):
        page, _ = _system_state(qtbot, client=None)
        _open_board_notes(page)
        _health_btn(page).click()
        status = _health_status(page)
        assert status.isVisibleTo(page._health_card)
        assert "no daemon connection" in status.text()


# ── GPU restore ──────────────────────────────────────────────────────────────


class TestGpuRestoreInFlight:
    def test_a_rerender_mid_restore_does_not_re_enable_the_button(self, qtbot):
        page, state = _system_state(qtbot)
        page._ensure_gpu_verify_worker = lambda: True  # type: ignore[method-assign]
        page._update_gpu_verify_availability(
            HardwareDiagnosticsResult(
                gpu=GpuDiagnosticsInfo(pci_bdf="0000:03:00.0", fan_control_method="pmfw_curve")
            )
        )
        sent: list[str] = []
        page._gpu_reset_request.connect(sent.append)
        button = page._gpu_restore_btn
        assert button.isEnabled() is True, "precondition: no profile manages the GPU"

        button.click()
        assert sent == ["0000:03:00.0"]
        assert button.isEnabled() is False
        # The two re-gating paths a restore used to be re-enabled by.
        page._update_gpu_verify_availability(
            HardwareDiagnosticsResult(
                gpu=GpuDiagnosticsInfo(pci_bdf="0000:03:00.0", fan_control_method="pmfw_curve")
            )
        )
        state.active_profile_changed.emit("Quiet")
        assert button.isEnabled() is False

        page._on_gpu_restore_ok(GpuFanResetResult(gpu_id="0000:03:00.0", reset=True))
        assert button.isEnabled() is True

    def test_an_error_releases_the_button_too(self, qtbot):
        page, _ = _system_state(qtbot)
        page._ensure_gpu_verify_worker = lambda: True  # type: ignore[method-assign]
        page._gpu_verify_bdf = "0000:03:00.0"
        page._gpu_restore_btn.click()
        assert page._gpu_restore_btn.isEnabled() is False
        page._on_gpu_restore_error("error", "boom")
        assert page._gpu_restore_btn.isEnabled() is True


# ── #17: reattach (characterisation and control-path dialogs) ────────────────


def _char_dialog(qtbot, header_id="h1"):
    dlg = PwmCharacterizationDialog(
        header_id, "AIO Pump", is_pump=True, name_for={"h2": "Rear Fan"}.get
    )
    qtbot.addWidget(dlg)
    return dlg


def _char_run(state: str, header_id="h1"):
    return CharacterizationRun(run_id="r1", header_id=header_id, state=state)


def _path_dialog(qtbot, header_id="h1"):
    dlg = ControlPathDiscoveryDialog(
        header_id, "AIO Pump", is_pump=True, name_for={"h2": "Rear Fan"}.get
    )
    qtbot.addWidget(dlg)
    return dlg


def _path_run(state: str, header_id="h1"):
    return ControlPathStatus(run=ControlPathRun(run_id="r1", header_id=header_id, state=state))


DIALOGS = [
    pytest.param(_char_dialog, _char_run, id="characterisation"),
    pytest.param(_path_dialog, _path_run, id="control-path"),
]


def _attached(qtbot, make, snapshot, reply):
    dlg = make(qtbot)
    polls: list[int] = []
    dlg.poll_requested.connect(lambda: polls.append(1))
    dlg.request_attach()
    assert polls == [1], "opening asks for the daemon's run exactly once"
    dlg.apply_run(reply)
    return dlg


@pytest.mark.parametrize(("make", "snapshot"), DIALOGS)
class TestReattach:
    def test_its_own_running_run_is_adopted(self, qtbot, make, snapshot):
        dlg = _attached(qtbot, make, snapshot, snapshot("running"))
        assert dlg._timer.isActive(), "a run still going is polled"
        assert dlg._cancel_btn.isEnabled(), "and can be cancelled"
        assert not dlg._start_btn.isEnabled()
        dlg.apply_run(snapshot("complete"))
        assert not dlg._timer.isActive()
        assert dlg._start_btn.text() == "Run again"

    def test_its_own_finished_run_is_shown_as_the_most_recent(self, qtbot, make, snapshot):
        dlg = _attached(qtbot, make, snapshot, snapshot("complete"))
        assert dlg._status_lbl.text().startswith("Most recent run")
        assert not dlg._timer.isActive()
        assert not dlg._cancel_btn.isEnabled()
        assert dlg._start_btn.isEnabled()

    def test_another_headers_running_run_holds_start_until_it_ends(self, qtbot, make, snapshot):
        dlg = _attached(qtbot, make, snapshot, snapshot("running", header_id="h2"))
        assert not dlg._start_btn.isEnabled()
        assert "Rear Fan" in dlg._status_lbl.text()
        assert "Rear Fan" in dlg._start_btn.toolTip()
        assert dlg._timer.isActive(), "watching for the other run's end"
        assert not dlg._cancel_btn.isEnabled(), "never offers Cancel on someone else's run"

        dlg.apply_run(snapshot("running", header_id="h2"))
        assert not dlg._start_btn.isEnabled()
        dlg.apply_run(snapshot("complete", header_id="h2"))
        assert dlg._start_btn.isEnabled()
        assert dlg._status_lbl.text() == "Ready to start."
        assert not dlg._timer.isActive()

    def test_an_unnamed_running_run_is_not_adopted(self, qtbot, make, snapshot):
        """An empty header id could be anyone's: Start waits, Cancel is not offered."""
        dlg = _attached(qtbot, make, snapshot, snapshot("running", header_id=""))
        assert not dlg._start_btn.isEnabled()
        assert not dlg._cancel_btn.isEnabled()
        assert dlg._status_lbl.text().startswith("Another")

    def test_another_headers_finished_run_is_ignored(self, qtbot, make, snapshot):
        dlg = _attached(qtbot, make, snapshot, snapshot("complete", header_id="h2"))
        assert dlg._status_lbl.text() == "Ready to start."
        assert dlg._start_btn.isEnabled()

    def test_a_start_before_the_reply_is_not_ended_by_it(self, qtbot, make, snapshot):
        """The open-time read was sent first, so it answers first. Read as the
        new run's first snapshot, an earlier finished run would end it."""
        dlg = make(qtbot)
        dlg.request_attach()
        dlg._start_btn.click()
        dlg.apply_run(snapshot("complete"))  # the open-time read: an earlier run
        assert dlg._timer.isActive()
        assert dlg._cancel_btn.isEnabled()
        assert dlg._start_btn.text() == "Start"

    def test_a_failed_open_time_read_leaves_the_dialog_as_it_opened(self, qtbot, make, snapshot):
        dlg = make(qtbot)
        dlg.request_attach()
        dlg.apply_error("unavailable", "Daemon unavailable during status poll")
        assert dlg._status_lbl.text() == "Ready to start."
        assert dlg._start_btn.isEnabled()


@pytest.mark.parametrize(("make", "snapshot"), DIALOGS)
class TestCloseMidRun:
    @pytest.mark.parametrize(
        ("answer", "cancels", "closes"),
        [(CLOSE_STOP, True, True), (CLOSE_KEEP, False, True), (CLOSE_STAY, False, False)],
    )
    def test_closing_mid_run_asks(
        self, qtbot, monkeypatch, make, snapshot, answer, cancels, closes
    ):
        dlg = make(qtbot)
        dlg._start_btn.click()
        dlg.apply_run(snapshot("running"))
        asked: list[int] = []
        monkeypatch.setattr(dlg, "_ask_close_mid_run", lambda: asked.append(1) or answer)
        cancelled: list[int] = []
        dlg.cancel_requested.connect(lambda: cancelled.append(1))
        rejected: list[int] = []
        dlg.rejected.connect(lambda: rejected.append(1))

        dlg._close_btn.click()
        assert asked == [1]
        assert bool(cancelled) is cancels
        assert dlg.cancel_sent_on_close is cancels
        assert bool(rejected) is closes
        dlg.stop_polling()

    def test_no_question_once_nothing_can_be_stopped(self, qtbot, monkeypatch, make, snapshot):
        dlg = make(qtbot)
        dlg._start_btn.click()
        dlg.apply_run(snapshot("running"))
        dlg._cancel_btn.click()  # already stopping
        monkeypatch.setattr(dlg, "_ask_close_mid_run", lambda: pytest.fail("asked"))
        rejected: list[int] = []
        dlg.rejected.connect(lambda: rejected.append(1))
        dlg._close_btn.click()
        assert rejected == [1]

    def test_no_question_before_a_run(self, qtbot, monkeypatch, make, snapshot):
        dlg = make(qtbot)
        monkeypatch.setattr(dlg, "_ask_close_mid_run", lambda: pytest.fail("asked"))
        rejected: list[int] = []
        dlg.rejected.connect(lambda: rejected.append(1))
        dlg._close_btn.click()
        assert rejected == [1]


# ── #17: reattach (OpenFan calibration) ──────────────────────────────────────


def _ofan(ch: int) -> FanReading:
    return FanReading(id=f"openfan:ch{ch:02d}", source="openfan", rpm=900)


def _cal_dialog(qtbot, *, demo=False):
    options = build_channel_options([_ofan(0), _ofan(3)], lambda fan_id: fan_id)
    dlg = OpenFanCalibrationDialog(options, demo=demo)
    qtbot.addWidget(dlg)
    return dlg


def _cal_run(*, running: bool) -> OpenFanCalibrationRun:
    return OpenFanCalibrationRun(
        run_id="ofcal-7",
        fan_id="openfan:ch03",
        channel=3,
        state="running" if running else "complete",
        phase="descent" if running else None,
        current_pct=40 if running else None,
        outcome=None if running else "stall_and_restart_found",
        stall_duty_pct=None if running else 12,
        restart_duty_pct=None if running else 18,
        restore_outcome="pending" if running else "restored",
        completed_unix_ms=None if running else 180_000,
    )


class TestCalibrationReattach:
    def test_a_running_walk_is_adopted_on_its_channel(self, qtbot):
        dlg = _cal_dialog(qtbot)
        assert dlg.selected_option().channel == 0, "precondition: the picker opens elsewhere"
        polls: list[int] = []
        dlg.poll_requested.connect(lambda: polls.append(1))
        dlg.request_attach()
        assert polls == [1]
        dlg.apply_run(_cal_run(running=True))
        assert dlg.selected_option().channel == 3
        assert dlg.is_running
        assert dlg._timer.isActive()
        assert dlg._cancel_btn.isEnabled()
        assert not dlg._start_btn.isEnabled()
        assert not dlg._channel_combo.isEnabled()

        dlg.apply_run(_cal_run(running=False))
        assert not dlg.is_running
        assert "18%" in dlg._advice_lbl.text()

    def test_a_finished_walk_is_shown_as_the_most_recent(self, qtbot):
        dlg = _cal_dialog(qtbot)
        dlg.request_attach()
        dlg.apply_run(_cal_run(running=False))
        assert dlg.selected_option().channel == 3
        assert dlg._status_lbl.text().startswith("Most recent run")
        assert "18%" in dlg._advice_lbl.text()
        assert not dlg.is_running
        assert not dlg._timer.isActive()

    def test_demo_mode_asks_nothing(self, qtbot):
        dlg = _cal_dialog(qtbot, demo=True)
        polls: list[int] = []
        dlg.poll_requested.connect(lambda: polls.append(1))
        dlg.request_attach()
        assert polls == []


# ── page wiring: open-time read, and a failed stop-on-close ──────────────────


class TestHardwarePageWiring:
    def test_the_characterise_window_reads_the_run_before_it_blocks(self, qtbot, monkeypatch):
        page, _ = _hardware(qtbot)
        order: list[str] = []
        page._char_preflight_request.connect(lambda *_: order.append("preflight"))
        page._char_poll_request.connect(lambda: order.append("poll"))
        monkeypatch.setattr(
            PwmCharacterizationDialog, "exec", lambda _d: order.append("exec") or 0, raising=True
        )
        page._open_characterization(PUMP_ID)
        assert order == ["preflight", "poll", "exec"]

    def test_a_vanished_header_says_why_nothing_opened(self, qtbot, monkeypatch):
        page, _ = _hardware(qtbot)
        monkeypatch.setattr(
            PwmCharacterizationDialog, "exec", lambda _d: pytest.fail("opened"), raising=True
        )
        page._open_characterization("hwmon:gone:pwm9")
        assert page._diag_result.text().startswith("Cannot characterise")


class TestSystemStatePageWiring:
    def test_the_characterise_window_reads_the_run_before_it_blocks(self, qtbot, monkeypatch):
        page, _ = _system_state(qtbot)
        page._ensure_char_worker = lambda: True  # type: ignore[method-assign]
        order: list[str] = []
        page._char_preflight_request.connect(lambda *_: order.append("preflight"))
        page._char_poll_request.connect(lambda: order.append("poll"))
        monkeypatch.setattr(
            PwmCharacterizationDialog, "exec", lambda _d: order.append("exec") or 0, raising=True
        )
        page._characterize_btn.click()
        assert order == ["preflight", "poll", "exec"]


# ── replies owed to a closed window (real worker threads) ────────────────────


class _FakeRunClient:
    """The worker's DaemonClient stand-in; called on the worker thread.

    The status read always answers "this header's run is going"; the cancel
    waits for ``release`` (a stop the daemon is slow to answer) and is refused.
    Anything else, which here is only the advisory preflight, is refused too.
    """

    def __init__(self, status_name: str, cancel_name: str, run) -> None:
        self.run = run
        self.release = threading.Event()
        self.release.set()
        setattr(self, status_name, lambda: self.run())
        setattr(self, cancel_name, self._cancel)

    def _cancel(self):
        self.release.wait(10)
        raise DaemonError(code="validation_error", message="The daemon refused the stop")

    def close(self) -> None:
        pass

    def __getattr__(self, name):
        def refused(*_a, **_kw):
            raise DaemonError(code="not_found", message=name)

        return refused


def _char_hw(qtbot):
    page, _ = _hardware_live(qtbot)
    return page, lambda: page._open_characterization(PUMP_ID), lambda: PUMP_ID, page._diag_result


def _discover_hw(qtbot):
    page, _ = _hardware_live(qtbot)
    return (
        page,
        lambda: page._open_control_path_discovery(PUMP_ID),
        lambda: PUMP_ID,
        page._diag_result,
    )


def _ofancal_hw(qtbot):
    state = _state(caps=_caps(openfan_calibration=True))
    state.set_fans([_ofan(3)])
    page, _ = _hardware_live(qtbot, state)
    return page, page._open_openfan_calibration, lambda: "", page._diag_result


def _char_system_state(qtbot):
    state = _state()
    page = SystemStatePage(
        state=state, diagnostics_service=DiagnosticsService(state), client=_SocketOnly()
    )
    qtbot.addWidget(page)
    page._populate_verify_combo()
    return (
        page,
        page._characterize_btn.click,
        page._verify_combo.currentData,
        page._verify_result_label,
    )


def _hardware_live(qtbot, state=None):
    state = state or _state()
    page = HardwarePage(
        state=state, diagnostics_service=DiagnosticsService(state), client=_SocketOnly()
    )
    qtbot.addWidget(page)
    return page, state


LIVE_KINDS = [
    pytest.param(
        _char_hw,
        _CharacterizationWorker,
        "characterization_status",
        "cancel_characterization",
        lambda hid: CharacterizationRun(run_id="r1", header_id=hid, state="running"),
        PwmCharacterizationDialog,
        "characterisation",
        id="hardware-characterise",
    ),
    pytest.param(
        _discover_hw,
        _ControlPathWorker,
        "control_path_status",
        "cancel_control_path_discovery",
        lambda hid: ControlPathStatus(
            run=ControlPathRun(run_id="r1", header_id=hid, state="running")
        ),
        ControlPathDiscoveryDialog,
        "control-path discovery",
        id="hardware-discover",
    ),
    pytest.param(
        _ofancal_hw,
        _OpenFanCalibrationWorker,
        "openfan_calibration_status",
        "cancel_openfan_calibration",
        lambda _hid: _cal_run(running=True),
        OpenFanCalibrationDialog,
        "calibration",
        id="hardware-calibrate",
    ),
    pytest.param(
        _char_system_state,
        _CharacterizationWorker,
        "characterization_status",
        "cancel_characterization",
        lambda hid: CharacterizationRun(run_id="r1", header_id=hid, state="running"),
        PwmCharacterizationDialog,
        "characterisation",
        id="system-state-characterise",
    ),
]


def _adopted(dialog) -> bool:
    if isinstance(dialog, OpenFanCalibrationDialog):
        return dialog.is_running
    return dialog._run_tracked()


@pytest.mark.parametrize(
    ("make", "worker_cls", "status_name", "cancel_name", "run", "dialog_cls", "what"),
    LIVE_KINDS,
)
class TestRepliesOwedToAClosedWindow:
    """The page routes a worker's in-order replies by counting (`RunReplyLedger`)."""

    def _setup(self, qtbot, monkeypatch, make, worker_cls, status_name, cancel_name, run):
        page, open_window, header_id, label = make(qtbot)
        client = _FakeRunClient(status_name, cancel_name, lambda: run(header_id()))
        monkeypatch.setattr(worker_cls, "_ensure_client", lambda _self: client)
        return page, open_window, label, client

    def _close_with_stop(self, qtbot, *, poll_in_flight: bool):
        def fake_exec(dialog):
            qtbot.waitUntil(lambda: _adopted(dialog), timeout=5000)
            if poll_in_flight:
                dialog.poll_requested.emit()
            dialog.cancel_sent_on_close = True
            dialog.cancel_requested.emit()
            return 0

        return fake_exec

    def test_a_failed_stop_is_reported_behind_a_poll_still_in_flight(
        self, qtbot, monkeypatch, make, worker_cls, status_name, cancel_name, run, dialog_cls, what
    ):
        page, open_window, label, _client = self._setup(
            qtbot, monkeypatch, make, worker_cls, status_name, cancel_name, run
        )
        monkeypatch.setattr(
            dialog_cls, "exec", self._close_with_stop(qtbot, poll_in_flight=True), raising=True
        )
        try:
            open_window()
            # The poll answers first, and successfully: it must not be taken for
            # the stop's answer and clear the report.
            qtbot.waitUntil(lambda: f"Could not stop the {what}" in label.text(), timeout=5000)
            assert "The daemon refused the stop" in label.text()
        finally:
            page.cleanup()

    def test_a_window_reopened_before_the_stop_is_answered_still_adopts_the_run(
        self, qtbot, monkeypatch, make, worker_cls, status_name, cancel_name, run, dialog_cls, what
    ):
        page, open_window, label, client = self._setup(
            qtbot, monkeypatch, make, worker_cls, status_name, cancel_name, run
        )
        client.release.clear()  # the stop is slow to be answered
        adopted: list[bool] = []

        def second_exec(dialog):
            client.release.set()
            qtbot.waitUntil(lambda: not dialog._attaching, timeout=5000)
            qtbot.waitUntil(lambda: _adopted(dialog), timeout=5000)
            adopted.append(True)
            return 0

        execs = [self._close_with_stop(qtbot, poll_in_flight=False), second_exec]
        monkeypatch.setattr(dialog_cls, "exec", lambda d: execs.pop(0)(d), raising=True)
        try:
            open_window()
            open_window()
            # The stop's refusal, not the new window's answer: reported on the
            # page, and the run the new window asked about is adopted.
            assert adopted == [True]
            qtbot.waitUntil(lambda: f"Could not stop the {what}" in label.text(), timeout=5000)
        finally:
            client.release.set()
            page.cleanup()


class TestRunReplyLedger:
    def test_with_no_window_closed_every_reply_is_the_windows(self):
        ledger = RunReplyLedger()
        ledger.window_opened()
        ledger.sent()
        ledger.sent()
        assert [ledger.received(), ledger.received()] == [ReplyRoute.WINDOW] * 2

    def test_replies_in_flight_at_open_are_not_the_new_windows(self):
        ledger = RunReplyLedger()
        ledger.sent()  # e.g. a background status refresh
        ledger.window_opened()
        ledger.sent()  # the window's own read
        assert [ledger.received(), ledger.received()] == [ReplyRoute.EARLIER, ReplyRoute.WINDOW]

    def test_the_last_reply_owed_to_a_window_closed_with_stop_is_the_stops(self):
        ledger = RunReplyLedger()
        ledger.window_opened()
        ledger.sent()  # a poll in flight
        ledger.sent()  # the stop
        ledger.window_closed(stop_sent=True)
        ledger.sent()  # sent after the close (the discovery refresh)
        assert [ledger.received() for _ in range(3)] == [
            ReplyRoute.EARLIER,
            ReplyRoute.STOP_ANSWER,
            ReplyRoute.WINDOW,
        ]

    def test_a_stop_keeps_its_place_across_a_reopen_and_a_plain_close(self):
        ledger = RunReplyLedger()
        ledger.window_opened()
        ledger.sent()  # the stop
        ledger.window_closed(stop_sent=True)
        ledger.window_opened()
        ledger.sent()  # the new window's read
        ledger.window_closed(stop_sent=False)
        ledger.window_opened()
        ledger.sent()
        assert [ledger.received() for _ in range(3)] == [
            ReplyRoute.STOP_ANSWER,
            ReplyRoute.EARLIER,
            ReplyRoute.WINDOW,
        ]

    def test_a_close_without_stop_reports_nothing(self):
        ledger = RunReplyLedger()
        ledger.window_opened()
        ledger.sent()
        ledger.window_closed(stop_sent=False)
        assert ledger.received() is ReplyRoute.EARLIER


# ── the preflight after a run, and the close question's re-check ────────────


def _preflight(*, blocked: bool):
    return parse_preflight_report(
        {
            "header_id": "h1",
            "diagnostic": "pwm_characterization",
            "verdict": "blocked" if blocked else "ready",
            "checks": [
                {
                    "check_id": "control_ownership",
                    "state": "fail" if blocked else "pass",
                    "detail": "Another hardware diagnostic is already running",
                }
            ],
            "blocking": ["control_ownership"] if blocked else [],
        }
    )


@pytest.mark.parametrize(("make", "snapshot"), DIALOGS)
class TestPreflightAfterARun:
    """The verdict fetched at open was given while a run held the slot."""

    def test_start_returns_once_another_headers_run_ends(self, qtbot, make, snapshot):
        dlg = make(qtbot)
        asked: list[int] = []
        dlg.preflight_requested.connect(lambda *_: asked.append(1))
        dlg.apply_preflight(_preflight(blocked=True))
        dlg.request_attach()
        dlg.apply_run(snapshot("running", header_id="h2"))
        dlg.apply_run(snapshot("complete", header_id="h2"))
        assert asked == [1], "the slot was freed: the verdict is asked for again"
        dlg.apply_preflight(_preflight(blocked=False))
        assert dlg._start_btn.isEnabled()
        assert dlg._blocked_lbl.isHidden()

    def test_run_again_follows_a_fresh_verdict_after_an_adopted_run(self, qtbot, make, snapshot):
        dlg = make(qtbot)
        asked: list[int] = []
        dlg.preflight_requested.connect(lambda *_: asked.append(1))
        dlg.apply_preflight(_preflight(blocked=True))  # its own run held the slot
        dlg.request_attach()
        dlg.apply_run(snapshot("running"))
        dlg.apply_run(snapshot("complete"))
        assert asked == [1]
        dlg.apply_preflight(_preflight(blocked=False))
        assert dlg._start_btn.isEnabled()
        assert dlg._blocked_lbl.isHidden()
        dlg.apply_preflight(_preflight(blocked=True))
        assert not dlg._start_btn.isEnabled(), "after the run, the verdict governs Start"


class TestCloseQuestionRechecks:
    @pytest.mark.parametrize(("make", "snapshot"), DIALOGS)
    def test_a_run_that_ends_during_the_question_is_not_stopped(
        self, qtbot, monkeypatch, make, snapshot
    ):
        dlg = make(qtbot)
        dlg._start_btn.click()
        dlg.apply_run(snapshot("running"))

        def answer():
            dlg.apply_run(snapshot("complete"))  # a poll lands behind the question
            return CLOSE_STOP

        monkeypatch.setattr(dlg, "_ask_close_mid_run", answer)
        cancelled: list[int] = []
        dlg.cancel_requested.connect(lambda: cancelled.append(1))
        dlg._close_btn.click()
        assert cancelled == []
        assert dlg.cancel_sent_on_close is False

    def test_a_calibration_that_ends_during_the_question_is_not_stopped(self, qtbot, monkeypatch):
        dlg = _cal_dialog(qtbot)
        dlg.request_attach()
        dlg.apply_run(_cal_run(running=True))
        assert dlg.is_running, "precondition"

        def answer():
            dlg.apply_run(_cal_run(running=False))
            return CLOSE_STOP

        monkeypatch.setattr(dlg, "_ask_close_mid_run", answer)
        cancelled: list[int] = []
        dlg.cancel_requested.connect(lambda: cancelled.append(1))
        dlg._close_btn.click()
        assert cancelled == []
        assert dlg.cancel_sent_on_close is False


class TestAskCloseMidRun:
    """The shared prompt's answer decides whether a cancel is sent."""

    @pytest.mark.parametrize(
        ("pick", "expected"),
        [
            ("Stop it", CLOSE_STOP),
            ("Keep running", CLOSE_KEEP),
            ("Stay here", CLOSE_STAY),
            (None, CLOSE_STAY),  # Escape or the title-bar X
        ],
    )
    def test_each_answer(self, qtbot, monkeypatch, pick, expected):
        parent = QWidget()
        qtbot.addWidget(parent)

        # The suite's modal isolation makes every `exec()` return at once; this
        # test is about the answer, so the box waits for one in its own loop.
        def wait_for_answer(box):
            loop = QEventLoop()
            box.finished.connect(loop.quit)
            box.open()
            loop.exec()
            return box.result()

        monkeypatch.setattr(QMessageBox, "exec", wait_for_answer)

        def answer():
            box = parent.findChild(QMessageBox, "Test_Msg_closeMidRun")
            assert box is not None, "the prompt is open"
            if pick is None:
                box.reject()
            else:
                next(b for b in box.buttons() if b.text() == pick).click()

        QTimer.singleShot(0, answer)
        got = ask_close_mid_run(
            parent,
            object_name="Test_Msg_closeMidRun",
            title="Still running",
            text="It is still running.",
            informative="Stop it?",
            stop_label="Stop it",
        )
        assert got == expected


# ── device-card gates ────────────────────────────────────────────────────────


def _device_card(page) -> CoolingDeviceCard:
    return page._device_cards["aio0"]


def _char_pump_btn(page) -> QPushButton:
    return _device_card(page).findChild(QPushButton, "CoolingDeviceCard_Btn_charPump_aio0")


def _validate_btn(page) -> QPushButton:
    return _device_card(page).findChild(QPushButton, "CoolingDeviceCard_Btn_validate_aio0")


class TestDeviceCardGates:
    @pytest.mark.parametrize("writable", [True, False])
    def test_characterise_pump_follows_the_pump_headers_own_card(self, qtbot, writable):
        pump = _pump(is_writable=writable)
        page, _ = _hardware(qtbot, _state(headers=[pump, _fan()]), devices=[_device()])
        view = build_header_inspector_view(pump, capabilities=_caps())
        assert view.can_characterize is writable, "precondition: the two branches differ"
        assert _char_pump_btn(page).isEnabled() is view.can_characterize
        assert _char_pump_btn(page).toolTip() == view.characterize_disabled_reason

    def test_a_missing_pump_header_greys_characterise_and_says_why(self, qtbot):
        page, _ = _hardware(qtbot, _state(headers=[_fan()]), devices=[_device()])
        assert _char_pump_btn(page).isEnabled() is False
        assert "not found" in _char_pump_btn(page).toolTip()

    def test_start_validation_needs_the_session_capability(self, qtbot):
        page, _ = _hardware(qtbot, devices=[_device()])
        assert _validate_btn(page).isEnabled() is True

        page, _ = _hardware(
            qtbot, _state(caps=_caps(validation_sessions=False)), devices=[_device()]
        )
        assert _validate_btn(page).isEnabled() is False
        assert _validate_btn(page).toolTip() == unsupported_feature_message("validation_sessions")
        page._ensure_validation_worker = lambda: pytest.fail("opened")  # type: ignore[method-assign]
        page._open_validation(kind="validation", device_id="aio0")
        assert page._diag_result.text() == unsupported_feature_message("validation_sessions")

    def test_a_page_verify_stands_both_down_until_it_answers(self, qtbot):
        page, _ = _hardware(qtbot, devices=[_device()])
        buttons = [_char_pump_btn(page), _validate_btn(page)]
        assert all(b.isEnabled() for b in buttons), "precondition: both live"
        card = page._header_cards[FAN_ID]
        card.findChild(QPushButton, f"HeaderCard_Btn_test_{_slug(FAN_ID)}").click()
        assert not any(b.isEnabled() for b in buttons)
        assert all(b.toolTip() == VERIFY_ACTIVE_REASON for b in buttons)
        page._on_verify_ok(HwmonVerifyResult(header_id=FAN_ID, result="effective"), FAN_ID)
        assert all(b.isEnabled() for b in buttons)

    def test_a_pump_on_no_motherboard_header_says_so(self, qtbot):
        page, _ = _hardware(qtbot, devices=[_device(pump_member="openfan:ch00")])
        assert _char_pump_btn(page).isEnabled() is False
        assert "not connected to one" in _char_pump_btn(page).toolTip()
