"""Executes the report runner's calls against the daemon, keeping every answer verbatim.

Qt-free, so the GUI's report worker and the ``ventulus-diag`` CLI make exactly the
same requests and record exactly the same evidence (DEC-503). The runner
(``runner.py``) decides what to ask for; this module only asks, and translates
every failure once into a :class:`~ventulus.services.pwm_report.runner.CallOutcome`:
``unavailable`` for "the daemon did not answer" (a timeout included — a verify
that timed out client-side may still have completed), ``error`` for "the daemon
answered no". The runner, not this module, decides what each means.

The client carries a response observer, so the report keeps the body the daemon
actually sent — error bodies included — rather than the parsed model, which would
drop any field this client does not model yet (S4-9 (8)).
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from ventulus.services.pwm_report.document import utc_now_iso
from ventulus.services.pwm_report.runner import CallOutcome

if TYPE_CHECKING:
    from ventulus.api.client import DaemonClient

log = logging.getLogger(__name__)

#: Long-running diagnostics' status and cancel calls, by the runner's slot name.
_POLL = {
    "characterization": lambda c: c.characterization_status(),
    "control_path": lambda c: c.control_path_status(),
    "stall_probe": lambda c: c.stall_probe_status(),
}
_CANCEL = {
    "characterization": lambda c: c.cancel_characterization(),
    "control_path": lambda c: c.cancel_control_path_discovery(),
    "stall_probe": lambda c: c.cancel_stall_probe(),
}


def poll_slot(client: DaemonClient, slot: str) -> Any:
    """``GET`` the daemon run in *slot* (``None`` when there has been none)."""
    return _POLL[slot](client)


#: The daemon's diagnostic slots, in the order ``ventulus-diag cancel`` checks them.
SLOTS = tuple(_CANCEL)


def cancel_slot(client: DaemonClient, slot: str) -> None:
    """``DELETE`` the daemon run in *slot*. Raises what the client raises."""
    _CANCEL[slot](client)


def snapshot_entry(outcome: CallOutcome, fetched_at: str) -> dict:
    return {
        "status": outcome.status,
        "body": outcome.body,
        "error": outcome.error_message or None,
        "fetched_at": fetched_at,
    }


class ReportCallExecutor:
    """Runs one call at a time on a client it is handed.

    ``get_client`` returns the client to use (building one if needed);
    ``drop_client`` forgets it after the daemon could not be reached, so the next
    call builds a fresh one. The client must be built with :meth:`observe` as its
    response observer. ``on_unexpected`` is told about an exception no arm here
    expects; the answer is then whatever body was seen, or "no answer".
    """

    def __init__(
        self,
        get_client: Callable[[], DaemonClient],
        drop_client: Callable[[], None],
        *,
        on_unexpected: Callable[[Exception], None] | None = None,
    ) -> None:
        self._get_client = get_client
        self._drop_client = drop_client
        self._on_unexpected = on_unexpected
        self._last_body: tuple[int, object] | None = None

    def observe(self, method: str, path: str, status: int, body: object) -> None:
        self._last_body = (status, body)

    def execute(self, kind: str, payload: object) -> CallOutcome:
        args = payload if isinstance(payload, Mapping) else {}
        header_id = str(args.get("header_id") or "")
        extra = args.get("args") if isinstance(args.get("args"), Mapping) else {}
        if kind == "snapshot":
            return self.snapshot()
        calls: dict[str, Callable[[Any], object] | None] = {
            "preflight": lambda c: c.diagnostic_preflight(header_id, str(extra.get("diagnostic"))),
            "verify": lambda c: c.verify_hwmon_pwm(header_id),
            "start_pairing": lambda c: c.start_control_path_discovery(header_id),
            "start_sweep": lambda c: c.start_characterization(
                header_id,
                points_pct=list(extra.get("points_pct") or []) or None,
                bidirectional=extra.get("bidirectional"),
                stability_seconds=extra.get("stability_seconds"),
            ),
            # The acknowledgement travels only when the runner put it in the
            # call, which it does only for a header the user confirmed (S4-2).
            "start_probe": lambda c: c.start_stall_probe(
                header_id, acknowledge_below_floor=extra.get("acknowledge_below_floor") is True
            ),
            "reapply_profile": lambda c: c.activate_profile(
                profile_id=str(extra.get("profile_id"))
            ),
        }
        slot = str(extra.get("slot") or "")
        if kind == "poll":
            calls["poll"] = _POLL.get(slot)
        elif kind == "cancel":
            calls["cancel"] = _CANCEL.get(slot)
        fn = calls.get(kind)
        if fn is None:
            return CallOutcome(ok=False, category="error", error_message=f"unknown call {kind!r}")
        return self.guarded(fn)

    def guarded(self, fn: Callable[[Any], object]) -> CallOutcome:
        """Run one client call and describe what came back, verbatim."""
        from ventulus.api.errors import DaemonError, DaemonTimeout, DaemonUnavailable

        self._last_body = None
        try:
            fn(self._get_client())
        except DaemonTimeout as e:
            return CallOutcome(ok=False, category="unavailable", error_message=e.message)
        except DaemonUnavailable as e:
            self._drop_client()
            return CallOutcome(ok=False, category="unavailable", error_message=e.message)
        except DaemonError as e:
            status, body = self._last_body or (e.status, None)
            return CallOutcome(
                ok=False,
                status=status,
                body=body,
                error_code=e.code,
                error_message=e.message,
                retryable=e.retryable,
                category="error",
                details=e.details,
            )
        except (ConnectionError, OSError) as e:
            log.warning("PWM report: connection error: %s", e)
            self._drop_client()
            return CallOutcome(ok=False, category="unavailable", error_message=str(e))
        except (TypeError, ValueError, KeyError, AttributeError) as e:
            # The typed parser choked on a 2xx body. The raw body is what the
            # report keeps anyway, so hand it on rather than losing the answer.
            log.warning("PWM report: could not parse a daemon reply (%s); keeping it raw", e)
        except Exception as e:
            # Anything else ends the same way as a parse failure: whatever the
            # daemon sent is kept raw, and no body at all is "no answer".
            if self._on_unexpected is not None:
                self._on_unexpected(e)
            else:
                log.error("PWM report: a call failed unexpectedly", exc_info=e)
        if self._last_body is None:
            return CallOutcome(ok=False, category="unavailable", error_message="no answer")
        status, body = self._last_body
        # A 404 the client maps to "nothing yet" (status GETs) is still a 404.
        return CallOutcome(
            ok=status < 400, status=status, body=body, category="" if status < 400 else "error"
        )

    def snapshot(self) -> CallOutcome:
        """Every read-only surface the report needs, each answer verbatim.

        Recorded per endpoint with its status: a 404 from a route an older
        daemon lacks is evidence of that, not a failure of the snapshot. Only
        a daemon that cannot be reached at all fails the whole snapshot.
        """
        reads: list[tuple[str, Callable[[Any], object]]] = [
            ("capabilities", lambda c: c.capabilities()),
            ("status", lambda c: c.status()),
            ("fans", lambda c: c.fans()),
            ("sensors", lambda c: c.sensors()),
            ("headers", lambda c: c.hwmon_headers()),
            ("hardware", lambda c: c.hardware_diagnostics()),
            ("profile_active", lambda c: c.active_profile()),
            ("cooling_devices", lambda c: c.get_cooling_devices()),
            ("control_paths", lambda c: c.control_path_status()),
        ]
        bundle: dict[str, dict] = {}
        for name, fn in reads:
            outcome = self.guarded(fn)
            if name == "capabilities" and outcome.category == "unavailable":
                return outcome  # nothing answered: the snapshot never happened
            bundle[name] = snapshot_entry(outcome, utc_now_iso())
        active = bundle["profile_active"].get("body")
        profile_id = active.get("profile_id") if isinstance(active, dict) else None
        if isinstance(active, dict) and active.get("active") and profile_id:
            outcome = self.guarded(lambda c: c.get_profile(str(profile_id)))
            bundle["profile"] = snapshot_entry(outcome, utc_now_iso())
        return CallOutcome(ok=True, status=200, body=bundle)


class OwnedClient:
    """A client this object builds, owns and rebuilds after a lost daemon.

    For callers with no client of their own (the CLI). Pass :meth:`get` and
    :meth:`drop` to :class:`ReportCallExecutor`.
    """

    def __init__(self, socket_path: str, observer: Callable[..., None] | None = None) -> None:
        self._socket_path = socket_path
        self._observer = observer
        self._client: DaemonClient | None = None

    def set_observer(self, observer: Callable[..., None]) -> None:
        self._observer = observer

    def get(self) -> DaemonClient:
        from ventulus.api.client import DaemonClient

        if self._client is None:
            self._client = DaemonClient(
                socket_path=self._socket_path, response_observer=self._observer
            )
        return self._client

    def drop(self) -> None:
        if self._client is not None:
            with contextlib.suppress(Exception):
                self._client.close()
        self._client = None

    close = drop
