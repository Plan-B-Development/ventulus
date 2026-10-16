"""About dialog — brand, versions, credits, and the update check's entry point."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ventulus.constants import APP_NAME, APP_VERSION
from ventulus.services.update_view import about_versions


class AboutDialog(QDialog):
    """About dialog with version info and credits."""

    def __init__(
        self,
        parent=None,
        *,
        daemon_version: str | None = None,
        on_check_updates: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        # DEC-258: was setFixedSize, which cannot hold its own content once the
        # user raises the theme's base font (7-16pt is user-adjustable). A
        # minimum keeps the dialog from collapsing while letting it grow.
        self.setMinimumSize(480, 320)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Title
        title = QLabel(APP_NAME)
        title.setProperty("class", "PageTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Version
        version_label = QLabel(f"Version {APP_VERSION}")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_label.setProperty("class", "PageSubtitle")
        layout.addWidget(version_label)

        # DEC-499: both components' versions, the pair an update check compares.
        versions = QLabel(" · ".join(about_versions(APP_VERSION, daemon_version)))
        versions.setObjectName("About_Label_versions")
        versions.setAlignment(Qt.AlignmentFlag.AlignCenter)
        versions.setProperty("class", "PageSubtitle")
        layout.addWidget(versions)

        # Tagline
        tagline = QLabel("Fan control for Linux")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tagline.setStyleSheet("font-style: italic;")
        layout.addWidget(tagline)

        # Credits
        credits_label = QLabel("Open-source fan control")
        credits_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        credits_label.setProperty("class", "PageSubtitle")
        layout.addWidget(credits_label)

        # Tech info
        tech = QLabel("PySide6 (Qt6) | Python | Linux")
        tech.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tech.setProperty("class", "PageSubtitle")
        layout.addWidget(tech)

        layout.addStretch()

        # Close button
        btn_row = QHBoxLayout()
        if on_check_updates is not None:
            check_btn = QPushButton("Check for updates")
            check_btn.setObjectName("About_Btn_checkUpdates")
            check_btn.setToolTip("Open Settings ▸ Updates and check now")
            check_btn.clicked.connect(self.accept)
            check_btn.clicked.connect(on_check_updates)
            btn_row.addWidget(check_btn)
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setObjectName("About_Btn_close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)
