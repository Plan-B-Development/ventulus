"""Run 1 (`G20`): the session dialog fits the screen and says what it is doing.

Covers `P8-ba` (ModalDialog had no scroll area and no screen clamp, so the Stop
button went off the bottom of the display), `P8-bb` (the evidence rows and the
poll summary were computed and rendered nowhere), `P8-bc` (Stop/Cancel wording),
`P8-bd` (the dialog blocked the page its own instructions send you to) and
`P8-w` (no single-poll-in-flight guard).

**Every size assertion here is a RELATIONSHIP measured at runtime, never a pixel
count.** A literal derived on one machine reddened all three CI legs once
(the project rulebook § Hard-won lessons), because CI's font set differs and every derived
metric moves with it. `tests/conftest.py` registers the bundled DM Sans, so the
metrics are at least stable — but a constant would still be a constant, and the
thing under test is "smaller than its content" / "fits the screen", which is a
relationship in the first place.
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from ventulus.api.models import (
    VALIDATION_KIND_THERMAL,
    VALIDATION_STATE_COMPLETED,
    VALIDATION_STATE_RECORDING,
    ValidationSessionSummary,
)
from ventulus.ui.components.dialog import ModalDialog
from ventulus.ui.components.footer import StatusFooter

#: Far taller than any screen a test can run on, so "does it scroll" is not a
#: question about this machine's resolution.
_TALLER_THAN_ANY_SCREEN = 6000


def _tall_dialog(qtbot, **kw) -> tuple[ModalDialog, QWidget, QPushButton]:
    dlg = ModalDialog("Tall", **kw)
    qtbot.addWidget(dlg)
    tall = QLabel("content")
    tall.setMinimumHeight(_TALLER_THAN_ANY_SCREEN)
    dlg.body_layout().addWidget(tall)
    stop = dlg.add_footer_button("Stop", "secondary", object_name="Test_Btn_stop")
    return dlg, tall, stop


class TestModalDialogFitsTheScreen:
    """`P8-ba`. The defect: the layout minimum WAS the window minimum."""

    def test_content_taller_than_the_screen_does_not_become_a_window_minimum(self, qtbot):
        """The relationship that was inverted before the fix.

        Asserted against the body's own minimum rather than a number, so it means
        the same thing in any font: the window must be allowed to be smaller than
        its content, which is precisely what a scroll area buys and what the bare
        `QVBoxLayout` forbade.
        """
        dlg, tall, _ = _tall_dialog(qtbot)
        assert tall.minimumSizeHint().height() >= _TALLER_THAN_ANY_SCREEN
        assert dlg.minimumSizeHint().height() < tall.minimumSizeHint().height(), (
            "the dialog's minimum still tracks its content — the scroll area is "
            "not taking effect, and tall content is again a floor the window "
            "cannot go below"
        )

    def test_a_resize_smaller_than_the_content_is_honoured(self, qtbot):
        """Before the fix `resize(700, 400)` returned 767x2496 — measured.

        This is the user-visible half: the window could not be shrunk, so the
        footer stayed off-screen no matter what the user did.
        """
        dlg, tall, _ = _tall_dialog(qtbot)
        dlg.show()
        qtbot.waitExposed(dlg)
        target = dlg.minimumSizeHint().height() + 40
        dlg.resize(dlg.width(), target)
        assert dlg.height() == target
        assert dlg.height() < tall.minimumSizeHint().height()

    def test_the_shown_dialog_fits_the_screen_it_opened_on(self, qtbot):
        """`availableGeometry`, so a panel or taskbar is excluded.

        The realised height of a shown widget, not `sizeHint()` — those differ,
        and only the realised one is what the user actually sees.
        """
        dlg, _, _ = _tall_dialog(qtbot)
        dlg.show()
        qtbot.waitExposed(dlg)
        avail = dlg.screen().availableGeometry()
        assert dlg.height() <= avail.height()
        assert dlg.width() <= avail.width()

    def test_an_oversized_explicit_resize_is_clamped_on_show(self, qtbot):
        """A subclass may `resize()` itself past the screen (alert_center does).

        The scroll area alone does not cover this: it removes the *minimum*, and
        an explicit oversized `resize` is neither a minimum nor a size hint.
        """
        dlg, _, _ = _tall_dialog(qtbot)
        avail = dlg.screen().availableGeometry()
        dlg.resize(avail.width() * 3, avail.height() * 3)
        dlg.show()
        qtbot.waitExposed(dlg)
        assert dlg.height() <= avail.height()
        assert dlg.width() <= avail.width()

    def test_the_footer_is_outside_the_scroll_area_so_stop_cannot_scroll_away(self, qtbot):
        """Structural, and the reason the fix is not "wrap everything".

        A footer INSIDE the scroll area would satisfy every size assertion above
        and still hide Stop below the fold — the exact failure being fixed, one
        layer in. So this asserts ancestry, which is the property that makes the
        buttons unconditionally reachable.
        """
        dlg, _, stop = _tall_dialog(qtbot)
        scrolled = dlg._scroll.widget()
        assert dlg._body is scrolled, "the body must be the scrolled widget"
        assert not scrolled.isAncestorOf(stop), (
            "a footer button is inside the scroll area — it will scroll out of "
            "reach exactly like the body content"
        )
        assert not scrolled.isAncestorOf(dlg._title), "the header must not scroll either"

    def test_the_body_really_scrolls_rather_than_clipping(self, qtbot):
        """A scroll area that cannot scroll would hide the content instead."""
        dlg, _, _ = _tall_dialog(qtbot)
        dlg.show()
        qtbot.waitExposed(dlg)
        assert dlg._scroll.verticalScrollBar().maximum() > 0


class TestModalityIsOptional:
    """`P8-bd`. The scrim and the modality are one decision, not two."""

    def test_a_modeless_dialog_is_not_modal_and_paints_no_scrim(self, qtbot):
        host = QWidget()
        host.resize(400, 300)
        qtbot.addWidget(host)
        dlg = ModalDialog("Modeless", parent=host, modal=False)
        qtbot.addWidget(dlg)
        assert dlg.isModal() is False
        dlg._ensure_scrim()
        assert dlg._scrim is None, (
            "a veil over a window the user can still click is a lie about what is reachable"
        )

    def test_the_default_is_still_modal_with_a_scrim(self, qtbot):
        """The opposite branch, or the assertion above passes vacuously."""
        host = QWidget()
        host.resize(400, 300)
        qtbot.addWidget(host)
        dlg = ModalDialog("Modal", parent=host)
        qtbot.addWidget(dlg)
        assert dlg.isModal() is True
        dlg._ensure_scrim()
        assert dlg._scrim is not None
        dlg._remove_scrim()


class TestFooterAnnouncesARecordingSession:
    """`P8-bb` second half: the session was invisible once the dialog closed."""

    def _summary(self, **kw) -> ValidationSessionSummary:
        base = {
            "session_id": "vs-1",
            "kind": VALIDATION_KIND_THERMAL,
            "state": VALIDATION_STATE_RECORDING,
            "sample_count": 42,
        }
        base.update(kw)
        return ValidationSessionSummary(**base)

    def test_a_recording_session_is_announced(self, qtbot):
        footer = StatusFooter()
        qtbot.addWidget(footer)
        footer.set_validation_session(self._summary())
        assert footer._session_btn.isVisibleTo(footer)
        assert "thermal observation" in footer._session_btn.text().lower()
        assert "42" in footer._session_btn.text()

    def test_a_finished_session_is_not(self, qtbot):
        """The daemon serves its most recent COMPLETED session indefinitely, so
        keying on presence would pin a permanent chip after the first run."""
        footer = StatusFooter()
        qtbot.addWidget(footer)
        footer.set_validation_session(self._summary())
        assert footer._session_btn.isVisibleTo(footer)
        footer.set_validation_session(self._summary(state=VALIDATION_STATE_COMPLETED))
        assert not footer._session_btn.isVisibleTo(footer)

    def test_no_session_at_all_is_not_announced(self, qtbot):
        footer = StatusFooter()
        qtbot.addWidget(footer)
        footer.set_validation_session(None)
        assert not footer._session_btn.isVisibleTo(footer)

    def test_losing_the_daemon_retracts_the_claim(self, qtbot):
        """A stale "Recording" would otherwise follow the user across every page."""
        footer = StatusFooter()
        qtbot.addWidget(footer)
        footer.set_validation_session(self._summary())
        footer.set_live(False)
        assert not footer._session_btn.isVisibleTo(footer)

    def test_an_unknown_kind_is_rendered_rather_than_dropped(self, qtbot):
        """The 273-i rule: a newer daemon must not make a state vanish."""
        footer = StatusFooter()
        qtbot.addWidget(footer)
        footer.set_validation_session(self._summary(kind="some_future_kind"))
        assert footer._session_btn.isVisibleTo(footer)
        assert footer._session_btn.text().strip()


class TestExportIsOneButtonWithAMenu:
    """`P8-bh`. The footer, not the content, was setting the minimum WIDTH.

    Measured before this change: dialog minimum width 840px against a body
    needing 184. Two export buttons were 214px of that, and 73px more came from
    DEC-337's own truthfulness rename (Stop/Cancel Session -> Stop & Save /
    Stop & Mark Cancelled), which took the footer from 767 to 840. So part of
    this row is a regression that change introduced, not merely old untidiness.
    """
