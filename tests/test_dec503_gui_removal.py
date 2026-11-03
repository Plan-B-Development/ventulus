"""DEC-503 `TDY-4`: the tests that drive fans for minutes left the GUI.

The PWM Test Report, Characterise, Discover Control Path and the validation
sessions run from ``ventulus-diag``. The GUI keeps the short checks, names the
command in one informational panel that launches nothing, still shows a
discovered control path read-only, and words the daemon's busy-slot refusal as
another test running.

Standing rules: presence before absence, relationships over literals,
``isVisibleTo`` under offscreen.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from ventulus.api.errors import OPENFAN_MAINTENANCE_REASON, DaemonError
from ventulus.api.models import (
    Capabilities,
    ConnectionState,
    ControlCapability,
    CoolingDevice,
    CoolingDeviceInventory,
    FanReading,
    HwmonHeader,
)
from ventulus.services.app_state import AppState
from ventulus.services.diag_cli_view import (
    HARDWARE_TESTS_COMMAND,
    HARDWARE_TESTS_TEXT,
    SLOT_BUSY_TEXT,
    is_slot_busy_refusal,
    slot_busy_text,
)
from ventulus.services.diagnostics_service import DiagnosticsService
from ventulus.ui.pages.diagnostics_workers import (
    _ControlPathWorker,
    _GpuVerifyWorker,
    _OpenFanCalibrationWorker,
    _VerifyWorker,
)
from ventulus.ui.pages.hardware_page import HardwarePage
from ventulus.ui.pages.system_state_page import SystemStatePage

PUMP = "hwmon:nct6799:isa-0a20:pwm5:AIO_PUMP"
FAN = "hwmon:nct6799:isa-0a20:pwm1:CPU_FAN"

#: Every word a moved test's button carried. None may label a GUI button.
MOVED_WORDS = (
    "PWM Test Report",
    "Characterise",
    "Discover",
    "Validation",
    "Lifecycle",
    "Thermal Observation",
)


def _header(header_id: str, label: str, index: int, role: str) -> HwmonHeader:
    return HwmonHeader(
        id=header_id,
        label=label,
        chip_name="nct6799",
        device_id="isa-0a20",
        pwm_index=index,
        supports_enable=True,
        rpm_available=True,
        is_writable=True,
        role=role,
        role_source="label",
    )


def _caps() -> Capabilities:
    return Capabilities(
        control=ControlCapability(
            header_roles=True,
            pwm_characterization=True,
            control_path_discovery=True,
            cooling_devices=True,
            validation_sessions=True,
            thermal_observation=True,
        )
    )


def _hardware(qtbot) -> HardwarePage:
    state = AppState()
    state.set_connection(ConnectionState.CONNECTED)
    state.set_capabilities(_caps())
    state.set_hwmon_headers(
        [_header(PUMP, "AIO_PUMP", 5, "pump"), _header(FAN, "CPU_FAN", 1, "cpu_fan")]
    )
    state.set_fans([FanReading(id=h, source="hwmon", rpm=1200, age_ms=500) for h in (PUMP, FAN)])
    state.set_cooling_devices(
        CoolingDeviceInventory(
            cooling_devices=[
                CoolingDevice(id="aio0", name="AIO", kind="aio_liquid", pump_member=PUMP)
            ]
        )
    )
    page = HardwarePage(state=state, diagnostics_service=DiagnosticsService(state))
    qtbot.addWidget(page)
    return page


# ── no GUI control launches a moved test ─────────────────────────────────────


def test_no_hardware_page_button_names_a_moved_test(qtbot):
    page = _hardware(qtbot)
    buttons = page.findChildren(QPushButton)
    names = {b.objectName() for b in buttons}
    # Presence first: the page, its cards and the tests that stay are built.
    assert "Hardware_Btn_openfanCalibration" in names
    assert any(n.startswith("HeaderCard_Btn_test_") for n in names)
    assert any(n.startswith("CoolingDeviceCard_Btn_viewHeaders_") for n in names)
    for button in buttons:
        text = f"{button.text()} {button.accessibleName()}"
        assert not any(word in text for word in MOVED_WORDS), button.objectName()


def test_a_header_card_offers_only_its_short_test_and_its_role(qtbot):
    page = _hardware(qtbot)
    card = page._header_cards[FAN]
    kinds = sorted(
        b.objectName().split("_")[2]
        for b in card.findChildren(QPushButton)
        if b.objectName().startswith("HeaderCard_Btn_")
    )
    assert kinds == ["role", "test"]


def test_system_state_keeps_verify_and_offers_no_characterisation(qtbot):
    page = SystemStatePage(state=AppState())
    qtbot.addWidget(page)
    assert page.findChild(QPushButton, "SystemState_Btn_verifyAll") is not None
    buttons = page.findChildren(QPushButton)
    assert buttons, "precondition: the page built its buttons"
    assert not any("Characteris" in b.text() for b in buttons)


# ── the informational panel ──────────────────────────────────────────────────


def test_the_panel_names_the_command_and_copies_it(qtbot):
    page = _hardware(qtbot)
    note = page.findChild(QLabel, "Hardware_Label_diagCli")
    assert note is not None and note.text() == HARDWARE_TESTS_TEXT
    assert note.isVisibleTo(page)
    assert "ventulus-diag" in note.text()
    copy = page.findChild(QPushButton, "Hardware_CmdCopy_diagCli")
    assert copy is not None and copy.isVisibleTo(page)
    QApplication.clipboard().setText("")
    copy.click()
    assert QApplication.clipboard().text() == HARDWARE_TESTS_COMMAND
    assert HARDWARE_TESTS_COMMAND.startswith("ventulus-diag ")


def test_the_panel_names_every_moved_test():
    for word in ("PWM Test Report", "Characterise", "Discover", "validation"):
        assert word in HARDWARE_TESTS_TEXT


# ── the daemon's busy-slot refusal ───────────────────────────────────────────


def _refusal(*, status=409, code="validation_error", retryable=False, details=None):
    return DaemonError(
        code=code,
        message="a hardware verify or calibration is already in progress",
        retryable=retryable,
        status=status,
        details=details,
    )


@pytest.mark.parametrize(
    ("err", "busy"),
    [
        (_refusal(), True),
        # Protection: retryable, worded by the daemon.
        (_refusal(retryable=True), False),
        (_refusal(code="thermal_abort"), False),
        # A firmware update holding the controller names itself.
        (_refusal(retryable=True, details={"reason": OPENFAN_MAINTENANCE_REASON}), False),
        (_refusal(details={"reason": OPENFAN_MAINTENANCE_REASON}), False),
        # Not a conflict at all.
        (_refusal(status=400), False),
        (_refusal(status=404, code="not_found"), False),
    ],
)
def test_only_the_slot_refusal_reads_as_another_test(err, busy):
    assert is_slot_busy_refusal(err.status, err.code, err.retryable, err.details) is busy
    assert slot_busy_text(err) == (SLOT_BUSY_TEXT if busy else "")


class _Raising:
    def __init__(self, err: DaemonError) -> None:
        self._err = err

    def __getattr__(self, _name):
        def call(*_a, **_kw):
            raise self._err

        return call


def _worker(cls, err: DaemonError, monkeypatch):
    worker = cls("/nonexistent.sock")
    monkeypatch.setattr(cls, "_ensure_client", lambda _self: _Raising(err))
    return worker


def test_a_verify_refused_by_a_busy_slot_says_another_test_is_running(monkeypatch):
    worker = _worker(_VerifyWorker, _refusal(), monkeypatch)
    errors: list[tuple] = []
    worker.verify_error.connect(lambda *a: errors.append(a))
    worker.do_verify(FAN)
    assert errors == [("unavailable", SLOT_BUSY_TEXT, FAN)]


def test_a_verify_refused_for_another_reason_keeps_the_daemons_words(monkeypatch):
    err = _refusal(status=400)
    worker = _worker(_VerifyWorker, err, monkeypatch)
    errors: list[tuple] = []
    worker.verify_error.connect(lambda *a: errors.append(a))
    worker.do_verify(FAN)
    assert errors == [("error", err.message, FAN)]


def test_a_gpu_test_refused_by_a_busy_slot_says_another_test_is_running(monkeypatch):
    worker = _worker(_GpuVerifyWorker, _refusal(), monkeypatch)
    errors: list[tuple] = []
    worker.verify_error.connect(lambda *a: errors.append(a))
    worker.do_verify("gpu0")
    assert errors == [("unavailable", SLOT_BUSY_TEXT)]


def test_only_a_calibration_start_reads_a_409_as_a_busy_slot(monkeypatch):
    err = _refusal()
    worker = _worker(_OpenFanCalibrationWorker, err, monkeypatch)
    errors: list[tuple] = []
    worker.run_error.connect(lambda *a: errors.append(a))
    worker.do_start(3)
    assert errors == [("unavailable", SLOT_BUSY_TEXT)]
    # A cancel's 409 means nothing was running; it is not another test.
    errors.clear()
    worker.do_cancel()
    assert errors == [("error", err.message)]


def test_the_hardware_page_shows_the_busy_wording_unprefixed(qtbot):
    page = _hardware(qtbot)
    page._verifies_in_flight = 1
    page._on_verify_error("unavailable", SLOT_BUSY_TEXT, FAN)
    assert page._diag_result.text() == SLOT_BUSY_TEXT
    assert page._verifies_in_flight == 0


# ── control paths stay visible, read-only ────────────────────────────────────


def _requests(page) -> list[int]:
    sent: list[int] = []
    page._ensure_control_path_worker = lambda: True  # type: ignore[method-assign]
    page._control_paths_request.connect(lambda: sent.append(1))
    return sent


def test_the_page_reads_the_persisted_paths_when_the_daemon_has_them(qtbot):
    page = _hardware(qtbot)
    sent = _requests(page)
    page._state.set_capabilities(_caps())
    assert sent, "a capability refresh asks for the persisted relationships"


def test_no_read_against_a_daemon_without_discovery(qtbot):
    page = _hardware(qtbot)
    sent = _requests(page)
    page._state.set_capabilities(
        Capabilities(control=ControlCapability(control_path_discovery=False))
    )
    assert sent == []
    # The opposite branch, on the same page: the flag turns the read on.
    page._state.set_capabilities(_caps())
    assert sent


# ── the report's setup facts survive the GUI for the CLI ─────────────────────


def test_the_setup_facts_survive_a_gui_save_and_reach_ventulus_diag(tmp_path):
    """No GUI screen edits `hardware_notes`/`cooler_notes` now, but an older
    GUI recorded them and `ventulus-diag report run` reads them as defaults. A
    GUI load and save must carry them through unchanged."""
    import json

    from ventulus.diag.daemon import read_gui_settings
    from ventulus.services.app_settings_service import AppSettings

    notes = {FAN: {"connected": "fan", "fans_behind": 2, "bios_mode": "", "notes": "hub"}}
    cooler = {"model": "NL-LC1", "pump_switch": ""}
    saved = AppSettings.from_dict({"hardware_notes": notes, "cooler_notes": cooler}).to_dict()
    path = tmp_path / "app_settings.json"
    path.write_text(json.dumps(saved))
    read = read_gui_settings(lambda: path)
    assert read.hardware_notes == AppSettings.from_dict(saved).hardware_notes
    assert read.hardware_notes[FAN]["notes"] == "hub"
    assert read.cooler_notes == cooler


# ── readiness actions lead to a test that is still here ──────────────────────


def test_the_test_pwm_control_action_lands_on_the_header_cards(qtbot, monkeypatch):
    """The checklist's "Test PWM control" used to land on Hardware Diagnostics,
    where the PWM Test Report was; it now holds no PWM test, so the action must
    reach the cards that carry Test Control."""
    page = _hardware(qtbot)
    seen: list = []
    monkeypatch.setattr(page._scroll, "ensureWidgetVisible", lambda w, *a: seen.append(w))
    page._route_action("pwm_verify")
    assert seen == [page._header_container]
    # What it reaches carries the test (presence), and the section it used to
    # reach carries none.
    tests = [
        b
        for b in page._header_container.findChildren(QPushButton)
        if b.objectName().startswith("HeaderCard_Btn_test_")
    ]
    assert tests
    assert not any(
        b.objectName().startswith("HeaderCard_Btn_test_")
        for b in page._diagnostics_card.findChildren(QPushButton)
    )


# ── the control-path read, end to end through the real worker ────────────────


class _PathsClient:
    """The worker's client: answers the GET with whatever the test set."""

    def __init__(self, status) -> None:
        self.status = status

    def control_path_status(self):
        return self.status

    def close(self) -> None:
        pass


