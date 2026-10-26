"""Duty drift, as the System State page reports it (DEC-404 S4-3, S4-12).

Daemon 2.53.0+ (DEC-406, capability ``control.duty_reconciliation``) reads back
an hwmon write it would coalesce and rewrites a duty something else moved. After
three corrections the next tick contradicts, it stops, and flags the header
``duty_not_holding``. Both facts ride every hwmon ``/fans``/``/poll`` entry.

What the page does with them — the user's choices, S4-3 and S4-12:

* **a condition card only while a header is not holding**, one per header, one
  per episode. The episode's identity is the daemon's correction count at the
  give-up, because the count cannot move while the daemon has stopped
  correcting: a new episode needs new corrections, so a fresh give-up is a new
  occurrence and a dismissal of the last one cannot hide it;
* **corrections that held are a reading**, a count in the Interference Monitor,
  never an alert;
* **the card counts everywhere the page's conditions count** — the "N ACTION
  REQUIRED" pill and the pop-out report — so the two cannot disagree (DEC-379).
  Every builder therefore takes :class:`DutyDriftState` as a REQUIRED keyword:
  a caller that forgot it would fail loudly instead of quietly reporting "no
  drift", which is the default-argument trap DEC-379 names.

Two more per-fan facts ride the same poll and reach the same surfaces through
this state, so they need no second required keyword:

* ``write_failing`` (hwmon and OpenFan): the daemon's last writes to the fan all
  failed. A card while it lasts; the daemon clears it when a write lands, or by
  age once it stops writing the fan.
* ``found_in_manual_mode`` (hwmon): the header was already in manual mode when
  the daemon first took it, so a stop gives it back in manual mode rather than
  to the BIOS — usually another fan program still holding it. A warning, for
  the daemon's lifetime.

Each has one shape, so its card has no fingerprint: a dismissal holds while
the condition does, and is pruned with the keys once it clears.

Qt-free.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass

#: Condition keys start with this; the rest is a digest of the header's stable
#: id, because an id carries ':' and may carry '#', which a silence token
#: cannot hold (`health_ack.parse_token`).
DRIFT_KEY_PREFIX = "duty_not_holding_"
WRITE_FAILING_KEY_PREFIX = "fan_write_failing_"
FOUND_MANUAL_KEY_PREFIX = "found_in_manual_mode_"

_MIGRATING_CHECK_URL = (
    "https://github.com/Plan-B-Development/ventulus/blob/main/manual/migrating.md"
    "#check-that-nothing-still-holds-a-header"
)
_CANNOT_CONTROL_URL = (
    "https://github.com/Plan-B-Development/ventulus/blob/main/"
    "manual/hardware-troubleshooting.md"
    "#a-fans-speed-shows-but-the-fan-cannot-be-controlled"
)


@dataclass(frozen=True)
class DutyDrift:
    """One header the daemon has stopped correcting."""

    header_id: str
    name: str
    #: The daemon's count when it gave up — the episode's identity. ``None``
    #: when the daemon flagged the header without a count (never expected).
    corrections: int | None


@dataclass(frozen=True)
class FanFlag:
    """One fan a poll field flags."""

    fan_id: str
    name: str


@dataclass(frozen=True)
class DutyDriftState:
    """Everything the page says about drift, from one ``/fans`` poll."""

    #: The daemon publishes the fields at all (it has DEC-406). Without them
    #: the page says nothing — absence is "this daemon does not reconcile",
    #: never "no drift".
    reported: bool
    not_holding: tuple[DutyDrift, ...]
    #: ``(header id, display name, corrections since the daemon started)`` for
    #: every hwmon header with at least one correction.
    corrections: tuple[tuple[str, str, int], ...]
    #: Fans whose writes the daemon reports failing (hwmon and OpenFan).
    write_failing: tuple[FanFlag, ...] = ()
    #: hwmon headers the daemon found in manual mode at its first take.
    found_in_manual_mode: tuple[FanFlag, ...] = ()


NO_DRIFT = DutyDriftState(reported=False, not_holding=(), corrections=())


def duty_drift_state(fans: Iterable[object], name_of: Callable[[str], str]) -> DutyDriftState:
    """Read the drift fields off the app's parsed ``FanReading`` list."""
    reported = False
    not_holding: list[DutyDrift] = []
    corrections: list[tuple[str, str, int]] = []
    write_failing: list[FanFlag] = []
    found_in_manual_mode: list[FanFlag] = []
    for fan in sorted(fans, key=lambda f: getattr(f, "id", "")):
        source = getattr(fan, "source", "")
        fid = str(getattr(fan, "id", ""))
        # Absent from an older daemon and on a GPU entry: only True flags.
        if source in ("hwmon", "openfan") and getattr(fan, "write_failing", None) is True:
            write_failing.append(FanFlag(fid, name_of(fid)))
        if source != "hwmon":
            continue
        if getattr(fan, "found_in_manual_mode", None) is True:
            found_in_manual_mode.append(FanFlag(fid, name_of(fid)))
        count = getattr(fan, "duty_corrections", None)
        flag = getattr(fan, "duty_not_holding", None)
        if count is None and flag is None:
            continue
        reported = True
        if isinstance(count, int) and not isinstance(count, bool) and count > 0:
            corrections.append((fid, name_of(fid), count))
        if flag is True:
            not_holding.append(
                DutyDrift(
                    header_id=fid,
                    name=name_of(fid),
                    corrections=count if isinstance(count, int) else None,
                )
            )
    return DutyDriftState(
        reported,
        tuple(not_holding),
        tuple(corrections),
        write_failing=tuple(write_failing),
        found_in_manual_mode=tuple(found_in_manual_mode),
    )


