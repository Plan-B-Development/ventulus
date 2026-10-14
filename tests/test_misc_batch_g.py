"""GUI audit 2026-10-14, batch G: the remaining P3s, plus G-18, G-19, G-20 and the
modal-dialog activation race Batch A left open.

Each test drives the real signal, click or call site and asserts the arm the
pre-fix code could not produce, with the opposite branch beside it:

- Logs: Clear Logs leaves no time-filter label; Follow is unchecked while paused,
  so one click resumes; the support bundle is finished off the GUI thread and
  its outcome reaches the window banner; "Open Hardware" opens Hardware.
- Shell: demo names the profile it runs; a reconnect re-shows a refused Apply's
  reason; a pre-2.0 daemon gets no Apply or Stop (DEC-165); the upgrade and
  GUI-floor banners name the daemon now running (G-18).
- Dashboard/Overview: a cleared hwmon/OpenFan fault leaves its chip on the next
  poll; Dismiss on a capabilities banner holds until its message changes; the
  hidden-sensors row toggles on a click and on Enter.
- Rail and chart: per-poll value updates reach no ``itemChanged`` (G-19); the plot
  is out of the Tab order and named, and every series row's menu can change its
  colour (G-20).
- Settings: a demo-sealed reset says it did not happen.
- Hardware: the OpenFan outcome line expires with its role; removing a user pump
  role from a header the daemon still infers a pump from asks nothing.
- Controls: linked cards follow role edits; a curve rename keeps held overrides;
  the open editor's floor follows its roles; a dialog whose profile was replaced
  while it was open applies nothing.
"""

from __future__ import annotations

import threading
from typing import ClassVar
from unittest.mock import Mock

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QInputDialog, QMessageBox, QPushButton

from tests.test_header_role_picker import LABEL_PUMP, USER_PUMP, _hdr, _role_btn
from tests.test_header_role_picker import _caps as _picker_caps
from tests.test_header_role_picker import _page as _picker_page
from tests.test_header_role_picker import _StubDialog as _PickerDialog
from tests.test_openfan_roles import CH0, _role
from tests.test_openfan_roles import _btn as _openfan_btn
from tests.test_openfan_roles import _outcome as _openfan_outcome
from tests.test_openfan_roles import _page as _openfan_page
from tests.test_openfan_roles import _StubDialog as _OpenFanDialog
from ventulus.api.models import (
    Capabilities,
    ConnectionState,
    ControlCapability,
    DaemonStatus,
    FanReading,
    HwmonCapability,
    OpenfanCapability,
    SensorReading,
    SubsystemStatus,
)
from ventulus.constants import EXPECTED_API_VERSION, PAGE_HARDWARE
from ventulus.services.app_state import AppState
from ventulus.services.dashboard_view import build_capabilities_vm
from ventulus.services.diagnostics_service import DiagnosticsService
from ventulus.services.header_role_writes import apply_role_writes
from ventulus.services.history_store import HistoryStore
from ventulus.services.logs_view import build_log_rows
from ventulus.services.profile_service import (
    ControlMode,
    CurveConfig,
    CurvePoint,
    CurveType,
    LogicalControl,
    Profile,
    ProfileService,
)
from ventulus.services.series_selection import SeriesSelectionModel
from ventulus.ui.main_window import MainWindow
from ventulus.ui.pages.controls_page import ControlsPage
from ventulus.ui.pages.logs_page import LogsPage
from ventulus.ui.pages.settings_page import SettingsPage
from ventulus.ui.widgets.fan_role_dialog import FanRoleDialog
from ventulus.ui.widgets.sensor_series_panel import SensorSeriesPanel
from ventulus.ui.widgets.timeline_chart import TimelineChart

NOT_SAVED = SettingsPage._SEALED_RESET_STATUS


@pytest.fixture()
def window(qtbot, app_state, profile_service, settings_service):
    win = MainWindow(
        state=app_state,
        profile_service=profile_service,
        settings_service=settings_service,
        demo_mode=False,
    )
    qtbot.addWidget(win)
    return win


def _banner_text(win: MainWindow) -> str:
    return win.error_banner._message_label.text()


# ── Logs ───────────────────────────────────────────────────────────────────


def _logs(qtbot) -> tuple[LogsPage, DiagnosticsService]:
    state = AppState()
    state.set_connection(ConnectionState.CONNECTED)
    diag = DiagnosticsService(state)
    page = LogsPage(diagnostics_service=diag)
    qtbot.addWidget(page)
    return page, diag


class TestLogsTimeFilter:
    def test_clearing_the_logs_drops_the_filter_label(self, qtbot):
        page, diag = _logs(qtbot)
        for i in range(6):
            diag.log_event("info", "gui", f"event {i}")
        # Distinct times, so the events land in different buckets.
        for i, ev in enumerate(diag._events):
            ev.timestamp = 1_000_000.0 + i * 60
        page._all_rows.clear()
        page._all_rows.extend(build_log_rows(diag.events))
        page._refresh_view()
        populated = [i for i, b in enumerate(page._histogram.buckets()) if b.total]
        page._on_bucket_clicked(populated[0])
        assert page._clear_window_btn.isVisibleTo(page), "precondition: a filter is applied"
        assert page._window_label.text() != "All retained events"

        diag.clear_events()  # Clear Logs

        assert page._window is None
        assert page._window_label.text() == "All retained events"
        assert not page._clear_window_btn.isVisibleTo(page)


