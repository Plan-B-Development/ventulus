"""DEC-499: the update check's surfaces — Settings ▸ Updates, the window notice, About.

The check itself is stubbed at ``update_check.check`` (its own tests run it
against a mock server); these tests drive the real controller, worker thread and
widgets through their signals and clicks.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from tests.update_fixtures import encode, installed, manifest_dict
from ventulus.services import update_check
from ventulus.services.install_ownership import InstallMethod
from ventulus.services.update_check import CheckState, Outcome, UpdateReport, evaluate
from ventulus.services.update_manifest import parse_manifest
from ventulus.services.update_view import (
    NEVER_CHECKED,
    detail_lines,
    notice_text,
    status_line,
)
from ventulus.ui import update_controller as controller_module
from ventulus.ui.pages.settings_page import SettingsPage
from ventulus.ui.update_controller import UpdateController

NOW = datetime.datetime(2026, 10, 21, 9, 0, tzinfo=datetime.UTC)


def report_for(*, gui="5.2.0", daemon="5.2.0", method=InstallMethod.PACMAN) -> UpdateReport:
    manifest = parse_manifest(encode(manifest_dict(gui=gui, daemon=daemon)))
    return evaluate(manifest, installed(gui=method, daemon=method), checked_at=NOW)


@pytest.fixture()
def stub_check(monkeypatch):
    """Answer every check with ``stub_check.report``; count the calls."""

    class Stub:
        report = report_for()
        calls = 0

    def fake_check(inst, *, client, state, **_kw):
        Stub.calls += 1
        state.last_attempt = NOW
        return Stub.report

    monkeypatch.setattr(update_check, "check", fake_check)
    monkeypatch.setattr(
        controller_module,
        "gather_installed",
        lambda app_version, daemon_version: installed(daemon_version=daemon_version),
    )
    return Stub


@pytest.fixture()
def page(qtbot, app_state, settings_service):
    page = SettingsPage(state=app_state, settings_service=settings_service)
    qtbot.addWidget(page)
    yield page
    page._updates.shutdown()


def _label(widget, name: str) -> QLabel:
    found = widget.findChild(QLabel, name)
    assert found is not None, name
    return found


def _button(widget, name: str) -> QPushButton:
    found = widget.findChild(QPushButton, name)
    assert found is not None, name
    return found


# ── the view model ───────────────────────────────────────────────────────────


def test_the_view_says_what_a_check_found():
    assert status_line(None) == NEVER_CHECKED
    assert "an update is available" in status_line(report_for())
    assert "no update available" in status_line(report_for(gui="5.1.0", daemon="5.1.0"))
    lines = detail_lines(report_for())
    assert lines[0] == "Ventulus 5.1.0, installed with pacman: 5.2.0 is available."
    assert "    sudo pacman -Syu" in lines
    assert lines[-1].startswith("Release information published 2026-10-20 12:00 UTC")
    assert notice_text(report_for()) == (
        "Update available: Ventulus 5.2.0 and ventulusd 5.2.0. See Settings ▸ Updates."
    )
    assert notice_text(report_for(gui="5.1.0", daemon="5.1.0")) == ""


def test_a_failure_is_never_shown_as_a_result():
    failed = UpdateReport(outcome=Outcome.UNVERIFIED, checked_at=NOW, error="Bad signature.")
    assert "no result" in status_line(failed) and "Bad signature." in status_line(failed)
    assert detail_lines(failed) == []
    assert notice_text(failed) == ""


# ── Settings ▸ Updates ───────────────────────────────────────────────────────


def test_the_switch_is_off_and_saves_with_save_changes(page, settings_service):
    switch = page.findChild(type(page._update_auto_cb), "Settings_Check_updateAuto")
    assert switch is page._update_auto_cb
    assert switch.isChecked() is False
    switch.click()
    assert settings_service.settings.update_check_auto is False  # not until Save
    _button(page, "Settings_Btn_saveApp").click()
    assert settings_service.settings.update_check_auto is True


def test_an_imported_settings_file_cannot_switch_the_check_on():
    from ventulus.services.app_settings_service import MACHINE_SPECIFIC_KEYS, AppSettings

    assert "update_check_auto" in MACHINE_SPECIFIC_KEYS
    assert "update_check_auto" not in AppSettings(update_check_auto=True).portable_dict()


def test_check_for_updates_renders_the_report(qtbot, page, stub_check):
    status = _label(page, "Settings_Label_updateStatus")
    details = _label(page, "Settings_Label_updateDetails")
    assert status.text() == NEVER_CHECKED
    assert not details.isVisibleTo(page)
    with qtbot.waitSignal(page._updates.report_ready, timeout=5000):
        _button(page, "Settings_Btn_checkUpdates").click()
    assert stub_check.calls == 1
    assert status.text() == status_line(stub_check.report)
    assert details.isVisibleTo(page)
    assert details.text() == "\n".join(detail_lines(stub_check.report))
    # A pacman install has nothing to download.
    assert not _button(page, "Settings_Btn_downloadGui").isVisibleTo(page)


def test_a_tarball_install_downloads_and_shows_the_install_commands(
    qtbot, page, stub_check, monkeypatch, tmp_path
):
    stub_check.report = report_for(method=InstallMethod.TARBALL)
    monkeypatch.setattr(update_check, "default_download_dir", lambda: tmp_path)
    from ventulus.ui.pages import settings_page as settings_module

    monkeypatch.setattr(settings_module, "default_download_dir", lambda: tmp_path)
    saved_to: list[Path] = []

    def fake_download(asset, dest_dir, *, client, cancel):
        target = dest_dir / asset.name
        target.write_bytes(b"verified")
        saved_to.append(target)
        return target

    monkeypatch.setattr(update_check, "download_asset", fake_download)
    with qtbot.waitSignal(page._updates.report_ready, timeout=5000):
        _button(page, "Settings_Btn_checkUpdates").click()
    gui_btn = _button(page, "Settings_Btn_downloadGui")
    assert gui_btn.isVisibleTo(page)
    assert gui_btn.text() == "Download and verify Ventulus 5.2.0"
    assert _button(page, "Settings_Btn_downloadDaemon").isVisibleTo(page)
    with qtbot.waitSignal(page._updates.download_finished, timeout=5000):
        gui_btn.click()
    assert saved_to == [tmp_path / "ventulus-5.2.0-noarch.tar.gz"]
    result = _label(page, "Settings_Label_updateDownload").text()
    command = update_check.tarball_install_commands(stub_check.report.gui.asset, saved_to[0])
    assert command is not None
    assert result.startswith(f"Saved and verified: {saved_to[0]}")
    assert result.endswith(command)
    copy = _button(page, "Settings_Btn_copyInstallCommands")
    assert copy.isVisibleTo(page)
    copy.click()
    assert QApplication.clipboard().text() == command


def test_a_refused_download_says_so_and_keeps_nothing(qtbot, page, stub_check, monkeypatch):
    stub_check.report = report_for(method=InstallMethod.TARBALL)

    def refuse(asset, dest_dir, *, client, cancel):
        raise update_check.DownloadError("the file does not match the SHA-256 the release lists")

    monkeypatch.setattr(update_check, "download_asset", refuse)
    with qtbot.waitSignal(page._updates.report_ready, timeout=5000):
        _button(page, "Settings_Btn_checkUpdates").click()
    with qtbot.waitSignal(page._updates.download_finished, timeout=5000):
        _button(page, "Settings_Btn_downloadDaemon").click()
    text = _label(page, "Settings_Label_updateDownload").text()
    assert text.startswith("Download refused: the file does not match the SHA-256")
    assert not _button(page, "Settings_Btn_copyInstallCommands").isVisibleTo(page)


# ── the controller: no request unless asked or opted in ──────────────────────


def test_with_the_switch_off_the_timer_never_checks(qtbot, settings_service, stub_check):
    ctl = UpdateController(settings_service=settings_service)
    try:
        assert settings_service.settings.update_check_auto is False
        assert ctl.maybe_check_automatically() is False
        assert stub_check.calls == 0
        assert ctl._thread is None  # the worker was never even started
        # Positive control: opted in, with no check yet today, it checks.
        settings_service.update(update_check_auto=True)
        with qtbot.waitSignal(ctl.report_ready, timeout=5000):
            assert ctl.maybe_check_automatically() is True
        assert stub_check.calls == 1
        # And not again the same day.
        update_check.save_state(CheckState(last_attempt=datetime.datetime.now(datetime.UTC)))
        assert ctl.maybe_check_automatically() is False
        assert stub_check.calls == 1
    finally:
        ctl.shutdown()


def test_one_check_at_a_time(qtbot, settings_service, stub_check):
    ctl = UpdateController(settings_service=settings_service)
    try:
        with qtbot.waitSignal(ctl.report_ready, timeout=5000):
            assert ctl.check_now() is True
            assert ctl.check_now() is False
        assert stub_check.calls == 1
    finally:
        ctl.shutdown()


def test_demo_mode_reports_no_daemon_version(app_state, settings_service):
    from ventulus.api.models import Capabilities, OperationMode

    ctl = UpdateController(settings_service=settings_service, state=app_state)
    app_state.set_capabilities(Capabilities(daemon_version="5.1.0"))
    assert ctl.daemon_version() == "5.1.0"
    app_state.set_mode(OperationMode.DEMO)
    assert ctl.daemon_version() is None


# ── the window notice and About ──────────────────────────────────────────────


@pytest.fixture()
def window(qtbot, app_state, profile_service, settings_service):
    from ventulus.ui.main_window import MainWindow

    win = MainWindow(
        state=app_state,
        profile_service=profile_service,
        settings_service=settings_service,
        demo_mode=False,
    )
    qtbot.addWidget(win)
    return win


def test_the_notice_shows_an_update_and_stays_dismissed_until_a_newer_one(window):
    notice = window.update_notice
    assert not notice.isVisibleTo(window)
    window.update_controller.last_report = report_for()
    window.update_controller.report_ready.emit(report_for())
    assert notice.isVisibleTo(window)
    assert notice.text() == notice_text(report_for())
    _button(window, "MainWindow_Btn_updateDismiss").click()
    assert not notice.isVisibleTo(window)
    assert update_check.load_dismissed() == report_for().offer_key
    window.update_controller.report_ready.emit(report_for())
    assert not notice.isVisibleTo(window)
    newer = report_for(gui="5.3.0")
    window.update_controller.last_report = newer
    window.update_controller.report_ready.emit(newer)
    assert notice.isVisibleTo(window)
    # Nothing to offer: no notice.
    window.update_controller.report_ready.emit(report_for(gui="5.1.0", daemon="5.1.0"))
    assert not notice.isVisibleTo(window)


def test_details_opens_settings_updates(window):
    from ventulus.constants import PAGE_SETTINGS

    window.update_controller.report_ready.emit(report_for())
    _button(window, "MainWindow_Btn_updateDetails").click()
    assert window.page_stack.currentIndex() == PAGE_SETTINGS


def test_about_shows_both_versions_and_offers_a_check(qtbot):
    from ventulus.constants import APP_VERSION
    from ventulus.ui.about_dialog import AboutDialog

    asked: list[bool] = []
    dlg = AboutDialog(daemon_version="5.1.0", on_check_updates=lambda: asked.append(True))
    qtbot.addWidget(dlg)
    versions = _label(dlg, "About_Label_versions").text()
    assert versions == f"Ventulus {APP_VERSION} · ventulusd 5.1.0"
    _button(dlg, "About_Btn_checkUpdates").click()
    assert asked == [True]
    plain = AboutDialog()
    qtbot.addWidget(plain)
    assert _label(plain, "About_Label_versions").text().endswith("ventulusd not connected")
    assert plain.findChild(QPushButton, "About_Btn_checkUpdates") is None


def test_about_check_opens_settings_and_checks(qtbot, window, stub_check):
    from ventulus.constants import PAGE_SETTINGS

    with qtbot.waitSignal(window.update_controller.report_ready, timeout=5000):
        window.sidebar.check_updates_requested.emit()
    assert window.page_stack.currentIndex() == PAGE_SETTINGS
    assert stub_check.calls == 1
