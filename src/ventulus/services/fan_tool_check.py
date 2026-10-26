"""Detect other fan-control software on this machine.

Two programs writing one fan header fight each other, and the daemon hands each
header back as it first found it, so a header another tool still holds goes back
to that tool's speed. This looks for the known ones the way the manual's
*Migrating from Another Fan Program* tells a user to: their systemd services,
and the PID file ``fancontrol`` writes when it is started by hand.

Read-only and unprivileged, like ``daemon_service_check``: one ``systemctl
show`` over a fixed allow-list of unit names, and two small reads under
``/run`` and ``/proc``. No fan, hwmon or sensor file is touched. Degrades to
``systemd_checked=False`` when ``systemctl`` is missing or does not answer.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

#: (unit, name the user knows it by). CoreCtrl has no system service to find.
KNOWN_FAN_TOOL_UNITS: tuple[tuple[str, str], ...] = (
    ("fancontrol.service", "fancontrol"),
    ("coolercontrold.service", "CoolerControl"),
    ("fan2go.service", "fan2go"),
    ("thinkfan.service", "thinkfan"),
    ("lactd.service", "LACT"),
)

FANCONTROL_PID_FILE = Path("/run/fancontrol.pid")

#: How long the one ``systemctl show`` may take.
SYSTEMCTL_TIMEOUT_S = 1.5

MIGRATING_GUIDE_URL = "https://github.com/Plan-B-Development/ventulus/blob/main/manual/migrating.md"

# systemd's ActiveState values for a unit that is up or on its way up or down.
_RUNNING_STATES = frozenset({"active", "reloading", "activating", "deactivating", "refreshing"})
# UnitFileState values that start the unit at boot (`static` units do not start
# on their own).
_BOOT_STATES = frozenset({"enabled", "enabled-runtime", "alias"})


@dataclass(frozen=True)
class FanToolUnit:
    """One installed unit from :data:`KNOWN_FAN_TOOL_UNITS`, as systemd reports it."""

    unit: str
    name: str
    active_state: str
    unit_file_state: str

    @property
    def running(self) -> bool:
        return self.active_state in _RUNNING_STATES

    @property
    def starts_at_boot(self) -> bool:
        return self.unit_file_state in _BOOT_STATES


@dataclass(frozen=True)
class FanToolState:
    """What :func:`check_fan_tools` found.

    Attributes:
        systemd_checked: ``systemctl`` answered; when False, ``units`` is empty
            because nothing could be read, not because nothing is installed.
        units: the known units that are installed (masked ones included), in
            :data:`KNOWN_FAN_TOOL_UNITS` order.
        fancontrol_pid: ``"absent"`` (no PID file), ``"running"`` (it names a
            live ``fancontrol``), ``"stale"`` (it names no ``fancontrol``: one was
            killed without restoring its fans) or ``"unreadable"``.
    """

    systemd_checked: bool
    units: tuple[FanToolUnit, ...] = ()
    fancontrol_pid: str = "absent"

    @property
    def running(self) -> tuple[FanToolUnit, ...]:
        return tuple(u for u in self.units if u.running)

    @property
    def starting_at_boot(self) -> tuple[FanToolUnit, ...]:
        """Units that start at boot but are not running now."""
        return tuple(u for u in self.units if u.starts_at_boot and not u.running)

    @property
    def fancontrol_by_hand(self) -> bool:
        """A ``fancontrol`` is running outside its service."""
        return self.fancontrol_pid == "running" and not any(
            u.unit == "fancontrol.service" for u in self.running
        )

    @property
    def any_running(self) -> bool:
        return bool(self.running) or self.fancontrol_by_hand

    @property
    def found_anything(self) -> bool:
        """Something the user should act on: a tool running or starting at
        boot, or a ``fancontrol`` that was killed."""
        return self.any_running or bool(self.starting_at_boot) or self.fancontrol_pid == "stale"

    def to_bundle(self) -> dict:
        """The support bundle's section: unit names and systemd states only."""
        return {
            "systemd_checked": self.systemd_checked,
            "units": [
                {
                    "unit": u.unit,
                    "active_state": u.active_state,
                    "unit_file_state": u.unit_file_state,
                }
                for u in self.units
            ],
            "fancontrol_pid_file": self.fancontrol_pid,
        }