def _scrollable_logs(qtbot):
    page, diag = _logs(qtbot)
    page.resize(900, 500)
    page.show()
    qtbot.waitExposed(page)
    for i in range(120):
        diag.log_event("info", "gui", f"event {i}")
    QApplication.processEvents()
    bar = page._table.verticalScrollBar()
    assert bar.maximum() > 0, "precondition: the list must actually be scrollable"
    return page, diag, bar


class TestLogsFollow:
    def test_a_pause_by_scrolling_unchecks_follow_and_one_click_resumes(self, qtbot):
        page, _diag, bar = _scrollable_logs(qtbot)
        assert page._follow_btn.isChecked() and page._is_following(), "precondition"

        bar.setValue(bar.maximum())

        assert not page._follow_btn.isChecked(), "a paused Follow must not read as checked"
        assert page._follow_btn.text() == "○ Follow paused"
        page._follow_btn.click()
        assert page._follow_btn.isChecked() and page._is_following()
        assert bar.value() == bar.minimum()

    def test_scrolling_back_to_the_tail_resumes_a_scroll_pause(self, qtbot):
        page, _diag, bar = _scrollable_logs(qtbot)
        bar.setValue(bar.maximum())
        assert not page._follow_btn.isChecked(), "precondition"
        bar.setValue(bar.minimum())
        assert page._follow_btn.isChecked() and page._is_following()

    def test_a_pause_the_user_made_survives_scrolling_back(self, qtbot):
        page, _diag, bar = _scrollable_logs(qtbot)
        page._follow_btn.click()  # the user pauses at the tail
        assert not page._follow_btn.isChecked(), "precondition"
        bar.setValue(bar.maximum())
        bar.setValue(bar.minimum())
        assert not page._follow_btn.isChecked()
        assert not page._is_following()


def _quick_collectors(monkeypatch, diag) -> list[threading.Thread]:
    """Stand in for lsmod and journalctl, recording the thread each runs on."""
    seen: list[threading.Thread] = []

    def journal():
        seen.append(threading.current_thread())
        return "journal line"

    monkeypatch.setattr(diag, "fetch_journal_entries", journal)
    monkeypatch.setattr(DiagnosticsService, "collect_kernel_modules", staticmethod(lambda: "mods"))
    monkeypatch.setattr(DiagnosticsService, "fetch_kernel_log_amdgpu", staticmethod(lambda: ""))
    return seen


def _save_to(monkeypatch, path) -> None:
    monkeypatch.setattr(
        "ventulus.ui.pages.logs_page.QFileDialog.getSaveFileName", lambda *a, **k: (str(path), "")
    )


class TestSupportBundleExport:
    def test_the_slow_half_runs_off_the_gui_thread_and_the_outcome_is_reported(
        self, qtbot, monkeypatch, tmp_path
    ):
        page, diag = _logs(qtbot)
        target = tmp_path / "bundle.json"
        _save_to(monkeypatch, target)
        threads = _quick_collectors(monkeypatch, diag)

        with qtbot.waitSignal(page.bundle_export_finished, timeout=5000) as sig:
            page.export_bundle()
        page.cleanup()

        assert sig.args == [True, f"Support bundle saved to {target}"]
        assert target.exists() and '"journal": "journal line"' in target.read_text()
        assert threads and threads[0] is not threading.main_thread()
        assert any(f"saved to {target}" in e.message for e in diag.events)

    def test_a_failed_write_is_reported(self, qtbot, monkeypatch, tmp_path):
        page, diag = _logs(qtbot)
        _save_to(monkeypatch, tmp_path / "b.json")
        _quick_collectors(monkeypatch, diag)

        def boom(*_a, **_k):
            raise OSError("disk full")

        monkeypatch.setattr("ventulus.paths.atomic_write", boom)
        with qtbot.waitSignal(page.bundle_export_finished, timeout=5000) as sig:
            page.export_bundle()
        page.cleanup()

        assert sig.args == [False, "Support bundle export failed: disk full"]
        assert any("export failed: disk full" in e.message for e in diag.events)

    def test_the_window_banner_shows_the_outcome(self, window):
        window.logs_page.bundle_export_finished.emit(True, "Support bundle saved to /x.json")
        assert not window.error_banner.isHidden()
        assert _banner_text(window) == "Support bundle saved to /x.json"
        window.logs_page.bundle_export_finished.emit(False, "Support bundle export failed: no")
        assert _banner_text(window) == "Support bundle export failed: no"
        assert not window.error_banner._auto_dismiss_timer.isActive(), "a failure stays up"

    def test_a_success_leaves_a_warning_already_up(self, window, app_state):
        app_state.set_connection(ConnectionState.DISCONNECTED)
        assert _banner_text(window) == MainWindow.DISCONNECTED_MESSAGE, "precondition"
        window.logs_page.bundle_export_finished.emit(True, "Support bundle saved to /x.json")
        assert _banner_text(window) == MainWindow.DISCONNECTED_MESSAGE
        assert not window.error_banner._auto_dismiss_timer.isActive()


