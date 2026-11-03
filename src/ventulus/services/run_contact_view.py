"""What a page says when "Stop" on closing a run's window was refused (`PTA-v`, `U11`).

The OpenFAN calibration window watches a run the daemon owns. The live-contact
wording the characterisation and control-path dialogs shared left with them
(DEC-503: those tests run from ``ventulus-diag``).

Qt-free.
"""

from __future__ import annotations


def stop_on_close_failed_text(what: str, detail: str) -> str:
    """What the page says when "Stop" on closing a run's window was refused or lost.

    The window has closed by the time the reply lands, so the page that opened
    it shows this instead. ``what`` names the diagnostic ("calibration");
    ``detail`` is the request's error.
    """
    detail = detail.strip()
    if detail and detail[-1] not in ".!?":
        detail += "."
    return (
        f"Could not stop the {what}: {detail} It may still be running; "
        "reopen its window to see it or stop it."
    )
