"""Connecting to the daemon, and what the tool reads from it before a test.

Every fact here comes from the daemon or, read-only, from the GUI's saved
settings (fan names and the PWM Test Report's "Your setup" answers). This
module never writes the GUI's settings file: the GUI owns it, and its loader
moves an unreadable file aside, which is not this tool's call to make.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from ventulus.api.client import DaemonClient
from ventulus.api.errors import DaemonError, DaemonTimeout, DaemonUnavailable
from ventulus.api.models import BoardInfo, Capabilities, DaemonStatus, HwmonHeader
from ventulus.diag.console import EXIT_INCOMPATIBLE, EXIT_REFUSED, EXIT_UNAVAILABLE, DiagError
from ventulus.paths import app_settings_path, load_json_capped
from ventulus.services.daemon_features import daemon_supports, unsupported_feature_message
from ventulus.services.fan_names import fallback_fan_name
from ventulus.services.pwm_report.setup_facts import coerce_cooler_notes, coerce_hardware_notes


def unreachable_message(socket_path: str, detail: str = "") -> str:
    """Why the daemon could not be reached, and what to check — never a
    permission change: the socket is open to every local user by design."""
    tail = f" ({detail})" if detail else ""
    return (
        f"The daemon is not reachable at {socket_path}{tail}. Check that it is running "
        "(systemctl status ventulusd) and that --socket matches its socket path."
    )


@dataclass
class GuiSettings:
    """What this tool reads from the GUI's settings file. Empty when absent."""

    fan_aliases: dict[str, str] = field(default_factory=dict)
    hardware_notes: dict[str, dict[str, object]] = field(default_factory=dict)
    cooler_notes: dict[str, str] = field(default_factory=dict)


def read_gui_settings(path_fn: Callable[[], object] = app_settings_path) -> GuiSettings:
    """Read-only, never raises: a missing or unreadable file reads as empty."""
    try:
        data = load_json_capped(path_fn())  # type: ignore[arg-type]
    except (OSError, ValueError):
        return GuiSettings()
    if not isinstance(data, dict):
        return GuiSettings()
    aliases_raw = data.get("fan_aliases")
    aliases = (
        {
            k: v.strip()
            for k, v in aliases_raw.items()
            if isinstance(k, str) and isinstance(v, str) and v.strip()
        }
        if isinstance(aliases_raw, dict)
        else {}
    )
    return GuiSettings(
        fan_aliases=aliases,
        hardware_notes=coerce_hardware_notes(data.get("hardware_notes")),
        cooler_notes=coerce_cooler_notes(data.get("cooler_notes")),
    )


#: How long a cancel sent while leaving may take. Leaving "at once" must not
#: wait out the ordinary API timeout on a daemon that has stopped answering.
STOP_CANCEL_TIMEOUT_S = 2.0


def _short_client(socket_path: str) -> DaemonClient:
    return DaemonClient(socket_path=socket_path, timeout=STOP_CANCEL_TIMEOUT_S)