def test_open_hardware_opens_the_hardware_page(qtbot):
    page, diag = _logs(qtbot)
    diag.log_event("error", "hwmon", "rescan failed")
    page._table.selectRow(0)
    assert page._action_btn.text() == "Open Hardware", "precondition"
    with qtbot.waitSignal(page.navigate_requested, timeout=500) as sig:
        page._action_btn.click()
    assert sig.args == [PAGE_HARDWARE]


# ── Shell ──────────────────────────────────────────────────────────────────


def test_demo_names_the_profile_it_runs(qtbot, app_state, profile_service, settings_service):
    active = profile_service.active_profile
    assert active is not None and active.name, "precondition: demo has a profile to run"
    win = MainWindow(
        state=app_state,
        profile_service=profile_service,
        settings_service=settings_service,
        demo_mode=True,
    )
    qtbot.addWidget(win)
    assert app_state.active_profile_name == active.name


class TestReconnectBanner:
    REFUSAL = "Could not activate “Quiet”: curve 'c1' has no points"

    def test_a_refused_apply_comes_back_after_a_blip(self, window, app_state):
        window._show_activation_failure(self.REFUSAL)
        app_state.set_connection(ConnectionState.DISCONNECTED)
        assert _banner_text(window) == MainWindow.DISCONNECTED_MESSAGE, "precondition"

        app_state.set_connection(ConnectionState.CONNECTED)

        assert not window.error_banner.isHidden()
        assert _banner_text(window) == self.REFUSAL

    def test_a_refusal_the_user_dismissed_stays_down(self, window, app_state):
        window._show_activation_failure(self.REFUSAL)
        window.error_banner.findChild(QPushButton, "ErrorBanner_Btn_dismiss").click()
        app_state.set_connection(ConnectionState.DISCONNECTED)
        app_state.set_connection(ConnectionState.CONNECTED)
        assert _banner_text(window) == "Connected to daemon"

    def test_a_refusal_overtaken_by_the_daemon_is_not_brought_back(self, window, app_state):
        """The refused profile ran after all (a timeout that landed) or another
        client changed what runs: the old refusal no longer describes the daemon."""
        window._show_activation_failure(self.REFUSAL)
        app_state.set_active_profile_id("quiet")
        app_state.set_connection(ConnectionState.DISCONNECTED)
        app_state.set_connection(ConnectionState.CONNECTED)
        assert _banner_text(window) == "Connected to daemon"

    def test_with_nothing_pending_a_reconnect_says_connected(self, window, app_state):
        app_state.set_connection(ConnectionState.DISCONNECTED)
        app_state.set_connection(ConnectionState.CONNECTED)
        assert _banner_text(window) == "Connected to daemon"

    def test_connected_does_not_replace_another_message(self, window, app_state):
        app_state.set_connection(ConnectionState.DISCONNECTED)
        window.error_banner.show_warning("Could not stop profile control: busy")
        app_state.set_connection(ConnectionState.CONNECTED)
        assert _banner_text(window) == "Could not stop profile control: busy"


def _legacy_caps(version: str) -> Capabilities:
    return Capabilities(
        daemon_version=version,
        control=ControlCapability(autonomous_control=False, min_supported_gui="2.0.0"),
    )


def _autonomous_caps(floor: str = "2.0.0") -> Capabilities:
    return Capabilities(
        daemon_version="5.0.0",
        control=ControlCapability(autonomous_control=True, min_supported_gui=floor),
    )


class TestPre20DaemonGate:
    def test_apply_and_stop_are_off_and_the_service_refuses(
        self, window, app_state, profile_service
    ):
        client = Mock()
        window._client = client
        profile = profile_service.create_profile("Quiet")
        profile_service.set_active(profile.id)
        app_state.set_capabilities(_autonomous_caps())
        assert window.sidebar.apply_profile_btn.isEnabled(), "precondition"
        assert window.sidebar.stop_profile_btn.isEnabled(), "precondition"
        assert window.dashboard_page._apply_btn.isEnabled(), "precondition"

        app_state.set_capabilities(_legacy_caps("1.21.0"))

        assert not window.sidebar.apply_profile_btn.isEnabled()
        assert not window.sidebar.stop_profile_btn.isEnabled()
        assert not window.dashboard_page._apply_btn.isEnabled()
        reason = profile_service.control_blocked_reason
        assert reason and "1.21.0" in reason
        assert window.sidebar.apply_profile_btn.toolTip() == reason

        activated = profile_service.activate(profile.id, client=client)
        stopped = profile_service.deactivate(client=client)
        assert not activated.activated and activated.error == reason
        assert not stopped.deactivated and stopped.error == reason
        client.activate_profile.assert_not_called()
        client.deactivate_profile.assert_not_called()

    def test_an_upgrade_gives_control_back(self, window, app_state, profile_service):
        profile_service.set_active(profile_service.create_profile("Quiet").id)
        app_state.set_capabilities(_legacy_caps("1.21.0"))
        assert not window.sidebar.apply_profile_btn.isEnabled(), "precondition"

        app_state.set_capabilities(_autonomous_caps())

        assert profile_service.control_blocked_reason is None
        assert window.sidebar.apply_profile_btn.isEnabled()
        assert window.sidebar.stop_profile_btn.isEnabled()
        assert window.dashboard_page._apply_btn.isEnabled()

    def test_the_banner_names_the_daemon_now_running(self, window, app_state):
        """G-18: an engaged gate kept the first daemon's version for good."""
        app_state.set_capabilities(_legacy_caps("1.21.0"))
        assert "1.21.0" in window._gate_banner.text(), "precondition"
        app_state.set_capabilities(_legacy_caps("1.22.0"))
        assert "1.22.0" in window._gate_banner.text()
        assert "1.21.0" not in window._gate_banner.text()

    def test_the_refusal_names_the_daemon_now_running(self, window, app_state, profile_service):
        app_state.set_capabilities(_legacy_caps("1.21.0"))
        app_state.set_capabilities(_legacy_caps("1.22.0"))
        assert "1.22.0" in profile_service.control_blocked_reason
        assert window.sidebar.apply_profile_btn.toolTip() == profile_service.control_blocked_reason

    def test_the_banner_no_longer_claims_the_daemon_drives_the_fans(self, window, app_state):
        app_state.set_capabilities(_legacy_caps("1.21.0"))
        assert "Apply, Stop and Manual are off" in window._gate_banner.text()
        assert "built-in engine" not in window._gate_banner.text()