def _record():
    from ventulus.api.models import ControlPathRecord

    return ControlPathRecord(
        header_id=FAN,
        relationship="confirmed",
        confidence="high",
        tach_labels=["fan1"],
        validated_unix_ms=1_700_000_000_000,
    )


@pytest.fixture
def wired(qtbot, monkeypatch):
    """A Hardware page with a real control-path worker on its own thread, over a
    fake client. Always cleaned up: a QThread destroyed while running aborts."""
    from types import SimpleNamespace

    from ventulus.api.models import ControlPathStatus

    fake = _PathsClient(ControlPathStatus(records=[_record()], from_status_endpoint=True))
    monkeypatch.setattr(_ControlPathWorker, "_ensure_client", lambda _self: fake)
    state = AppState()
    state.set_connection(ConnectionState.CONNECTED)
    state.set_hwmon_headers([_header(FAN, "CPU_FAN", 1, "cpu_fan")])
    state.set_fans([FanReading(id=FAN, source="hwmon", rpm=1200, age_ms=500)])
    page = HardwarePage(
        state=state,
        diagnostics_service=DiagnosticsService(state),
        client=SimpleNamespace(socket_path="/nonexistent/test.sock"),
    )
    qtbot.addWidget(page)
    yield page, state, fake
    page.cleanup()


