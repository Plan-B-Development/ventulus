"""Deliberate intent before a test drives fans (DEC-503 decision 4).

Two gates, both required for what they cover:

* **Every** command that drives fans prints what it will touch and needs a typed
  ``yes`` on a terminal, or :data:`CONFIRM_FLAG` when not on one. Without either
  it does nothing: a script that runs the tool by accident changes no fan.
* A test that **can stop a fan** (the stall/restart probe) also needs a
  per-header acknowledgement: typing ``stop`` for that header on a terminal, or
  :data:`ALLOW_STOP_FLAG` naming it. That is what the daemon's
  ``acknowledge_below_floor`` stands for, and the tool sends it only for a header
  acknowledged here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from ventulus.diag.console import Console

CONFIRM_FLAG = "--yes-change-fan-speeds"
ALLOW_STOP_FLAG = "--allow-fan-stop"

SUPERVISE_NOTE = (
    "Stay at the machine while it runs. Ctrl-C stops the test: the daemon ends it and "
    "puts the header back. The daemon also puts the header back if this tool is "
    "killed or the terminal is closed."
)


def describe(console: Console, title: str, lines: Iterable[str], warnings: Iterable[str]) -> None:
    console.out(title)
    for line in lines:
        console.out(f"  • {line}")
    warnings = list(warnings)
    if warnings:
        console.out("")
        for w in warnings:
            console.out(f"  ! {w}")
    console.out("")
    console.out(SUPERVISE_NOTE)
    console.out("")


def confirm_writes(console: Console, *, flag_given: bool) -> str:
    """``""`` when confirmed, else why not (the run must not start)."""
    if flag_given:
        console.out(f"Confirmed by {CONFIRM_FLAG}.")
        return ""
    if not console.interactive:
        return (
            "Not started: this changes fan speeds and needs confirmation. Run it on a "
            f"terminal and type yes, or pass {CONFIRM_FLAG}."
        )
    answer = console.ask("Type yes to start, anything else to stop: ")
    if answer is not None and answer.strip().lower() == "yes":
        return ""
    return "Not started: not confirmed."


def confirm_fan_stops(
    console: Console,
    targets: Mapping[str, str],
    *,
    allowed: Iterable[str],
) -> tuple[frozenset[str], str]:
    """Ask for each header whose fan may stop. Returns ``(acknowledged, refusal)``.

    *targets* maps header id to display name. A header named in *allowed* (the
    :data:`ALLOW_STOP_FLAG` values) is acknowledged without a prompt; any other
    needs ``stop`` typed for it on a terminal. One missing acknowledgement
    refuses the whole run: the user asked for that test, so silently dropping it
    would report a plan they did not get.
    """
    allowed_ids = set(allowed)
    acknowledged: set[str] = set()
    for header_id, name in targets.items():
        if header_id in allowed_ids:
            acknowledged.add(header_id)
            continue
        if not console.interactive:
            return frozenset(), (
                f"Not started: the stall/restart probe can stop the fan on {name}. Pass "
                f"{ALLOW_STOP_FLAG} {header_id} to allow it."
            )
        answer = console.ask(
            f"The fan on {name} ({header_id}) may stop for a short time. Type stop to allow it: "
        )
        if answer is None or answer.strip().lower() != "stop":
            return frozenset(), f"Not started: the fan stop on {name} was not allowed."
        acknowledged.add(header_id)
    return frozenset(acknowledged), ""