def test_the_gui_floor_banner_quotes_the_floor_declared_now(window, app_state):
    """G-18: the GUI-floor banner kept the first floor it was shown with."""
    app_state.set_capabilities(_autonomous_caps(floor="98.0.0"))
    assert "98.0.0" in window._gui_floor_banner.text(), "precondition"
    app_state.set_capabilities(_autonomous_caps(floor="99.0.0"))
    assert "99.0.0" in window._gui_floor_banner.text()


# ── Dashboard ──────────────────────────────────────────────────────────────


def _status(**subsystems: str) -> DaemonStatus:
    return DaemonStatus(
        overall_status="ok",
        subsystems=[
            SubsystemStatus(name=name, status=st, reason="link lost" if st != "ok" else "")
            for name, st in subsystems.items()
        ],
    )


class TestSubsystemChips:
    CAPS = Capabilities(
        daemon_version="5.0.0",
        api_version=EXPECTED_API_VERSION,
        openfan=OpenfanCapability(present=True, channels=6),
        hwmon=HwmonCapability(present=True, pwm_header_count=4),
    )

    @pytest.mark.parametrize("name", ["hwmon", "openfan"])
    def test_a_cleared_fault_leaves_the_chip_on_the_next_poll(self, window, app_state, name):
        dash = window.dashboard_page
        label = dash._sub_hwmon_label if name == "hwmon" else dash._sub_openfan_label
        app_state.set_capabilities(self.CAPS)
        healthy = getattr(build_capabilities_vm(self.CAPS), name).text
        app_state.set_status(_status(**{name: "warn"}))
        assert "link lost" in label.text(), "precondition: the fault is shown"

        app_state.set_status(_status(**{name: "ok"}))

        assert label.text() == healthy
        assert label.property("class") != "WarningChip"


def _dismiss(banner) -> None:
    banner.findChild(QPushButton, "ErrorBanner_Btn_dismiss").click()


class TestCapabilitiesBannerDismiss:
    def test_a_dismissed_hwmon_banner_stays_down_until_its_message_changes(self, window, app_state):
        banner = window.dashboard_page._hwmon_banner
        absent = Capabilities(daemon_version="5.0.0", api_version=EXPECTED_API_VERSION)
        app_state.set_capabilities(absent)
        message = build_capabilities_vm(absent).hwmon_banner
        assert message is not None and not banner.isHidden(), "precondition: a banner"
        _dismiss(banner)

        app_state.set_capabilities(absent)  # the 300 s refresh
        assert banner.isHidden()

        changed = Capabilities(
            daemon_version="5.0.0",
            api_version=EXPECTED_API_VERSION,
            hwmon=HwmonCapability(present=True, pwm_header_count=2, write_support=False),
        )
        new_message = build_capabilities_vm(changed).hwmon_banner
        assert new_message is not None and new_message.message != message.message, "precondition"
        app_state.set_capabilities(changed)
        assert not banner.isHidden()

    def test_a_dismissed_api_skew_banner_stays_down_but_stays_an_alert(self, window, app_state):
        banner = window.dashboard_page._api_version_banner
        skew = Capabilities(daemon_version="5.0.0", api_version=EXPECTED_API_VERSION + 1)
        app_state.set_capabilities(skew)
        assert not banner.isHidden(), "precondition"
        _dismiss(banner)
        app_state.set_capabilities(skew)
        assert banner.isHidden()
        assert "api_version_skew" in {w.get("_key") for w in app_state._external_warnings}


# ── Overview ───────────────────────────────────────────────────────────────


def _overview(qtbot):
    from tests.test_overview_page import _page, _sensor, _settings

    page, _state = _page(qtbot, settings=_settings())
    page._on_sensors([_sensor(sid="a"), _sensor(sid="b")])
    page._set_sensor_hidden("a", True)
    assert page._is_hidden_toggle_row(1), "precondition: row 1 is the toggle row"
    assert page._sensor_table.rowCount() == 2
    return page


