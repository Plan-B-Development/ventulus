"""Which window a diagnostic worker's reply belongs to (GUI audit 2026-10-14, #17).

A run worker (characterisation, control-path discovery, OpenFan calibration)
answers every request exactly once, in the order the requests were sent: one
thread, queued connections. The page routes each answer to the run window it
has open. That is not enough once windows can close mid-run: a reply can still
be owed to a window that has closed (a poll in flight, or the "Stop" chosen on
closing) when the next window opens and asks for the daemon's run. Without
counting, the first reply to arrive is taken as the new window's answer, so a
stale error is read as "could not read the run" and the real answer is then
mistaken for an ordinary poll, and a failed stop is never reported.

The ledger counts requests sent and answers received. Answers owed to a closed
window go to the page, and the last of them, when the window closed with
"Stop", is the stop's own answer, which is the one the page reports on.

Qt-free.
"""

from __future__ import annotations

from enum import Enum


class ReplyRoute(Enum):
    #: Deliver to the open window (if any).
    WINDOW = "window"
    #: Owed to a window that has closed, or sent before this one opened: drop.
    EARLIER = "earlier"
    #: The answer to the "Stop" a closed window sent; the page reports a failure.
    STOP_ANSWER = "stop_answer"


class RunReplyLedger:
    """Counts one worker's outstanding requests to route its in-order replies."""

    def __init__(self) -> None:
        self._outstanding = 0
        #: Replies still to arrive that no open window asked for.
        self._skip = 0
        #: Replies until the closed window's stop is answered; 0 when none.
        self._stop_in = 0

    @property
    def outstanding(self) -> int:
        return self._outstanding

    def sent(self, *_args) -> None:
        """One request went to the worker (connected to every request signal)."""
        self._outstanding += 1

    def window_opened(self) -> None:
        """Everything already in flight answers something sent before this window."""
        self._skip = self._outstanding

    def window_closed(self, *, stop_sent: bool) -> None:
        """Everything still in flight belonged to the window that closed.

        ``stop_sent``: it closed with "Stop", whose cancel was the last request
        it sent, so the last of those replies is the stop's answer.
        """
        self._skip = self._outstanding
        if stop_sent:
            self._stop_in = self._outstanding
        # Otherwise an earlier window's stop, still unanswered, keeps its place.

    def received(self) -> ReplyRoute:
        """Account one reply and say where it goes."""
        self._outstanding = max(0, self._outstanding - 1)
        if self._skip == 0:
            return ReplyRoute.WINDOW
        self._skip -= 1
        if self._stop_in:
            self._stop_in -= 1
            if self._stop_in == 0:
                return ReplyRoute.STOP_ANSWER
        return ReplyRoute.EARLIER
