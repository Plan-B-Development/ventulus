"""GUI audit 2026-10-14, batch E: the Fan Wizard and the PWM Test Report.

Wizard: Finish keeps the Review page's edits and saves only the fans it
reviewed; Skip comes back on re-entry; the intro page re-checks live and a hot
CPU warns without blocking; status chips restyle; "restored" only when the
daemon said so. Report: a failed save is not painted over, and "Saved to"
never names an earlier run's file or a stale checkpoint.

Every wizard/page a helper returns is bound and used in an assertion
(DASH-h): ``qtbot.addWidget`` does not keep it alive.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QWizard

from tests.pwm_report_fixtures import CPU
from tests.test_pwm_report_window import _box, _btn, _clear, _run_to_end, rig  # noqa: F401
from ventulus.api.errors import DaemonError
from ventulus.api.models import ConnectionState, FanReading, OperationMode, SensorReading
from ventulus.services.app_state import AppState
from ventulus.services.pwm_report import store
from ventulus.ui.widgets.fan_wizard import (
    PAGE_DISCOVERY,
    PAGE_INTRO,
    PAGE_REVIEW,
    PAGE_TEST,
    FanConfigWizard,
    thermal_limit_c,
)
from ventulus.ui.widgets.pwm_report_window import PAGE_REPORT

FANS = ("openfan:ch00", "openfan:ch01", "openfan:ch02")


def _state(*, connected: bool = True, cpu_c: float = 45.0) -> AppState:
    state = AppState()
    if connected:
        state.set_connection(ConnectionState.CONNECTED)
    state.set_mode(OperationMode.AUTOMATIC)
    state.set_fans([FanReading(id=f, source="openfan", rpm=1000, age_ms=50) for f in FANS])
    state.set_sensors([_cpu(cpu_c)])
    return state


def _cpu(value_c: float) -> SensorReading:
    return SensorReading(id="cpu", label="Tctl", kind="cpu_temp", value_c=value_c, age_ms=50)


def _hot(state: AppState) -> float:
    """A CPU reading over the limit the wizard actually applies."""
    return thermal_limit_c(state.capabilities) + 10.0


def _wizard(qtbot, state: AppState, client=None) -> FanConfigWizard:
    wizard = FanConfigWizard(state=state, client=client or MagicMock())
    qtbot.addWidget(wizard)
    wizard.show()
    assert wizard.currentId() == PAGE_INTRO, "precondition: the wizard opens on Intro"
    return wizard


def _next(wizard: FanConfigWizard, expected: int) -> None:
    wizard.next()
    assert wizard.currentId() == expected


def _select_only(wizard: FanConfigWizard, *keep: str) -> None:
    for target, cb in zip(wizard._targets, wizard._discovery_page._checkboxes, strict=True):
        cb.setChecked(target["id"] in keep)


def _finish(wizard: FanConfigWizard) -> None:
    assert wizard.currentId() == PAGE_REVIEW
    wizard.button(QWizard.WizardButton.FinishButton).click()


def _aliases(state: AppState) -> dict[str, str]:
    return {f: state.fan_display_name(f) for f in FANS}


# ── Finish ───────────────────────────────────────────────────────────────────


def test_finish_saves_a_label_typed_on_the_review_page(qtbot):
    state = _state()
    wizard = _wizard(qtbot, state)
    _next(wizard, PAGE_DISCOVERY)
    _select_only(wizard)  # nothing selected: the Review page lists every fan
    _next(wizard, PAGE_REVIEW)
    seen: list[dict] = []
    wizard.labels_saved.connect(seen.append)

    wizard._review_page._table.item(0, 2).setText("Rear Exhaust")
    _finish(wizard)

    assert state.fan_display_name("openfan:ch00") == "Rear Exhaust"
    assert seen == [{"openfan:ch00": "Rear Exhaust"}]


def test_finish_does_not_save_a_label_for_a_fan_deselected_after_labelling(qtbot):
    state = _state()
    before = _aliases(state)
    wizard = _wizard(qtbot, state)
    _next(wizard, PAGE_DISCOVERY)
    _select_only(wizard, "openfan:ch00", "openfan:ch01")
    _next(wizard, PAGE_TEST)
    page = wizard._test_page
    page._label_combo.setCurrentText("CPU Cooler")
    page._next_fan_btn.click()  # ch00 labelled, on to ch01
    assert wizard._labels == {"openfan:ch00": "CPU Cooler"}, "precondition: ch00 labelled"

    wizard.back()
    assert wizard.currentId() == PAGE_DISCOVERY
    _select_only(wizard, "openfan:ch01")  # the user changes their mind about ch00
    _next(wizard, PAGE_TEST)
    page._label_combo.setCurrentText("Rear Exhaust")
    page._next_fan_btn.click()
    _next(wizard, PAGE_REVIEW)
    _finish(wizard)

    assert state.fan_display_name("openfan:ch01") == "Rear Exhaust", "the reviewed fan saved"
    assert state.fan_display_name("openfan:ch00") == before["openfan:ch00"]


# ── Identify page ────────────────────────────────────────────────────────────


def test_skip_is_offered_again_after_re_entering_the_identify_page(qtbot):
    wizard = _wizard(qtbot, _state())
    _next(wizard, PAGE_DISCOVERY)
    _select_only(wizard, "openfan:ch00")
    _next(wizard, PAGE_TEST)
    page = wizard._test_page
    page._skip_btn.click()  # the last fan: the pair hides
    assert not page._skip_btn.isVisibleTo(page), "precondition: hidden at the end"

    wizard.back()
    _next(wizard, PAGE_TEST)

    assert page._skip_btn.isVisibleTo(page)
    assert page._next_fan_btn.isVisibleTo(page)


@pytest.mark.parametrize("ending", ["countdown", "abort"])
def test_a_restore_the_daemon_rejected_is_not_reported_as_restored(qtbot, ending):
    client = MagicMock()
    wizard = _wizard(qtbot, _state(), client)
    _next(wizard, PAGE_DISCOVERY)
    _select_only(wizard, "openfan:ch00")
    _next(wizard, PAGE_TEST)
    page = wizard._test_page
    page._test_btn.click()
    assert page._testing, "precondition: the test started"

    client.fan_identify.side_effect = DaemonError(
        code="internal", message="restore refused", status=500
    )
    if ending == "countdown":
        page._seconds_remaining = 1
        page._tick()
    else:
        page._abort_btn.click()

    text = page._status_msg.text()
    assert "restore refused" in text
    assert "did not confirm" in text
    assert "fan restored" not in text.lower()
    assert page._status_msg.property("class") == "CriticalChip"


@pytest.mark.parametrize("ending", ["countdown", "abort"])
def test_a_confirmed_restore_still_says_restored(qtbot, ending):
    wizard = _wizard(qtbot, _state())
    _next(wizard, PAGE_DISCOVERY)
    _select_only(wizard, "openfan:ch00")
    _next(wizard, PAGE_TEST)
    page = wizard._test_page
    page._test_btn.click()
    if ending == "countdown":
        page._seconds_remaining = 1
        page._tick()
    else:
        page._abort_btn.click()
    assert "restored" in page._status_msg.text().lower()
    assert not page._status_msg.property("class")


def test_the_thermal_abort_message_keeps_a_failed_restore(qtbot):
    client = MagicMock()
    state = _state()
    wizard = _wizard(qtbot, state, client)
    _next(wizard, PAGE_DISCOVERY)
    _select_only(wizard, "openfan:ch00")
    _next(wizard, PAGE_TEST)
    page = wizard._test_page
    page._test_btn.click()
    client.fan_identify.side_effect = DaemonError(
        code="internal", message="restore refused", status=500
    )
    state.set_sensors([_cpu(_hot(state))])
    page._tick()
    text = page._status_msg.text()
    assert "ABORTED" in text and "restore refused" in text


def test_a_successful_start_clears_the_refusal_chip(qtbot):
    state = _state()
    wizard = _wizard(qtbot, state)
    _next(wizard, PAGE_DISCOVERY)
    _select_only(wizard, "openfan:ch00")
    _next(wizard, PAGE_TEST)
    page = wizard._test_page
    state.set_sensors([_cpu(_hot(state))])
    page._test_btn.click()
    assert page._status_msg.property("class") == "CriticalChip", "precondition: refused"

    state.set_sensors([_cpu(45.0)])
    page._test_btn.click()

    assert page._testing
    assert not page._status_msg.property("class")
    page._abort_btn.click()


def test_the_status_chip_is_restyled_when_its_class_changes(qtbot):
    """The class alone is not the restyle: Qt re-reads QSS for a shown widget
    only on unpolish/polish. Assert the painted colour moved."""
    red = QColor(200, 0, 0)
    state = _state()
    wizard = _wizard(qtbot, state)
    wizard.setStyleSheet(f".CriticalChip {{ color: {red.name()}; }}")
    _next(wizard, PAGE_DISCOVERY)
    _select_only(wizard, "openfan:ch00")
    _next(wizard, PAGE_TEST)
    page = wizard._test_page
    label = page._status_msg
    QApplication.processEvents()
    assert label.palette().color(QPalette.ColorRole.WindowText) != red, "precondition"

    state.set_sensors([_cpu(_hot(state))])
    page._test_btn.click()

    assert label.palette().color(QPalette.ColorRole.WindowText) == red


# ── Intro page ───────────────────────────────────────────────────────────────


def _intro_status(wizard: FanConfigWizard) -> QLabel:
    return wizard._intro_page._status_label


def _next_enabled(wizard: FanConfigWizard) -> bool:
    return wizard.button(QWizard.WizardButton.NextButton).isEnabled()


def test_the_intro_page_follows_a_daemon_that_connects_after_it_opened(qtbot):
    state = _state(connected=False)
    wizard = _wizard(qtbot, state)
    assert not _next_enabled(wizard), "precondition: no daemon, no Next"
    assert "Cannot proceed" in _intro_status(wizard).text()

    state.set_connection(ConnectionState.CONNECTED)

    assert _next_enabled(wizard)
    assert _intro_status(wizard).text().startswith("Ready")
    assert _intro_status(wizard).property("class") == "SuccessChip"


def test_the_intro_page_follows_a_daemon_that_drops(qtbot):
    state = _state()
    wizard = _wizard(qtbot, state)
    assert _next_enabled(wizard), "precondition"

    state.set_connection(ConnectionState.DISCONNECTED)

    assert not _next_enabled(wizard)
    assert "Daemon is not connected" in _intro_status(wizard).text()
    assert _intro_status(wizard).property("class") == "CriticalChip"


def test_a_hot_cpu_warns_on_the_intro_page_without_blocking(qtbot):
    state = _state()
    state.set_sensors([_cpu(_hot(state))])
    wizard = _wizard(qtbot, state)
    status = _intro_status(wizard)

    assert _next_enabled(wizard), "the heat limit is enforced per test, not here"
    assert "Cannot proceed" not in status.text()
    assert "too high" in status.text()
    assert status.property("class") == "WarningChip"

    state.set_sensors([_cpu(45.0)])  # it cools while the page is open
    assert "too high" not in status.text()
    assert status.property("class") == "SuccessChip"


def test_a_hot_cpu_is_named_alongside_a_blocker(qtbot):
    state = _state(connected=False)
    state.set_sensors([_cpu(_hot(state))])
    wizard = _wizard(qtbot, state)
    text = _intro_status(wizard).text()
    assert "Cannot proceed" in text and "too high" in text
    assert not _next_enabled(wizard)


def test_a_closed_wizard_stops_following_app_state(qtbot):
    state = _state()
    wizard = _wizard(qtbot, state)
    status = _intro_status(wizard)
    before = status.text()
    assert before.startswith("Ready"), "precondition"

    wizard.reject()
    state.set_connection(ConnectionState.DISCONNECTED)

    assert status.text() == before


# ── PWM Test Report ──────────────────────────────────────────────────────────


def _start_verify_run(window) -> None:
    _clear(window)
    _box(window, "verify", CPU).click()
    _btn(window, "PwmReport_Btn_next").click()
    _btn(window, "PwmReport_Btn_next").click()

    window.findChild(QCheckBox, "PwmReport_Check_consent").click()
    _btn(window, "PwmReport_Btn_start").click()


_FAILED_SAVES: list[object] = []


def _failing_save(doc, *_args, **_kwargs):
    _FAILED_SAVES.append(doc.get("report_id"))
    raise OSError("disk full")


def _saved_line(window) -> str:
    label = window.findChild(QLabel, "PwmReport_Label_savedPath")
    assert label is not None
    return label.text()


def test_a_failed_save_stays_on_the_run_status(qtbot, rig, monkeypatch):  # noqa: F811
    window, controller, _st, _daemon, _clock, _settings = rig
    monkeypatch.setattr(store, "save_report", _failing_save)
    _FAILED_SAVES.clear()
    _start_verify_run(window)
    assert controller.is_running(), "precondition: the run started"
    assert _FAILED_SAVES, "precondition: a save was attempted and failed"

    status = window.findChild(QLabel, "PwmReport_Label_runStatus").text()
    assert "could not be saved: disk full" in status
    controller.cancel()
    _run_to_end(qtbot, controller, _clock)


def test_a_report_whose_saves_failed_does_not_claim_the_last_runs_file(
    qtbot,
    rig,  # noqa: F811
    monkeypatch,
):
    window, controller, _st, _daemon, clock, _settings = rig
    _start_verify_run(window)
    _run_to_end(qtbot, controller, clock)
    assert window.current_page() == PAGE_REPORT
    first = controller.last_path
    assert first is not None and _saved_line(window) == f"Saved to {first}", "precondition"

    monkeypatch.setattr(store, "save_report", _failing_save)
    _btn(window, "PwmReport_Btn_new").click()
    _start_verify_run(window)
    assert controller.last_path is None, "a new run has saved nothing yet"
    _run_to_end(qtbot, controller, clock)
    assert window.current_page() == PAGE_REPORT

    line = _saved_line(window)
    assert str(first) not in line
    assert "could not be saved: disk full" in line


def test_a_failed_final_save_does_not_say_saved_to_the_stale_checkpoint(
    qtbot,
    rig,  # noqa: F811
    monkeypatch,
):
    window, controller, _st, _daemon, clock, _settings = rig
    real_save = store.save_report
    _start_verify_run(window)
    checkpoint = controller.last_path
    assert checkpoint is not None, "precondition: an early checkpoint was written"

    monkeypatch.setattr(store, "save_report", _failing_save)
    _run_to_end(qtbot, controller, clock)
    assert window.current_page() == PAGE_REPORT

    line = _saved_line(window)
    assert not line.startswith("Saved to")
    assert "could not be saved: disk full" in line
    assert f"an earlier copy is at {checkpoint}" in line

    # A later successful save clears the error (the store is writable again).
    monkeypatch.setattr(store, "save_report", real_save)
    controller._checkpoint(force=True)
    assert controller.last_save_error is None
