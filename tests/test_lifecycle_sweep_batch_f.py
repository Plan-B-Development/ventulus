"""GUI audit 2026-10-14, batch F: one-shot dialogs and menus are deleted after
use, and an open Sensor Detail follows the poll.

A dialog or menu parented to a page and run with ``exec()`` lived as long as the
page, i.e. the whole session, so each open left a hidden copy behind. The
leaked Alert Centre kept rebuilding itself on every ``warnings_changed``.

Each site test drives the real entry point (a button, an action, a signal) and
then flushes ``DeferredDelete``, as the event loop would on return.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
import shiboken6
from PySide6.QtCore import QEvent, QPoint, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QWidget

from ventulus.api.models import ConnectionState, Freshness, SensorReading
from ventulus.services.diagnostics_service import DiagnosticsService

_UI = pathlib.Path(__file__).resolve().parent.parent / "src" / "ventulus" / "ui"


def _flush() -> None:
    QApplication.instance().sendPostedEvents(None, QEvent.Type.DeferredDelete)


def _close_popup_soon() -> None:
    """Close the menu that ``exec()`` is about to show, so the test does not
    block on it (patching ``QMenu.exec`` does not intercept PySide6's call)."""

    def close() -> None:
        popup = QApplication.activePopupWidget()
        if popup is not None:
            popup.close()

    QTimer.singleShot(0, close)


# ── The rule: every exec() under ui/ disposes of what it ran ────────────────

#: The only ``.exec()`` calls allowed outside the helpers, keyed (file, receiver).
_EXEMPT = {
    ("components/transient.py", "dialog"): "the helper itself",
    ("components/transient.py", "menu"): "the helper itself",
    ("widgets/reorderable_flow.py", "drag"): "Qt deletes a QDrag itself when the drag ends",
    ("widgets/openfan_firmware_dialog.py", "drag"): "Qt deletes a QDrag itself when the drag ends",
}


def _exec_calls() -> list[tuple[str, str, int]]:
    calls = []
    for path in sorted(_UI.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("exec", "exec_")
            ):
                calls.append(
                    (path.relative_to(_UI).as_posix(), ast.unparse(node.func.value), node.lineno)
                )
    return calls


def test_every_exec_under_ui_goes_through_a_disposing_helper():
    calls = _exec_calls()
    assert calls, "the sweep found no exec() at all; it is not looking at ui/"
    bare = [c for c in calls if (c[0], c[1]) not in _EXEMPT]
    assert bare == [], (
        "run a one-shot dialog or menu with exec_dialog / exec_menu "
        "(ui/components/transient.py), or it outlives its use: " + repr(bare)
    )


def test_every_exemption_is_still_a_real_call():
    seen = {(f, r) for f, r, _ in _exec_calls()}
    assert set(_EXEMPT) - seen == set()


# ── The helpers ─────────────────────────────────────────────────────────────


class _Answering(QDialog):
    def exec(self) -> int:
        return QDialog.DialogCode.Accepted


class _Raising(QDialog):
    def exec(self) -> int:
        raise RuntimeError("boom")


def test_exec_dialog_returns_the_result_and_the_dialog_outlives_the_call(qtbot):
    from ventulus.ui.components.transient import exec_dialog

    parent = QWidget()
    qtbot.addWidget(parent)
    dialog = _Answering(parent)
    dialog.setObjectName("probe")
    assert exec_dialog(dialog) == QDialog.DialogCode.Accepted
    # The caller reads the outcome after exec() returns: still valid here.
    assert dialog.objectName() == "probe"
    _flush()
    assert not shiboken6.isValid(dialog)
    assert parent.findChildren(QDialog) == []


def test_exec_dialog_deletes_even_when_exec_raises(qtbot):
    from ventulus.ui.components.transient import exec_dialog

    parent = QWidget()
    qtbot.addWidget(parent)
    dialog = _Raising(parent)
    with pytest.raises(RuntimeError):
        exec_dialog(dialog)
    _flush()
    assert parent.findChildren(QDialog) == []


def test_exec_menu_deletes_the_menu(qtbot):
    from ventulus.ui.components.transient import exec_menu

    parent = QWidget()
    qtbot.addWidget(parent)
    menu = QMenu(parent)
    menu.addAction("x")
    _close_popup_soon()
    exec_menu(menu, QPoint(0, 0))
    assert parent.findChildren(QMenu) == [menu], "still there until the event loop runs"
    _flush()
    assert parent.findChildren(QMenu) == []


# ── The sites ───────────────────────────────────────────────────────────────


def test_alert_centre_leaves_nothing_behind(qtbot, app_state):
    from ventulus.ui.pages.logs_page import LogsPage
    from ventulus.ui.widgets.alert_center_dialog import AlertCenterDialog

    page = LogsPage(diagnostics_service=DiagnosticsService(), state=app_state)
    qtbot.addWidget(page)
    for _ in range(3):
        page.open_alert_center()
    _flush()
    assert page.findChildren(AlertCenterDialog) == []


def test_about_leaves_nothing_behind(qtbot):
    from ventulus.ui.about_dialog import AboutDialog
    from ventulus.ui.sidebar import Sidebar

    sidebar = Sidebar()
    qtbot.addWidget(sidebar)
    sidebar._about_btn.click()
    _flush()
    assert sidebar.findChildren(AboutDialog) == []


def test_fan_wizard_leaves_nothing_behind(qtbot, app_state, profile_service):
    from ventulus.ui.pages.controls_page import ControlsPage
    from ventulus.ui.widgets.fan_wizard import FanConfigWizard

    page = ControlsPage(state=app_state, profile_service=profile_service)
    qtbot.addWidget(page)
    page._wizard_action.trigger()
    _flush()
    assert page.findChildren(FanConfigWizard) == []


def test_hardware_role_dialog_leaves_nothing_behind(qtbot, monkeypatch):
    from tests.test_header_role_picker import _hdr, _role_btn, hw_mod
    from tests.test_header_role_picker import _page as _role_page
    from ventulus.ui.widgets.header_role_dialog import HeaderRoleDialog

    page, _state, client = _role_page(qtbot, monkeypatch, [_hdr()])
    # The real dialog this time; the suite's exec() stub cancels it.
    monkeypatch.setattr(hw_mod, "HeaderRoleDialog", HeaderRoleDialog)
    _role_btn(page, _hdr().id).click()
    assert client.calls == [], "cancelled, so nothing was sent"
    _flush()
    assert page.findChildren(HeaderRoleDialog) == []


def test_fan_card_context_menu_leaves_nothing_behind(qtbot):
    from tests.test_fan_inline_rename import TestFanCardRename
    from ventulus.ui.widgets.fan_control_card import FanControlCard

    card = FanControlCard(TestFanCardRename()._vm())
    qtbot.addWidget(card)
    assert card.build_rename_menu() is not None, "precondition: this card has a menu"
    _flush()
    before = len(card.findChildren(QMenu))
    _close_popup_soon()
    card.customContextMenuRequested.emit(QPoint(4, 4))
    _flush()
    assert len(card.findChildren(QMenu)) == before


def test_manage_profiles_menu_leaves_nothing_behind(qtbot, app_state, profile_service):
    from PySide6.QtWidgets import QPushButton

    from ventulus.ui.pages.controls_page import ControlsPage

    page = ControlsPage(state=app_state, profile_service=profile_service)
    qtbot.addWidget(page)
    btn = page.findChild(QPushButton, "Controls_Btn_manageProfiles")
    before = len(page.findChildren(QMenu))  # the Setup button's menu is permanent
    _close_popup_soon()
    btn.click()
    _flush()
    assert len(page.findChildren(QMenu)) == before


# ── Sensor Detail ───────────────────────────────────────────────────────────


def _sensor(value_c: float = 45.0, sid: str = "hwmon:k10temp:Tctl") -> SensorReading:
    return SensorReading(
        id=sid,
        kind="cpu_temp",
        label="Tctl",
        value_c=value_c,
        chip_name="k10temp",
        source="hwmon",
        age_ms=500,
    )


def _overview(qtbot, app_state):
    from ventulus.ui.pages.overview_page import OverviewPage

    page = OverviewPage(state=app_state, diagnostics_service=DiagnosticsService(app_state))
    qtbot.addWidget(page)
    app_state.set_sensors([_sensor()])
    page._sensor_table.cellDoubleClicked.emit(0, 0)
    dialog = page._sensor_detail_dialog
    assert dialog is not None, "precondition: the double-click opened it"
    return page, dialog


def test_closing_sensor_detail_deletes_it(qtbot, app_state):
    from ventulus.ui.widgets.sensor_detail_dialog import SensorDetailDialog

    page, dialog = _overview(qtbot, app_state)
    dialog.reject()
    _flush()
    assert page._sensor_detail_dialog is None
    assert page.findChildren(SensorDetailDialog) == []


def test_open_sensor_detail_follows_the_poll(qtbot, app_state):
    page, dialog = _overview(qtbot, app_state)
    assert "45.0 °C" in dialog._live.text()
    report = dialog._browser.toHtml()
    app_state.set_sensors([_sensor(61.0)])
    assert "61.0 °C" in dialog._live.text()
    assert "45.0 °C" not in dialog._live.text()
    # Only the strip re-renders, so the report's scroll and selection survive.
    assert dialog._browser.toHtml() == report
    # The binding keeps the page, and so its poll connections, alive (DEC-356).
    assert page._sensor_detail_dialog is dialog


def test_sensor_detail_says_when_the_sensor_is_gone(qtbot, app_state):
    page, dialog = _overview(qtbot, app_state)
    app_state.set_sensors([_sensor(sid="hwmon:k10temp:Tccd1")])
    assert "No current reading" in dialog._live.text()
    assert "45.0 °C" not in dialog._live.text()
    assert page._sensor_detail_dialog is dialog


def test_sensor_detail_freshness_follows_the_connection(qtbot, app_state):
    page, dialog = _overview(qtbot, app_state)
    assert f">{Freshness.FRESH.value}<" in dialog._live.text()
    app_state.set_connection(ConnectionState.DISCONNECTED)
    shown = app_state.display_freshness(_sensor())
    assert shown is not Freshness.FRESH, "precondition: disconnected is never fresh"
    assert f">{shown.value}<" in dialog._live.text()
    assert page._sensor_detail_dialog is dialog