def _relationship_label(page) -> QLabel:
    from ventulus.ui.widgets.pwm_header_card import _slug

    label = page.findChild(QLabel, f"HeaderCard_Relationship_{_slug(FAN)}")
    assert label is not None
    return label


def test_a_persisted_path_reaches_its_card_through_the_worker(qtbot, wired):
    """Capabilities → the real `_ControlPathWorker` on its thread → the queued
    `run_updated` → the card's Relationship line. Nothing stubbed on the page."""
    page, state, _ = wired
    state.set_capabilities(_caps())
    label = _relationship_label(page)
    qtbot.waitUntil(lambda: bool(label.text()), timeout=3000)
    assert "fan1" in label.text()
    assert not label.isHidden()


def test_a_path_the_daemon_dropped_leaves_the_card(qtbot, wired):
    """The daemon answers 404, which the client returns as `None`, once it holds
    no run and no records. The card must not keep the old relationship."""
    page, state, fake = wired
    state.set_capabilities(_caps())
    qtbot.waitUntil(lambda: FAN in page._control_paths, timeout=3000)
    fake.status = None
    page._refresh_control_paths()
    qtbot.waitUntil(lambda: page._control_paths == {}, timeout=3000)
    label = _relationship_label(page)
    assert label.text() == "" and label.isHidden()


def test_rescan_rereads_the_control_paths(qtbot):
    page = _hardware(qtbot)
    sent = _requests(page)
    page._rescan()
    assert sent, "a CLI discovery since the last capability refresh shows on Re-scan"


def test_the_panel_names_the_command_that_stops_a_session():
    from ventulus.services.diag_cli_view import SESSION_STOP_COMMAND

    assert SESSION_STOP_COMMAND in HARDWARE_TESTS_TEXT