class TestHiddenSensorsRow:
    def test_one_click_expands_it(self, qtbot):
        page = _overview(qtbot)
        page._sensor_table.cellClicked.emit(1, 0)
        assert page._hidden_group_expanded
        assert page._sensor_table.rowCount() == 3

    def test_enter_expands_it(self, qtbot):
        page = _overview(qtbot)
        page._sensor_table.return_pressed.emit(1)
        assert page._hidden_group_expanded

    def test_a_double_click_does_not_toggle_it_twice(self, qtbot):
        page = _overview(qtbot)
        page._sensor_table.cellClicked.emit(1, 0)  # a double-click's first click
        page._sensor_table.cellDoubleClicked.emit(1, 0)
        assert page._hidden_group_expanded


# ── Rail and chart ─────────────────────────────────────────────────────────


def _rail_sensor(value: float) -> SensorReading:
    return SensorReading(
        id="hwmon:k10temp:Tctl", kind="cpu_temp", label="Tctl", value_c=value, age_ms=100
    )


class _Chart:
    def color_for_key(self, _key: str) -> str:
        return "#336699"

    def set_series_color(self, _key: str, _hex: str) -> None:
        pass


def _rail(qtbot) -> tuple[SensorSeriesPanel, SeriesSelectionModel]:
    selection = SeriesSelectionModel()
    state = AppState()
    panel = SensorSeriesPanel(selection, state=state)
    qtbot.addWidget(panel)
    panel.set_chart(_Chart())
    panel.update_sensors([_rail_sensor(50.0)])
    panel.update_fans([FanReading(id="openfan:ch00", source="openfan", rpm=900)])
    return panel, selection


class TestRailPollUpdates:
    def test_a_poll_reaches_no_item_changed(self, qtbot):
        """G-19: the column-0 tooltip was rewritten every poll outside
        block_signals, so every sensor's visibility was re-applied each second."""
        panel, _selection = _rail(qtbot)
        changed: list[int] = []
        panel._tree.itemChanged.connect(lambda _item, col: changed.append(col))

        panel.update_sensors([_rail_sensor(51.0)])
        panel.update_fans([FanReading(id="openfan:ch00", source="openfan", rpm=950)])

        assert panel._sensor_items["hwmon:k10temp:Tctl"].text(1).startswith("51.0"), (
            "precondition: the poll did update the row"
        )
        assert changed == []

    def test_a_user_tick_still_reaches_the_selection(self, qtbot):
        panel, selection = _rail(qtbot)
        item = panel._sensor_items["hwmon:k10temp:Tctl"]
        item.setCheckState(0, Qt.CheckState.Unchecked)
        assert selection.is_hidden(item.data(0, Qt.ItemDataRole.UserRole))


class TestChartKeyboardAccess:
    def test_the_plot_is_named_and_not_a_tab_stop(self, qtbot):
        chart = TimelineChart(HistoryStore(), selection=SeriesSelectionModel())
        qtbot.addWidget(chart)
        plot = chart._plot_widget
        assert plot.focusPolicy() == Qt.FocusPolicy.NoFocus
        assert plot.accessibleName()
        chart.cleanup()

    def test_every_series_row_can_change_its_colour_from_the_menu(self, qtbot, monkeypatch):
        panel, _selection = _rail(qtbot)
        picked: list[object] = []
        monkeypatch.setattr(panel, "pick_series_color", picked.append)
        for item in (panel._sensor_items["hwmon:k10temp:Tctl"], panel._fan_items["openfan:ch00"]):
            menu = panel.build_row_menu(item)
            action = next(
                a
                for a in menu.actions()
                if a.objectName() == "SensorSeriesPanel_Action_changeColour"
            )
            action.trigger()
            assert picked[-1] is item

    def test_a_group_row_offers_no_colour(self, qtbot):
        panel, _selection = _rail(qtbot)
        group = next(iter(panel._group_items.values()))
        assert panel.build_row_menu(group) is None

    @pytest.mark.parametrize(
        ("key", "modifier"),
        [
            (Qt.Key.Key_Menu, Qt.KeyboardModifier.NoModifier),
            (Qt.Key.Key_F10, Qt.KeyboardModifier.ShiftModifier),
        ],
        ids=["menu-key", "shift-f10"],
    )
    def test_the_keyboard_opens_the_current_rows_menu(self, qtbot, monkeypatch, key, modifier):
        from PySide6.QtTest import QTest

        panel, _selection = _rail(qtbot)
        panel.show()
        qtbot.waitExposed(panel)
        item = panel._sensor_items["hwmon:k10temp:Tctl"]
        panel._tree.setCurrentItem(item)
        seen: list[object] = []
        monkeypatch.setattr(panel, "build_row_menu", lambda it: seen.append(it))

        QTest.keyClick(panel._tree, key, modifier)

        assert seen == [item]


# ── Settings in demo ───────────────────────────────────────────────────────


@pytest.fixture()
def settings_page(qapp, app_state, settings_service):
    page = SettingsPage(
        state=app_state, settings_service=settings_service, series_selection=SeriesSelectionModel()
    )
    return page, settings_service


