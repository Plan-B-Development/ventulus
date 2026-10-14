"""GUI audit 2026-10-14, batch B: what the GUI shows with no daemon, or a changed one.

Each surface here showed a state no poll had confirmed:

- started with no daemon, the footer kept a green "Thermal OK" built from no
  data and the "Daemon disconnected" banner never appeared, because the first
  failed poll repeated AppState's initial DISCONNECTED and so emitted nothing;
- the ribbon kept the daemon's last uptime after a disconnect (G-17);
- the Overview health card kept its green "ok", uptime and override countdown;
- the readiness report read the fetched snapshot's thermal state, not the live
  one the Safety row beside it shows (DEC-358);
- Settings read the daemon config once per session, so a daemon restart left
  "restart required" up and one failed read disabled the card for good, and
  capabilities arriving after the config never re-gated the exit minimum and
  the coolant limit.

Every test drives the real signal or the real call site, and asserts the arm
the pre-fix code could not produce.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from tests.test_daemon_config_dec243 import _ConfigClient, _default_config, _key
from tests.test_system_state_health_noise import _healthy_gigabyte
from ventulus.api.errors import DaemonUnavailable
from ventulus.api.models import (
    Capabilities,
    ConnectionState,
    ControlCapability,
    DaemonStatus,
    ThermalSafetyInfo,
)
from ventulus.services.app_state import AppState
from ventulus.services.daemon_features import unsupported_feature_message
from ventulus.services.duty_drift import NO_DRIFT
from ventulus.services.overview_view import build_daemon_health_vm
from ventulus.ui.widgets.readiness_report import (
    THERMAL_STATE_NO_CONNECTION,
    build_readiness_report_html,
)

DISCONNECT_BANNER = "Daemon disconnected — retrying..."


@pytest.fixture()
def fresh_state() -> AppState:
    return AppState()


# ── AppState: the first report is a change ─────────────────────────────────


def test_the_first_report_emits_even_when_it_repeats_the_initial_state(qtbot):
    state = AppState()
    assert state.connection == ConnectionState.DISCONNECTED, "precondition: the placeholder"
    seen: list[ConnectionState] = []
    state.connection_changed.connect(seen.append)

    state.set_connection(ConnectionState.DISCONNECTED)
    state.set_connection(ConnectionState.DISCONNECTED)

    assert seen == [ConnectionState.DISCONNECTED], "once for the first report, then only changes"


# ── The shell at startup ───────────────────────────────────────────────────


def _window(qtbot, app_state, profile_service, settings_service):
    """A live-mode window as `main.py` builds it: on a fresh AppState, which
    no poll has reported to yet (the shared fixture's is already CONNECTED)."""
    from ventulus.ui.main_window import MainWindow

    assert not app_state._connection_reported, "pass a fresh AppState()"
    win = MainWindow(
        state=app_state,
        profile_service=profile_service,
        settings_service=settings_service,
        demo_mode=False,
    )
    qtbot.addWidget(win)
    return win


def _banner_text(win) -> str:
    return win.error_banner._message_label.text()


def test_no_thermal_chip_before_any_poll(qtbot, fresh_state, profile_service, settings_service):
    app_state = fresh_state
    win = _window(qtbot, app_state, profile_service, settings_service)
    assert not win.footer._thermal_btn.isVisibleTo(win.footer)
    assert not win.status_ribbon._thermal_pill.isVisibleTo(win.status_ribbon)
    # Nothing has failed yet, so nothing says it has.
    assert win.error_banner.isHidden()


def test_the_first_failed_poll_raises_the_disconnect_banner(
    qtbot, fresh_state, profile_service, settings_service
):
    app_state = fresh_state
    win = _window(qtbot, app_state, profile_service, settings_service)
    assert win.error_banner.isHidden(), "precondition"

    # What PollingService._on_disconnected does on a failed poll.
    app_state.set_connection(ConnectionState.DISCONNECTED)

    assert not win.error_banner.isHidden()
    assert _banner_text(win) == DISCONNECT_BANNER
    assert not win.footer._thermal_btn.isVisibleTo(win.footer)


def test_a_healthy_start_shows_the_chip_and_no_disconnect_banner(
    qtbot, fresh_state, profile_service, settings_service
):
    app_state = fresh_state
    win = _window(qtbot, app_state, profile_service, settings_service)
    # A successful first poll: status first, then the connection (polling.py).
    app_state.set_status(DaemonStatus(thermal_state="normal"))
    app_state.set_connection(ConnectionState.CONNECTED)

    assert win.footer._thermal_btn.isVisibleTo(win.footer)
    assert _banner_text(win) != DISCONNECT_BANNER


# ── The ribbon's uptime (G-17) ─────────────────────────────────────────────


def test_the_ribbon_drops_the_uptime_on_disconnect(
    qtbot, fresh_state, profile_service, settings_service
):
    from ventulus.ui.status_ribbon import format_uptime

    app_state = fresh_state
    win = _window(qtbot, app_state, profile_service, settings_service)
    label = win.status_ribbon._uptime_label
    app_state.set_status(DaemonStatus(thermal_state="normal", uptime_seconds=7200))
    app_state.set_connection(ConnectionState.CONNECTED)
    assert label.text() == format_uptime(7200), "precondition"
    assert label.text() != format_uptime(None), "precondition: the two forms differ"

    app_state.set_connection(ConnectionState.DISCONNECTED)
    assert label.text() == format_uptime(None)

    app_state.set_status(DaemonStatus(thermal_state="normal", uptime_seconds=5))
    app_state.set_connection(ConnectionState.CONNECTED)
    assert label.text() == format_uptime(5)


# ── The Overview health card ───────────────────────────────────────────────


def test_the_health_view_model_has_a_disconnected_form():
    status = DaemonStatus(overall_status="ok", uptime_seconds=60)
    live = build_daemon_health_vm(None, status)
    gone = build_daemon_health_vm(None, status, connected=False)
    assert live.status_state == "ok", "precondition"
    assert (gone.status_text, gone.status_state) == ("Status: disconnected", "neutral")
    assert gone.uptime_text == build_daemon_health_vm(None, None).uptime_text
    assert gone.overrides_text == build_daemon_health_vm(None, None).overrides_text


def test_the_overview_card_stops_reporting_ok_on_disconnect(qtbot):
    from tests.test_overview_page import _page

    page, state = _page(qtbot)
    state.set_status(DaemonStatus(overall_status="ok", uptime_seconds=3600))
    assert page._daemon_status_pill.state() == "ok", "precondition"
    healthy_uptime = page._daemon_uptime_label.text()

    state.set_connection(ConnectionState.DISCONNECTED)
    assert page._daemon_status_pill.text() == "DISCONNECTED"
    assert page._daemon_status_pill.state() == "neutral"
    assert page._daemon_uptime_label.text() != healthy_uptime

    state.set_status(DaemonStatus(overall_status="ok", uptime_seconds=1))
    state.set_connection(ConnectionState.CONNECTED)
    assert page._daemon_status_pill.state() == "ok"


# ── The readiness report's thermal state ───────────────────────────────────


def _report_text(diag, live) -> str:
    from PySide6.QtGui import QTextDocument

    doc = QTextDocument()
    doc.setHtml(build_readiness_report_html(diag, duty_drift=NO_DRIFT, live_thermal_state=live))
    return doc.toPlainText()


@pytest.mark.parametrize(
    ("live", "expected"),
    [
        (None, "State: normal"),
        ("", "State: normal"),
        ("emergency", "State: emergency"),
        (THERMAL_STATE_NO_CONNECTION, "State: unknown — disconnected"),
    ],
)
def test_the_report_states_the_live_thermal_state(live, expected):
    diag = _healthy_gigabyte(thermal_safety=ThermalSafetyInfo(state="normal"))
    assert expected in _report_text(diag, live)


def test_the_report_verdict_follows_the_live_state():
    diag = _healthy_gigabyte(thermal_safety=ThermalSafetyInfo(state="normal"))
    text = _report_text(diag, THERMAL_STATE_NO_CONNECTION)
    assert "thermal safety unknown — disconnected" in text
    assert "thermal safety normal" not in text


def _system_state_page(qtbot):
    from ventulus.services.app_settings_service import AppSettingsService
    from ventulus.services.diagnostics_service import DiagnosticsService
    from ventulus.ui.pages.system_state_page import SystemStatePage

    svc = AppSettingsService()
    # A recorded effective test keeps the verdict "✓ System ready … · thermal …".
    svc.update(last_pwm_verify_effective="effective")
    diag_svc = DiagnosticsService(None)
    diag_svc.set_hw_diagnostics(_healthy_gigabyte())
    page = SystemStatePage(diagnostics_service=diag_svc, settings_service=svc)
    qtbot.addWidget(page)
    return page


def test_an_open_report_follows_the_pages_live_thermal_state(qtbot):
    """Both call sites: the open (button) and the re-render on a change."""
    page = _system_state_page(qtbot)
    page.set_thermal_state("emergency")
    page._open_report_btn.setEnabled(True)
    page._open_report_btn.click()
    assert page._report_dialog is not None
    assert "State: emergency" in page._report_dialog._browser.toPlainText()

    page.set_live(False)
    shown = page._report_dialog._browser.toPlainText()
    assert "State: unknown — disconnected" in shown
    assert "thermal safety unknown — disconnected" in shown
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


# ── Settings: the daemon configuration is re-read ──────────────────────────


def _caps(*, live_keys: bool = True) -> Capabilities:
    return Capabilities(
        control=ControlCapability(exit_floor=live_keys, cooling_failure_detection=live_keys)
    )


def _restart_pending_config():
    cfg = _default_config()
    at = next(i for i, k in enumerate(cfg.keys) if k.key == "polling.poll_interval_ms")
    cfg.keys[at] = _key(
        "polling.poll_interval_ms",
        500,
        mutable=True,
        requires_restart=True,
        restart_pending=True,
        running_value=1000,
    )
    cfg.restart_pending = True
    return cfg


class _FlakyConfigClient(_ConfigClient):
    """A daemon whose config read can be made to fail."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.fail = False
        self.reads = 0

    def inventory_hwmon(self):
        raise DaemonUnavailable()  # the preferred-sensor picker; not under test

    def get_daemon_config(self):
        self.reads += 1
        if self.fail:
            raise DaemonUnavailable()
        return super().get_daemon_config()


def _settings_page(qtbot, app_state, settings_service, client):
    from ventulus.ui.pages.settings_page import SettingsPage

    page = SettingsPage(state=app_state, settings_service=settings_service, client=client)
    qtbot.addWidget(page)
    return page


def test_each_arrival_rereads_and_a_restart_clears_the_banner(qtbot, app_state, settings_service):
    app_state.capabilities = _caps()
    client = _FlakyConfigClient(config=_restart_pending_config())
    page = _settings_page(qtbot, app_state, settings_service, client)
    page.show()
    assert page._daemon_restart_banner.isVisibleTo(page), "precondition"

    # The daemon restarted between visits: nothing is pending now.
    client._config = _default_config()
    page.hide()
    page.show()
    assert client.reads == 2
    assert not page._daemon_restart_banner.isVisibleTo(page)


def test_a_failed_read_does_not_disable_the_card_for_the_session(
    qtbot, app_state, settings_service
):
    """The audit's path: a write lands, but the re-read after it fails."""
    app_state.capabilities = _caps()
    client = _FlakyConfigClient()
    page = _settings_page(qtbot, app_state, settings_service, client)
    page.show()
    assert page._poll_interval_spin.isEnabled(), "precondition"
    lead = page._daemon_cfg_note.text()

    client.fail = True
    page._poll_interval_spin.setValue(2000)
    page._poll_interval_spin.editingFinished.emit()
    assert ("polling.poll_interval_ms", 2000) in client.writes, "precondition: the write went"
    assert not page._poll_interval_spin.isEnabled(), "precondition: its re-read failed"
    assert page._daemon_cfg_note.text() != lead

    client.fail = False
    page.hide()
    page.show()
    assert page._poll_interval_spin.isEnabled()
    assert page._daemon_cfg_note.text() == lead


def test_capabilities_after_the_config_regate_the_live_keys(qtbot, app_state, settings_service):
    """Settings as the startup page: its first read lands before `/capabilities`."""
    assert app_state.capabilities is None
    client = _FlakyConfigClient()
    page = _settings_page(qtbot, app_state, settings_service, client)
    page.show()
    assert not page._coolant_limit_spin.isEnabled(), "precondition: no capabilities yet"
    assert not page._exit_floor_spin.isEnabled(), "precondition: no capabilities yet"

    app_state.set_capabilities(_caps())

    assert page._coolant_limit_spin.isEnabled()
    assert page._exit_floor_spin.isEnabled()
    note = page._daemon_row_notes["safety.coolant_limit_c"].text()
    assert unsupported_feature_message("cooling_failure_detection") not in note


def test_a_capabilities_refresh_on_screen_clears_a_stale_restart_banner(
    qtbot, app_state, settings_service
):
    app_state.capabilities = _caps()
    client = _FlakyConfigClient(config=_restart_pending_config())
    page = _settings_page(qtbot, app_state, settings_service, client)
    page.show()
    assert page._daemon_restart_banner.isVisibleTo(page), "precondition"

    client._config = _default_config()
    # What polling does after it notices a daemon restart.
    app_state.set_capabilities(_caps())
    assert not page._daemon_restart_banner.isVisibleTo(page)


def test_a_capabilities_refresh_off_screen_reads_nothing(qtbot, app_state, settings_service):
    app_state.capabilities = _caps()
    client = _FlakyConfigClient()
    page = _settings_page(qtbot, app_state, settings_service, client)
    page.show()
    page.hide()
    reads = client.reads
    app_state.set_capabilities(_caps())
    assert client.reads == reads


def _has_focus(widget) -> bool:
    focus = QApplication.focusWidget()
    return focus is not None and (focus is widget or widget.isAncestorOf(focus))


def test_a_refresh_while_editing_keeps_the_typed_value(qtbot, app_state, settings_service):
    """A capabilities refresh must not overwrite a value being typed, and still
    re-gates the card: here the coolant limit, gated until capabilities land."""
    assert app_state.capabilities is None
    client = _FlakyConfigClient()
    page = _settings_page(qtbot, app_state, settings_service, client)
    page.show()
    page.activateWindow()
    assert not page._coolant_limit_spin.isEnabled(), "precondition: gated, no capabilities"
    spin = page._poll_interval_spin
    spin.setFocus()
    qtbot.waitUntil(lambda: _has_focus(spin), timeout=1000)
    shown = spin.value()
    spin.setValue(shown + 250)  # typed, not yet committed
    reads = client.reads

    app_state.set_capabilities(_caps())

    assert client.reads == reads, "no read while an editor has focus"
    assert spin.value() == shown + 250
    assert page._coolant_limit_spin.isEnabled()


def test_a_later_good_read_clears_a_read_error_but_not_a_write_result(
    qtbot, app_state, settings_service
):
    from ventulus.api.errors import DaemonError

    app_state.capabilities = _caps()
    client = _FlakyConfigClient()
    page = _settings_page(qtbot, app_state, settings_service, client)

    def broken():
        raise DaemonError("internal", "boom", status=500)

    client.get_daemon_config = broken  # type: ignore[method-assign]
    page.show()
    assert "Could not read daemon configuration" in page._daemon_cfg_result.text()

    del client.get_daemon_config  # back to the class's working read
    page.hide()
    page.show()
    assert page._daemon_cfg_result.isHidden()

    page._poll_interval_spin.setValue(2000)
    page._poll_interval_spin.editingFinished.emit()
    assert ("polling.poll_interval_ms", 2000) in client.writes
    assert page._daemon_cfg_result.text().startswith("Saved polling.poll_interval_ms")


def test_focus_parked_with_nothing_typed_does_not_block_the_read(
    qtbot, app_state, settings_service
):
    """Enter commits a value and keeps focus; a restart must still clear the banner."""
    app_state.capabilities = _caps()
    client = _FlakyConfigClient(config=_restart_pending_config())
    page = _settings_page(qtbot, app_state, settings_service, client)
    page.show()
    page.activateWindow()
    assert page._daemon_restart_banner.isVisibleTo(page), "precondition"
    spin = page._poll_interval_spin
    spin.setFocus()
    qtbot.waitUntil(lambda: _has_focus(spin), timeout=1000)

    client._config = _default_config()
    app_state.set_capabilities(_caps())
    assert not page._daemon_restart_banner.isVisibleTo(page)


def test_a_background_reread_keeps_the_selected_search_dir(qtbot, app_state, settings_service):
    app_state.capabilities = _caps()
    cfg = _default_config()
    at = next(i for i, k in enumerate(cfg.keys) if k.key == "profiles.search_dirs")
    dirs = ["/var/lib/ventulus/profiles", "/home/u/a", "/home/u/b"]
    cfg.keys[at] = _key("profiles.search_dirs", dirs, mutable=True, running_value=dirs)
    client = _FlakyConfigClient(config=cfg)
    page = _settings_page(qtbot, app_state, settings_service, client)
    page.show()
    listing = page._search_dirs_list
    listing.setCurrentRow(2)
    assert listing.currentItem().text() == "/home/u/b", "precondition"
    reads = client.reads

    app_state.set_capabilities(_caps())

    assert client.reads == reads + 1, "precondition: the re-read happened"
    assert listing.currentItem() is not None
    assert listing.currentItem().text() == "/home/u/b"


@pytest.mark.parametrize(
    ("live", "css", "tick"),
    [
        ("normal", "SuccessChip", True),
        ("emergency", "CriticalChip", False),
        ("recovery", "WarningChip", False),
        (THERMAL_STATE_NO_CONNECTION, "WarningChip", False),
    ],
)
def test_the_verdict_is_green_only_while_thermal_safety_is_normal(live, css, tick):
    from ventulus.ui.widgets.readiness_report import readiness_verdict

    diag = _healthy_gigabyte(thermal_safety=ThermalSafetyInfo(state="normal"))
    text, cls = readiness_verdict(
        diag, pwm_control_verified=True, duty_drift=NO_DRIFT, live_thermal_state=live
    )
    assert cls == css
    assert text.startswith("✓") is tick


def test_a_restart_takes_down_a_saved_but_pending_write_result(qtbot, app_state, settings_service):
    app_state.capabilities = _caps()
    client = _FlakyConfigClient()
    page = _settings_page(qtbot, app_state, settings_service, client)
    page.show()
    # The daemon reports the key pending once written.
    client._config = _restart_pending_config()
    page._poll_interval_spin.setValue(500)
    page._poll_interval_spin.editingFinished.emit()
    assert ("polling.poll_interval_ms", 500) in client.writes, "precondition"
    assert page._daemon_cfg_result.text().startswith("Saved"), "precondition"

    client._config = _default_config()
    app_state.set_capabilities(_caps())
    assert page._daemon_cfg_result.isHidden()
