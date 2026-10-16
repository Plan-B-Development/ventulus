"""Runs the update check off the UI thread and keeps its latest answer (DEC-499).

One controller per window. The worker thread starts on the first check or
download, so a session that never checks never starts it. The opt-in daily check
asks :func:`update_check.automatic_check_due` on a timer and does nothing while
``update_check_auto`` is off: with the setting off, only "Check for updates"
makes a request.
"""

from __future__ import annotations

import datetime
import logging
import platform
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot

from ventulus.api.models import ConnectionState, OperationMode
from ventulus.constants import APP_VERSION, EXPECTED_API_VERSION
from ventulus.knowledge.driver_install import parse_os_release
from ventulus.services import install_ownership, update_check
from ventulus.services.update_check import (
    DOWNLOAD_TIMEOUT,
    ComponentStatus,
    DownloadError,
    Installed,
    UpdateReport,
)

log = logging.getLogger(__name__)

#: How often the timer asks whether the daily check is due.
AUTO_POLL_MS = 60 * 60 * 1000
#: The first look after start-up, so a check never competes with the first polls.
AUTO_FIRST_MS = 60 * 1000
#: How long close waits for a check or download in flight to give up. The
#: check's own timeouts bound it; the download stops at its next chunk.
SHUTDOWN_WAIT_MS = 15_000


