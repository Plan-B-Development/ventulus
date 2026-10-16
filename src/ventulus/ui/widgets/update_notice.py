"""The window's dismissible "update available" notice (DEC-499)."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ventulus.ui.components.buttons import make_button


class UpdateNotice(QWidget):
    """A strip naming the offered versions, with Details and Dismiss.

    Shown only after a check found a newer release; a dismissal holds until a
    newer release than the dismissed one appears (``UpdateController``).
    """

    details_requested = Signal()
    dismissed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MainWindow_Notice_update")
        self.setVisible(False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(8)
        self._label = QLabel("")
        self._label.setObjectName("MainWindow_Label_updateNotice")
        self._label.setWordWrap(True)
        self._label.setProperty("class", "InfoChip")
        layout.addWidget(self._label, 1)
        details = make_button("Details", "secondary", object_name="MainWindow_Btn_updateDetails")
        details.clicked.connect(self.details_requested)
        layout.addWidget(details)
        dismiss = make_button("Dismiss", "secondary", object_name="MainWindow_Btn_updateDismiss")
        dismiss.clicked.connect(self._on_dismiss)
        layout.addWidget(dismiss)

    def show_notice(self, text: str) -> None:
        self._label.setText(text)
        self.setVisible(bool(text))

    def text(self) -> str:
        return self._label.text()

    def _on_dismiss(self) -> None:
        self.setVisible(False)
        self.dismissed.emit()