class TestSealedResets:
    CASES: ClassVar = [
        ("series_colors", {"sensor:a": "#ff0000"}, "_reset_colors_btn"),
        ("controls_card_sizes", {"lc1": [300, 200]}, "_reset_card_sizes_btn"),
        ("chart_series_seeded", True, "_reseed_series_btn"),
    ]

    @pytest.mark.parametrize(("key", "value", "button"), CASES)
    def test_in_demo_a_reset_says_it_was_not_saved(self, settings_page, key, value, button):
        page, svc = settings_page
        svc.update(**{key: value})
        svc.make_ephemeral("demo mode")
        page._refresh_reset_buttons()
        getattr(page, button).click()
        assert getattr(svc.settings, key) == value, "precondition: the seal dropped the reset"
        assert page._status_label.text() == NOT_SAVED

    @pytest.mark.parametrize(("key", "value", "button"), CASES)
    def test_live_a_reset_says_it_happened(self, settings_page, key, value, button):
        page, svc = settings_page
        svc.update(**{key: value})
        page._refresh_reset_buttons()
        getattr(page, button).click()
        assert getattr(svc.settings, key) != value
        assert page._status_label.text() not in ("", NOT_SAVED)


# ── Hardware ───────────────────────────────────────────────────────────────


class TestOpenFanOutcomeExpiry:
    def test_the_line_goes_when_the_role_moves_on(self, qtbot, monkeypatch):
        page, state, _client = _openfan_page(qtbot, monkeypatch, [_role()])
        _OpenFanDialog.choice, _OpenFanDialog.accept = "chassis_fan", True
        _openfan_btn(page).click()
        assert _openfan_outcome(page).isVisibleTo(page), "precondition"

        state.set_openfan_roles([_role(role="radiator_fan")])  # set from elsewhere

        assert not _openfan_outcome(page).isVisibleTo(page)
        assert _openfan_outcome(page).text() == ""

    def test_the_line_stays_while_the_role_is_unchanged(self, qtbot, monkeypatch):
        page, state, _client = _openfan_page(qtbot, monkeypatch, [_role()])
        _OpenFanDialog.choice, _OpenFanDialog.accept = "chassis_fan", True
        _openfan_btn(page).click()
        state.set_openfan_roles(list(state.openfan_roles))  # a refresh, same roles
        assert _openfan_outcome(page).isVisibleTo(page)
        assert state.openfan_role(CH0).role == "chassis_fan"


def _user_pump(hid: str):
    return _hdr(hid, role="pump", role_source="user_assigned", stop_permitted=False)


class TestPumpRemovalPrompt:
    def _asked(self, monkeypatch, answer=QMessageBox.StandardButton.Yes) -> list[str]:
        asked: list[str] = []
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(a[1]) or answer)
        return asked

    def test_a_header_the_daemon_still_infers_a_pump_from_asks_nothing(self, qtbot, monkeypatch):
        page, _state, client = _picker_page(qtbot, monkeypatch, [_user_pump(LABEL_PUMP)])
        asked = self._asked(monkeypatch)
        _PickerDialog.choice, _PickerDialog.accept = None, True
        _role_btn(page, LABEL_PUMP).click()
        assert asked == []
        assert client.calls == [(LABEL_PUMP, None)]

    def test_a_header_that_loses_protection_still_asks(self, qtbot, monkeypatch):
        page, _state, client = _picker_page(qtbot, monkeypatch, [_user_pump(USER_PUMP)])
        asked = self._asked(monkeypatch, QMessageBox.StandardButton.No)
        _PickerDialog.choice, _PickerDialog.accept = None, True
        _role_btn(page, USER_PUMP).click()
        assert asked == ["Remove pump protection from a header?"]
        assert client.calls == []


class _RoleClient:
    def __init__(self, headers):
        self.log: list[tuple] = []
        self._headers = headers

    def set_header_role(self, header_id, role):
        from ventulus.api.models import HeaderRoleResult

        self.log.append((header_id, role))
        return HeaderRoleResult(
            updated=True, header_id=header_id, role=role, effective_role=role or "unknown"
        )

    def hwmon_headers(self):
        return list(self._headers)


class TestRoleWritesAskOnlyAboutALoss:
    HEADERS: ClassVar = [_user_pump(LABEL_PUMP), _user_pump(USER_PUMP)]

    def test_only_the_removal_that_loses_protection_is_asked_about(self):
        asked: list[list[str]] = []
        client = _RoleClient(self.HEADERS)
        apply_role_writes(
            client,
            self.HEADERS,
            [(LABEL_PUMP, None), (USER_PUMP, None)],
            confirm=lambda ids: asked.append(ids) or True,
            capabilities=_picker_caps(),
        )
        assert asked == [[USER_PUMP]]
        assert client.log == [(LABEL_PUMP, None), (USER_PUMP, None)]

    def test_without_capabilities_every_removal_is_asked_about(self):
        asked: list[list[str]] = []
        apply_role_writes(
            _RoleClient(self.HEADERS),
            self.HEADERS,
            [(LABEL_PUMP, None), (USER_PUMP, None)],
            confirm=lambda ids: asked.append(ids) or True,
            capabilities=None,
        )
        assert asked == [[LABEL_PUMP, USER_PUMP]]

    def test_a_removal_needing_no_question_still_runs_after_every_assign(self):
        new = "hwmon:it8696:it87.2624:pwm2:pwm2"
        headers = [*self.HEADERS, _hdr(new)]
        client = _RoleClient(headers)
        apply_role_writes(
            client,
            headers,
            [(LABEL_PUMP, None), (new, "pump")],
            confirm=lambda _ids: pytest.fail("nothing loses protection"),
            capabilities=_picker_caps(),
        )
        assert client.log == [(new, "pump"), (LABEL_PUMP, None)]