def _fedora_release() -> int | None:
    for path in (Path("/etc/os-release"), Path("/usr/lib/os-release")):
        try:
            fields = parse_os_release(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if fields.get("ID") != "fedora":
            return None
        version = fields.get("VERSION_ID", "")
        return int(version) if version.isdigit() else None
    return None


def gather_installed(app_version: str, daemon_version: str | None) -> Installed:
    """What is installed here, asked of the package managers (worker thread)."""
    return Installed(
        gui_version=app_version,
        daemon_version=daemon_version,
        gui=install_ownership.gui_ownership(
            install_ownership.gui_module_file(), app_version=app_version
        ),
        daemon=install_ownership.daemon_ownership(),
        machine=platform.machine(),
        fedora=_fedora_release(),
        api_version=EXPECTED_API_VERSION,
    )


class _UpdateWorker(QObject):
    checked = Signal(object)  # UpdateReport
    downloaded = Signal(str, str, str)  # project, saved path ("" on failure), error

    def __init__(self, app_version: str) -> None:
        super().__init__()
        self._app_version = app_version
        self.cancel = threading.Event()

    @Slot(object)
    def do_check(self, daemon_version: object) -> None:
        version = daemon_version if isinstance(daemon_version, str) else None
        try:
            installed = gather_installed(self._app_version, version)
            state = update_check.load_state()
            with update_check.make_client(self._app_version) as client:
                report = update_check.check(
                    installed, client=client, state=state, cancel=self.cancel
                )
            update_check.save_state(state)
        except Exception as exc:  # never let a check take the worker down
            log.exception("Update check failed unexpectedly")
            report = UpdateReport(
                outcome=update_check.Outcome.UNVERIFIED,
                checked_at=datetime.datetime.now(datetime.UTC),
                error=f"The check stopped with an unexpected error ({type(exc).__name__}).",
            )
        self.checked.emit(report)

    @Slot(object, str)
    def do_download(self, status: object, dest_dir: str) -> None:
        if not isinstance(status, ComponentStatus) or status.asset is None:
            self.downloaded.emit("", "", "nothing to download")
            return
        try:
            with update_check.make_client(self._app_version, DOWNLOAD_TIMEOUT) as client:
                saved = update_check.download_asset(
                    status.asset, Path(dest_dir), client=client, cancel=self.cancel
                )
        except DownloadError as exc:
            self.downloaded.emit(status.project, "", str(exc))
            return
        except Exception as exc:
            log.exception("Update download failed unexpectedly")
            self.downloaded.emit(status.project, "", f"unexpected error ({type(exc).__name__})")
            return
        self.downloaded.emit(status.project, str(saved), "")


class UpdateController(QObject):
    """The window's update check: one in flight at a time, the last answer kept."""

    check_started = Signal()
    report_ready = Signal(object)  # UpdateReport
    download_started = Signal(str)  # project
    download_finished = Signal(str, str, str)  # project, saved path, error

    _request_check = Signal(object)
    _request_download = Signal(object, str)

    def __init__(
        self,
        *,
        settings_service=None,
        state=None,
        app_version: str = APP_VERSION,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings_service
        self._state = state
        self._app_version = app_version
        self._thread: QThread | None = None
        self._worker: _UpdateWorker | None = None
        self._checking = False
        self._downloading = ""
        self.last_report: UpdateReport | None = None
        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self.maybe_check_automatically)

    # ── public ──────────────────────────────────────────────────────────

    @property
    def checking(self) -> bool:
        return self._checking

    @property
    def downloading(self) -> str:
        """The project being downloaded, or ""."""
        return self._downloading

    def start_automatic(self) -> None:
        """Arm the timer that asks whether the opt-in daily check is due."""
        self._auto_timer.start(AUTO_FIRST_MS)

    def automatic_enabled(self) -> bool:
        return bool(self._settings is not None and self._settings.settings.update_check_auto)

    @Slot()
    def maybe_check_automatically(self) -> bool:
        """Check if the user opted in and a day has passed. True if it started."""
        if self._auto_timer.interval() != AUTO_POLL_MS:
            self._auto_timer.setInterval(AUTO_POLL_MS)
        now = datetime.datetime.now(datetime.UTC)
        due = update_check.automatic_check_due(
            update_check.load_state(), now, enabled=self.automatic_enabled()
        )
        return due and self.check_now()

    def check_now(self) -> bool:
        """Start a check; False if one is already running."""
        if self._checking:
            return False
        self._ensure_worker()
        assert self._worker is not None
        self._worker.cancel.clear()
        self._checking = True
        self.check_started.emit()
        self._request_check.emit(self.daemon_version())
        return True

    def download(self, status: ComponentStatus, dest_dir: Path) -> bool:
        """Download and verify *status*'s tarball into *dest_dir*."""
        if self._downloading or not status.can_download:
            return False
        self._ensure_worker()
        assert self._worker is not None
        self._worker.cancel.clear()
        self._downloading = status.project
        self.download_started.emit(status.project)
        self._request_download.emit(status, str(dest_dir))
        return True

    def dismiss_notice(self) -> None:
        if self.last_report is not None and self.last_report.offer_key:
            update_check.save_dismissed(self.last_report.offer_key)

    def notice_dismissed(self, report: UpdateReport) -> bool:
        return bool(report.offer_key) and update_check.load_dismissed() == report.offer_key

    def shutdown(self) -> None:
        self._auto_timer.stop()
        if self._thread is None:
            return
        if self._worker is not None:
            self._worker.cancel.set()
            QObject.disconnect(self._worker, None, None, None)
        self._thread.quit()
        if not self._thread.wait(SHUTDOWN_WAIT_MS):
            log.warning("The update check did not stop in time; terminating its thread")
            self._thread.terminate()
            self._thread.wait(1000)
        self._thread = None
        self._worker = None

    # ── internals ───────────────────────────────────────────────────────

    def daemon_version(self) -> str | None:
        """The connected daemon's version; None in demo mode or with no connection."""
        state = self._state
        if state is None or state.mode == OperationMode.DEMO:
            return None
        if state.connection != ConnectionState.CONNECTED or state.capabilities is None:
            return None
        return state.capabilities.daemon_version or None

    def _ensure_worker(self) -> None:
        if self._worker is not None:
            return
        self._thread = QThread(self)
        self._worker = _UpdateWorker(self._app_version)
        self._worker.moveToThread(self._thread)
        self._request_check.connect(self._worker.do_check, Qt.ConnectionType.QueuedConnection)
        self._request_download.connect(self._worker.do_download, Qt.ConnectionType.QueuedConnection)
        self._worker.checked.connect(self._on_checked, Qt.ConnectionType.QueuedConnection)
        self._worker.downloaded.connect(self._on_downloaded, Qt.ConnectionType.QueuedConnection)
        self._thread.start()

    @Slot(object)
    def _on_checked(self, report: UpdateReport) -> None:
        self._checking = False
        self.last_report = report
        self.report_ready.emit(report)

    @Slot(str, str, str)
    def _on_downloaded(self, project: str, saved: str, error: str) -> None:
        self._downloading = ""
        self.download_finished.emit(project, saved, error)
