"""The support bundle, shown whole before it leaves the app.

The Logs page builds the bundle off the GUI thread and hands the finished text
here; nothing is written until **Save…**, and **Copy** puts the same text on the
clipboard. One dialog per page, reused for every export, as the readiness
report's is.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ventulus.ui.components.a11y import name_value_control
from ventulus.ui.components.buttons import make_button

INTRO_TEXT = (
    "This is the whole file. Read it before you share it: it names your hardware, "
    "and may name your folders. Nothing is sent anywhere. Save it or copy it, then "
    "attach it to your report."
)


class SupportBundlePreviewDialog(QDialog):
    """Read-only view of one bundle, with Save and Copy."""

    #: The user chose **Save…**; the page asks where and writes the text.
    save_requested = Signal()
    #: The text is on the clipboard.
    copied = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SupportBundlePreview_Dialog")
        self.setWindowTitle("Support Bundle")
        self.resize(760, 640)
        #: The text as built: what Save writes and Copy copies, never read back
        #: out of the editor.
        self._bundle_text = ""

        layout = QVBoxLayout(self)
        intro = QLabel(INTRO_TEXT)
        intro.setObjectName("SupportBundlePreview_Label_intro")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self._text = QPlainTextEdit()
        self._text.setObjectName("SupportBundlePreview_Text")
        self._text.setReadOnly(True)
        self._text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        name_value_control(self._text, "Support bundle contents")
        font = self._text.font()
        font.setFamily("monospace")
        self._text.setFont(font)
        layout.addWidget(self._text, 1)

        self._status = QLabel("")
        self._status.setObjectName("SupportBundlePreview_Label_status")
        self._status.setProperty("class", "CardMeta")
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        buttons = QHBoxLayout()
        self._copy_btn = make_button(
            "Copy", "secondary", object_name="SupportBundlePreview_Btn_copy"
        )
        self._copy_btn.clicked.connect(self._copy)
        buttons.addWidget(self._copy_btn)
        buttons.addStretch(1)
        close_btn = make_button("Close", "ghost", object_name="SupportBundlePreview_Btn_close")
        close_btn.clicked.connect(self.reject)
        buttons.addWidget(close_btn)
        self._save_btn = make_button(
            "Save…", "primary", object_name="SupportBundlePreview_Btn_save"
        )
        self._save_btn.clicked.connect(self.save_requested)
        buttons.addWidget(self._save_btn)
        layout.addLayout(buttons)

    def set_text(self, text: str) -> None:
        """Show a newly built bundle, clearing what the last one said."""
        self._bundle_text = text
        self._text.setPlainText(text)
        self._status.setText("")

    def text(self) -> str:
        return self._bundle_text

    def show_status(self, message: str) -> None:
        self._status.setText(message)

    def set_saving(self, saving: bool) -> None:
        """Hold Save while a write is in flight, so one press writes one file."""
        self._save_btn.setEnabled(not saving)
        if saving:
            self._status.setText("Saving…")

    def _copy(self) -> None:
        clip = QApplication.clipboard()
        if clip is None:
            return
        clip.setText(self.text())
        self.show_status("Copied to the clipboard.")
        self.copied.emit()