def _digest(fan_id: str) -> str:
    return hashlib.sha256(fan_id.encode("utf-8")).hexdigest()[:12]


def drift_key(header_id: str) -> str:
    return DRIFT_KEY_PREFIX + _digest(header_id)


def write_failing_key(fan_id: str) -> str:
    return WRITE_FAILING_KEY_PREFIX + _digest(fan_id)


def found_manual_key(header_id: str) -> str:
    return FOUND_MANUAL_KEY_PREFIX + _digest(header_id)


def is_drift_key(key: str) -> bool:
    """Any per-fan condition from the poll: each names its fan the same way."""
    return key.startswith((DRIFT_KEY_PREFIX, WRITE_FAILING_KEY_PREFIX, FOUND_MANUAL_KEY_PREFIX))


def drift_problems(state: DutyDriftState, *, doc_url: str, doc_title: str) -> list[dict]:
    """Condition dicts in the readiness shape, one per header not holding, then
    one per fan whose writes fail, then one per header found in manual mode.

    The not-holding guide link is the caller's (``readiness_report``, beside the
    BIOS-reclaim condition — the same class of problem, another writer on the
    header), so the URL has one definition. The other two link the manual
    sections that answer them.

    ``label`` and ``fix`` are GUI-authored only, per that shape's contract —
    they reach rich text unescaped. The fan's name is daemon- or user-supplied,
    so it travels separately as ``subject`` and every consumer escapes it.
    """
    out: list[dict] = []
    for drift in state.not_holding:
        out.append(
            {
                "key": drift_key(drift.header_id),
                "label": "Fan duty is not holding",
                "fix": (
                    "Something other than Ventulus keeps changing this fan's duty. "
                    "The daemon corrected it three times, the change came back each "
                    "time, so it has stopped rewriting it; it corrects it again once the "
                    "duty agrees or the command changes. Look for the motherboard's own "
                    "fan control (BIOS/EC) or another fan-control program acting on this "
                    "header, and turn it off for it."
                ),
                "doc_url": doc_url,
                "doc_title": doc_title,
                "severity": "warn",
                "subject": drift.name,
                "header_id": drift.header_id,
                "corrections": drift.corrections,
                # The episode: see the module docstring.
                "fingerprint": "" if drift.corrections is None else f"c{drift.corrections}",
            }
        )
    for fan in state.write_failing:
        out.append(
            {
                "key": write_failing_key(fan.fan_id),
                "label": "Fan speed cannot be set",
                "fix": (
                    "The daemon's last writes to this fan all failed, so the fan may "
                    "not be at the speed Ventulus chose, and a thermal emergency cannot "
                    "speed it up either. The daemon's journal names the error: open the "
                    "Logs page's Journal tab and look for 'write failed'. 'Read-only "
                    "file system' means the service's sandbox does not cover this "
                    "device; an I/O error usually means the driver or the board refuses "
                    "the write. This clears by itself once a write lands."
                ),
                "doc_url": _CANNOT_CONTROL_URL,
                "doc_title": "Hardware Troubleshooting",
                # Losing control of a fan is ACTION REQUIRED, not CRITICAL: that
                # tier is kept for a risk of damaging hardware (manual § Conditions).
                "severity": "warn",
                "subject": fan.name,
                "header_id": fan.fan_id,
                "fingerprint": "",
            }
        )
    for fan in state.found_in_manual_mode:
        out.append(
            {
                "key": found_manual_key(fan.fan_id),
                "label": "Header was already in manual mode",
                "fix": (
                    "When Ventulus first took this header, something had already set "
                    "it to manual mode: another fan-control program, a script, or "
                    "pwmconfig. Ventulus gives every header back exactly as it found "
                    "it, so when it stops it leaves this one in manual mode at the "
                    "speed it had then, and the BIOS fan curve does not take it back. "
                    "Stop and disable the other program, then reboot: the BIOS sets "
                    "every header up afresh as the machine starts, and Ventulus then "
                    "records that mode instead. If this card is back after a reboot "
                    "with nothing else running, your board starts this header in "
                    "manual mode itself, and nothing needs doing."
                ),
                "doc_url": _MIGRATING_CHECK_URL,
                "doc_title": "Migrating from another fan program",
                "severity": "warn",
                "subject": fan.name,
                "header_id": fan.fan_id,
                "fingerprint": "",
            }
        )
    return out


def corrections_line(state: DutyDriftState) -> str:
    """The Interference Monitor's reading — "" when there is nothing to say."""
    if not state.reported or not state.corrections:
        return ""
    parts = ", ".join(f"{name} ({count})" for _hid, name, count in state.corrections)
    return (
        f"Duty corrections since the daemon started: {parts}. Each time, something "
        "else had changed the fan's duty and the daemon put it back."
    )
