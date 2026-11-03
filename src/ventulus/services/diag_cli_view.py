"""How the GUI talks about the tests that moved to ``ventulus-diag`` (DEC-503).

The PWM Test Report, characterisation, control-path discovery and the
validation sessions drive fans for minutes or pause curve control for every fan,
so they run from the ``ventulus-diag`` command instead of a GUI button. The GUI
launches none of them; it says where they went, and words the daemon's refusal
when one of them (or any other test) holds the daemon's single diagnostic slot.

Qt-free: the Hardware page renders :data:`HARDWARE_TESTS_TEXT`, and the verify
and calibration workers use :func:`slot_busy_text`.
"""

from __future__ import annotations

#: The first command to run: read-only, and it says whether a test could start.
HARDWARE_TESTS_COMMAND = "ventulus-diag status"

#: What stops a recording validation session (the footer's chip and the panel say it).
SESSION_STOP_COMMAND = "ventulus-diag validation stop"

#: The Hardware page's informational panel. Names the command; launches nothing.
HARDWARE_TESTS_TEXT = (
    "The PWM Test Report, Characterise, Discover Control Path and the validation "
    "sessions (AIO validation, lifecycle recording, thermal observation) run from "
    "the ventulus-diag command, because they drive fans for minutes and pause "
    "curve control for every fan. It asks you to confirm before it changes any "
    "fan speed, and the daemon puts every header back when a test ends. Saved "
    "reports open with ventulus-diag report list, a recording session stops "
    f"with {SESSION_STOP_COMMAND}, and man ventulus-diag lists every command."
)

#: The daemon refused a test because another one holds its diagnostic slot.
SLOT_BUSY_TEXT = (
    "Another hardware test is running, for example one started with "
    "ventulus-diag. The daemon runs one at a time, so try again once it ends; "
    "fan curves resume then."
)


def is_slot_busy_refusal(status: int, code: str, retryable: bool, details: object) -> bool:
    """True for the daemon's ``409`` refusing a test because the slot is held.

    The daemon answers a busy slot with ``409 validation_error``, not retryable
    and with no ``details`` (``verify_slot_refusal``). Its other ``409``s at a
    test's start are told apart first: protection is retryable
    (:func:`ventulus.api.errors.is_soft_safety_refusal`) and an OpenFAN firmware
    update names itself in ``details.reason``.
    """
    from ventulus.api.errors import is_openfan_maintenance_refusal

    return (
        status == 409
        and code == "validation_error"
        and not retryable
        and not is_openfan_maintenance_refusal(details)
    )


def slot_busy_text(err: object) -> str:
    """:data:`SLOT_BUSY_TEXT` when ``err`` is a busy-slot refusal, else ``""``."""
    if is_slot_busy_refusal(
        int(getattr(err, "status", 0) or 0),
        str(getattr(err, "code", "")),
        bool(getattr(err, "retryable", False)),
        getattr(err, "details", None),
    ):
        return SLOT_BUSY_TEXT
    return ""