@dataclass
class Daemon:
    """A connected daemon and the state read from it at the start."""

    client: DaemonClient
    socket_path: str
    capabilities: Capabilities
    settings: GuiSettings
    headers: list[HwmonHeader] = field(default_factory=list)
    board: BoardInfo = field(default_factory=BoardInfo)
    #: Builds the client :meth:`best_effort` uses; a test passes its fake.
    stop_client_factory: Callable[[str], Any] = _short_client

    def best_effort(self, call: Callable[[Any], object]) -> str:
        """Send one request on a short-timeout client of its own, on the way out.
        Never raises: returns ``""`` when the daemon answered, else why not.
        Its own client, so a call stuck on :attr:`client` cannot hold it up."""
        client = self.stop_client_factory(self.socket_path)
        try:
            call(client)
            return ""
        except (DaemonError, OSError) as e:
            return getattr(e, "message", "") or str(e)
        finally:
            with contextlib.suppress(Exception):
                client.close()

    def refresh_headers(self) -> list[HwmonHeader]:
        self.headers = self.client.hwmon_headers()
        return self.headers

    def name_of(self, fan_id: str) -> str:
        """The GUI's display name: the user's alias, then the shared fallback chain."""
        alias = self.settings.fan_aliases.get(fan_id)
        if alias:
            return alias
        return fallback_fan_name(
            fan_id,
            capabilities=self.capabilities,
            headers=self.headers,
            board_vendor=self.board.vendor,
            board_name=self.board.name,
        )

    def header(self, header_id: str) -> HwmonHeader:
        for h in self.headers:
            if h.id == header_id:
                return h
        known = ", ".join(h.id for h in self.headers) or "none"
        raise DiagError(
            EXIT_REFUSED,
            f"No motherboard header has the id {header_id!r}. "
            f"Run ventulus-diag headers to list them. Known ids: {known}",
        )

    def require(self, feature_id: str) -> None:
        if daemon_supports(feature_id, self.capabilities) is not True:
            raise DiagError(EXIT_INCOMPATIBLE, unsupported_feature_message(feature_id))

    def status(self) -> DaemonStatus:
        return self.client.status()

    def profile_member_ids(self) -> frozenset[str]:
        """Members of the active profile, from the daemon's own document."""
        try:
            active = self.client.active_profile()
            if active is None or not getattr(active, "active", False):
                return frozenset()
            doc = self.client.get_profile(str(active.profile_id))
        except DaemonError:
            return frozenset()
        ids: set[str] = set()
        for control in doc.get("controls") or []:
            if not isinstance(control, Mapping):
                continue
            for member in control.get("members") or []:
                if isinstance(member, Mapping) and isinstance(member.get("member_id"), str):
                    ids.add(member["member_id"])
        return frozenset(ids)

    def close(self) -> None:
        self.client.close()


def connect(
    socket_path: str,
    *,
    client_factory: Callable[[str], DaemonClient] | None = None,
    settings: GuiSettings | None = None,
) -> Daemon:
    """Connect, check the daemon can be driven, and read headers and board.

    A daemon without ``control.autonomous_control`` predates daemon-side control
    (DEC-165); the GUI stands down from it, and so does this tool.
    """
    client = (client_factory or (lambda p: DaemonClient(socket_path=p)))(socket_path)
    try:
        caps = client.capabilities()
    except (DaemonUnavailable, DaemonTimeout) as e:
        client.close()
        raise DiagError(EXIT_UNAVAILABLE, unreachable_message(socket_path, e.message)) from e
    except DaemonError as e:
        client.close()
        raise DiagError(EXIT_INCOMPATIBLE, f"The daemon refused /capabilities: {e.message}") from e
    control = getattr(caps, "control", None)
    if not (control and control.autonomous_control):
        client.close()
        raise DiagError(
            EXIT_INCOMPATIBLE,
            "This ventulusd is too old for ventulus-diag (it has no daemon-side control). "
            "Upgrade ventulusd.",
        )
    daemon = Daemon(
        client=client,
        socket_path=socket_path,
        capabilities=caps,
        settings=settings if settings is not None else read_gui_settings(),
    )
    try:
        daemon.refresh_headers()
        daemon.board = client.hardware_diagnostics().board
    except (DaemonUnavailable, DaemonTimeout) as e:
        client.close()
        raise DiagError(EXIT_UNAVAILABLE, unreachable_message(socket_path, e.message)) from e
    except DaemonError:
        pass  # an older daemon without a route: names fall back further, nothing more
    return daemon


def start_refusal(status: DaemonStatus) -> list[str]:
    """Why no test may start now, read from the daemon's status."""
    from ventulus.services.pwm_report.runner import start_refusals

    session = getattr(status, "validation_session", None)
    return start_refusals(
        connected=True,
        thermal_state=status.thermal_state,
        diagnostic_running=bool(status.verify_active),
        session_recording=bool(session is not None and session.is_recording),
        demo_mode=False,
    )