def check_fan_tools(
    *,
    systemctl_path: str | None = None,
    pid_file: Path = FANCONTROL_PID_FILE,
    proc_dir: Path = Path("/proc"),
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    timeout_secs: float = SYSTEMCTL_TIMEOUT_S,
) -> FanToolState:
    """Probe this machine for the known fan-control programs.

    ``systemctl_path``, ``pid_file``, ``proc_dir`` and ``run`` are for tests;
    production calls :func:`probe_fan_tools`. Blocks for up to ``timeout_secs``
    on a stuck systemd, so call it off the GUI thread.
    """
    resolved = systemctl_path if systemctl_path is not None else shutil.which("systemctl")
    units = _query_units(resolved, run, timeout_secs) if resolved else None
    return FanToolState(
        systemd_checked=units is not None,
        units=units or (),
        fancontrol_pid=_fancontrol_pid_state(pid_file, proc_dir),
    )


def probe_fan_tools() -> FanToolState:
    """This machine's state. Tests pin this entry point (``tests/conftest.py``)."""
    return check_fan_tools()


def _query_units(
    systemctl: str, run: Callable[..., subprocess.CompletedProcess], timeout_secs: float
) -> tuple[FanToolUnit, ...] | None:
    """One ``systemctl show`` for every known unit, or ``None`` if it failed.

    systemd prints one block per unit, in argument order and separated by a
    blank line, and reports a unit that is not installed as
    ``LoadState=not-found`` rather than failing.
    """
    names = [unit for unit, _ in KNOWN_FAN_TOOL_UNITS]
    try:
        result = run(
            [
                systemctl,
                "show",
                "--property=LoadState,ActiveState,UnitFileState",
                "--",
                *names,
            ],
            capture_output=True,
            text=True,
            timeout=timeout_secs,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.debug("systemctl show probe failed: %s", exc)
        return None
    if result.returncode != 0:
        log.debug("systemctl show exited %s", result.returncode)
        return None
    blocks = result.stdout.strip().split("\n\n")
    if len(blocks) != len(KNOWN_FAN_TOOL_UNITS):
        log.debug("systemctl show printed %d blocks for %d units", len(blocks), len(names))
        return None
    found: list[FanToolUnit] = []
    for (unit, name), block in zip(KNOWN_FAN_TOOL_UNITS, blocks, strict=True):
        props = dict(line.partition("=")[::2] for line in block.splitlines())
        if props.get("LoadState", "not-found") == "not-found":
            continue
        found.append(
            FanToolUnit(
                unit=unit,
                name=name,
                active_state=props.get("ActiveState", ""),
                unit_file_state=props.get("UnitFileState", ""),
            )
        )
    return tuple(found)


def _fancontrol_pid_state(pid_file: Path, proc_dir: Path) -> str:
    """Whether ``fancontrol``'s PID file names a running ``fancontrol``.

    The script writes its own PID there and removes the file as it restores
    the fans, so a file naming no ``fancontrol`` is one left by a kill.
    """
    try:
        text = pid_file.read_text(errors="replace").strip()
    except FileNotFoundError:
        return "absent"
    except OSError as exc:
        log.debug("read %s failed: %s", pid_file, exc)
        return "unreadable"
    if not text.isdigit():
        return "stale"
    try:
        comm = (proc_dir / text / "comm").read_text(errors="replace").strip()
    except OSError:
        return "stale"
    return "running" if comm == "fancontrol" else "stale"


def fan_tools_line(state: FanToolState | None) -> str:
    """The Interference Monitor's reading, or ``""`` when nothing could be read."""
    if state is None:
        return ""
    running = [f"{u.name} ({u.unit})" for u in state.running]
    if state.fancontrol_by_hand:
        running.append("fancontrol (started by hand)")
    at_boot = [f"{u.name} ({u.unit})" for u in state.starting_at_boot]
    parts: list[str] = []
    if running:
        parts.append(f"Other fan-control software running: {', '.join(running)}.")
    if at_boot:
        parts.append(f"Set to start at boot: {', '.join(at_boot)}.")
    if state.fancontrol_pid == "stale":
        parts.append(
            "fancontrol did not exit cleanly (/run/fancontrol.pid is left over), so "
            "fans it drove may still be at its speeds; a reboot clears both."
        )
    if not parts:
        if not state.systemd_checked:
            return ""
        return "No known fan-control service is running or set to start at boot."
    if running or at_boot:
        them = "it" if len(running) + len(at_boot) == 1 else "them"
        parts.append(
            "Two programs writing one fan header fight each other: stop "
            f"{them}, or keep {them} off every fan Ventulus drives."
        )
    return " ".join(parts)