# ── Controls ───────────────────────────────────────────────────────────────


def _graph(curve_id: str, name: str) -> CurveConfig:
    return CurveConfig(
        id=curve_id,
        name=name,
        type=CurveType.GRAPH,
        sensor_id="hwmon:k10temp:Tctl",
        points=[CurvePoint(30, 40), CurvePoint(80, 100)],
    )


def _controls(qtbot, app_state, profile_service, *, controls, curves):
    page = ControlsPage(state=app_state, profile_service=profile_service)
    qtbot.addWidget(page)
    profile = profile_service.create_profile("Linked")
    profile.curves.extend(curves)
    profile.controls.extend(controls)
    page.select_profile(profile.id)
    return page, profile


def _used_by(page, curve_id: str) -> str:
    return page._curve_cards[curve_id]._used_by_label.text()


class TestLinkedCards:
    def test_deleting_a_role_clears_its_curves_used_by(self, qtbot, app_state, profile_service):
        role = LogicalControl(id="lc1", name="Front", mode=ControlMode.CURVE, curve_id="c1")
        page, _profile = _controls(
            qtbot, app_state, profile_service, controls=[role], curves=[_graph("c1", "Quiet")]
        )
        assert "Front" in _used_by(page, "c1"), "precondition"
        page._on_delete_control("lc1")
        assert _used_by(page, "c1") == "Not assigned"

    def test_a_new_role_appears_on_its_curve(self, qtbot, app_state, profile_service):
        page, _profile = _controls(
            qtbot, app_state, profile_service, controls=[], curves=[_graph("c1", "Quiet")]
        )
        assert _used_by(page, "c1") == "Not assigned", "precondition"
        page._on_new_control(name="Rear")
        assert "Rear" in _used_by(page, "c1")

    def test_renaming_a_curve_in_its_dialog_renames_it_on_the_role_card(
        self, qtbot, app_state, profile_service, monkeypatch
    ):
        from ventulus.ui.widgets.curve_edit_dialog import CurveEditDialog

        flat = CurveConfig(id="c1", name="Fixed", type=CurveType.FLAT, flat_output_pct=50)
        role = LogicalControl(id="lc1", name="Front", mode=ControlMode.CURVE, curve_id="c1")
        page, _profile = _controls(
            qtbot, app_state, profile_service, controls=[role], curves=[flat]
        )

        def rename(dlg):
            dlg._name_edit.setText("Steady")
            return 1

        monkeypatch.setattr(CurveEditDialog, "exec", rename)
        page._on_edit_curve("c1")

        assert page._control_cards["lc1"]._curve_label.text().startswith("Curve: Steady")


def test_renaming_a_curve_keeps_held_overrides(qtbot, app_state, profile_service, monkeypatch):
    role = LogicalControl(id="lc1", name="Front", mode=ControlMode.CURVE, curve_id="c1")
    page, _profile = _controls(
        qtbot, app_state, profile_service, controls=[role], curves=[_graph("c1", "Quiet")]
    )
    released: list[str] = []
    monkeypatch.setattr(page, "_release_all_overrides", lambda: released.append("all"))
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Calm", True))

    page._on_rename_curve("c1")

    assert page._control_cards["lc1"]._curve_label.text().startswith("Curve: Calm")
    assert released == []


def test_the_open_editors_floor_follows_its_roles(qtbot, app_state, profile_service):
    strict = LogicalControl(
        id="lc1", name="Pump", mode=ControlMode.CURVE, curve_id="c1", minimum_pct=30
    )
    loose = LogicalControl(
        id="lc2", name="Rad", mode=ControlMode.CURVE, curve_id="c1", minimum_pct=20
    )
    page, profile = _controls(
        qtbot,
        app_state,
        profile_service,
        controls=[strict, loose],
        curves=[_graph("c1", "Loop")],
    )
    page._on_edit_curve("c1")
    before = page._curve_editor._min_output
    assert before == page._curve_min_output_floor(profile, "c1"), "precondition"

    page._on_delete_control("lc1")

    after = page._curve_min_output_floor(profile, "c1")
    assert after < before, "precondition: deleting the strict role lowers the floor"
    assert page._curve_editor._min_output == after


class TestDialogWhoseProfileWasReplaced:
    """An activation lands while a modal dialog's nested loop runs."""

    def _page(self, qtbot, app_state, profile_service):
        role = LogicalControl(id="lc1", name="Front", mode=ControlMode.CURVE, curve_id="c1")
        page, profile = _controls(
            qtbot, app_state, profile_service, controls=[role], curves=[_graph("c1", "Quiet")]
        )
        active = profile_service.active_id
        assert active != profile.id, "precondition: the page shows a profile that is not running"
        other = next(p for p in profile_service.profiles if p.id not in (profile.id, active))
        return page, profile, other

    def test_the_role_dialog_applies_nothing(self, qtbot, app_state, profile_service, monkeypatch):
        page, profile, other = self._page(qtbot, app_state, profile_service)
        control = profile.controls[0]

        def activate_meanwhile(dlg):
            dlg._name_edit.setText("Renamed")
            profile_service.set_active(other.id)  # the Dashboard, the tray, another client
            return 1

        monkeypatch.setattr(FanRoleDialog, "exec", activate_meanwhile)
        page._on_edit_role("lc1")

        assert page.viewed_profile_id == other.id, "precondition: the page moved"
        assert control.name == "Front"
        assert not page.has_unsaved_changes()
        assert page._DIALOG_NOT_APPLIED in page._unsaved_label.text()

    def test_a_curve_rename_applies_nothing(self, qtbot, app_state, profile_service, monkeypatch):
        page, profile, other = self._page(qtbot, app_state, profile_service)

        def activate_meanwhile(*_a, **_k):
            profile_service.set_active(other.id)
            return ("Calm", True)

        monkeypatch.setattr(QInputDialog, "getText", activate_meanwhile)
        page._on_rename_curve("c1")

        assert profile.get_curve("c1").name == "Quiet"
        assert not page.has_unsaved_changes()

    @pytest.mark.parametrize("activated_meanwhile", [True, False])
    def test_configure_aio_builds_nothing_after_its_pump_prompt_moved_the_page(
        self, qtbot, app_state, profile_service, monkeypatch, activated_meanwhile
    ):
        """The role writes can ask about a pump removal, a second nested loop
        after the dialog's own."""
        from ventulus.ui.widgets.aio_config_dialog import AioConfigDialog

        page, profile, other = self._page(qtbot, app_state, profile_service)
        result = {
            "pump_strategy": None,
            "pump_member_id": None,
            "pump_pct": 0,
            "radiator_members": [{"source": "hwmon", "id": "hwmon:x:pwm1", "label": "Rad"}],
            "radiator_sensor_id": "cpu_temp",
            "role_assignments": [("hwmon:x:pwm2", None)],
            "cooling_device": None,
        }
        monkeypatch.setattr(AioConfigDialog, "exec", lambda _self: 1)
        monkeypatch.setattr(AioConfigDialog, "get_result", lambda _self: result)

        def role_writes_with_a_prompt(_assignments):
            if activated_meanwhile:
                profile_service.set_active(other.id)
            return True

        monkeypatch.setattr(page, "_apply_header_roles", role_writes_with_a_prompt)
        before = (len(profile.controls), len(profile.curves))
        page._on_configure_aio()

        built = (len(profile.controls), len(profile.curves)) != before
        assert built is not activated_meanwhile
        assert (page._DIALOG_NOT_APPLIED in page._unsaved_label.text()) is activated_meanwhile

    def test_a_cancelled_dialog_says_nothing(self, qtbot, app_state, profile_service, monkeypatch):
        page, _profile, other = self._page(qtbot, app_state, profile_service)

        def activate_then_cancel(_dlg):
            profile_service.set_active(other.id)
            return 0

        monkeypatch.setattr(FanRoleDialog, "exec", activate_then_cancel)
        page._on_edit_role("lc1")
        assert page.viewed_profile_id == other.id, "precondition: the page moved"
        assert page._DIALOG_NOT_APPLIED not in page._unsaved_label.text()

    def test_activating_the_profile_on_screen_still_applies(
        self, qtbot, app_state, profile_service, monkeypatch
    ):
        page, profile, _other = self._page(qtbot, app_state, profile_service)

        def activate_this(dlg):
            dlg._name_edit.setText("Renamed")
            profile_service.set_active(profile.id)
            return 1

        monkeypatch.setattr(FanRoleDialog, "exec", activate_this)
        page._on_edit_role("lc1")

        assert profile.controls[0].name == "Renamed"
        assert page.has_unsaved_changes()


# ── DEC-165: a Save's reapply honours the stand-down ─────────────────────────


@pytest.mark.parametrize("blocked", [False, True])
def test_saving_the_active_profile_reapplies_only_when_not_stood_down(qtbot, app_state, blocked):
    from unittest.mock import MagicMock

    from ventulus.api.models import ProfileActivateResult

    client = MagicMock()
    client.create_profile.return_value = {"created": "p1"}
    client.activate_profile.return_value = ProfileActivateResult(
        activated=True, profile_id="p1", profile_name="P1"
    )
    ps = ProfileService(client=client)
    ps._profiles["p1"] = Profile(id="p1", name="P1")
    ps.set_active("p1")
    ps.control_blocked_reason = "ventulusd 1.22.0 is too old" if blocked else None
    page = ControlsPage(state=app_state, profile_service=ps, client=client)
    qtbot.addWidget(page)

    page._on_save_profile()

    assert client.activate_profile.called is not blocked
    assert ("reapply failed" in page._unsaved_label.text()) is blocked
