"""Background QThread workers for the Diagnostics page.

Extracted from ``diagnostics_page.py`` (Cluster C maintainability split). Each is
a self-contained ``QObject`` that runs one blocking daemon call off the UI thread
and reports via signals. It takes only a socket path and lazily builds its own
per-thread ``DaemonClient``, so it holds no back-reference to the page and the
heavy ``api.client`` / ``api.errors`` imports stay inside the methods (avoiding
import cycles).
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal, Slot

from ventulus.constants import VERIFY_TIMEOUT_S
from ventulus.services.daemon_features import unsupported_feature_message
from ventulus.services.diag_cli_view import slot_busy_text

if TYPE_CHECKING:
    from ventulus.api.client import DaemonClient

log = logging.getLogger(__name__)


def unexpected_error_message(subject: str) -> str:
    """What a call that failed outside the daemon-error family says (`PTA-p`).

    A bare lower-case clause: every consumer but two prefixes its own label
    ("Verify error: …", "Session error: …"), and the exception text goes to the
    log rather than to the user.
    """
    return f"{subject} ended with an unexpected error (details in the application log)"


#: What a verify that failed outside the daemon-error family says (`PTA-p`).
UNEXPECTED_VERIFY_ERROR = unexpected_error_message("the test")


def _is_soft_refusal(err: object) -> bool:
    """A raised refusal to show softly, in the daemon's words — not a failure.

    Protection (:func:`ventulus.api.errors.is_soft_safety_refusal`), or an
    OpenFAN firmware update holding the controller
    (:func:`~ventulus.api.errors.is_openfan_maintenance_refusal`): both are
    retryable, and the daemon accepts the same request later. The rules live in
    ``api.errors`` so the PWM Test Report runner (``ventulus-diag``), which sees an outcome rather
    than an exception, applies the same ones (``DC-cl``) and words them apart.
    """
    from ventulus.api.errors import is_openfan_maintenance_refusal, is_soft_safety_refusal

    details = getattr(err, "details", None)
    return is_soft_safety_refusal(
        getattr(err, "code", ""), bool(getattr(err, "retryable", False)), details
    ) or is_openfan_maintenance_refusal(details)


class _SocketWorker(QObject):
    """Shared base for the Diagnostics QThread workers.

    Holds the per-thread client machinery every worker duplicated: it stores
    only the daemon socket path (no back-reference to the page), lazily builds
    its own ``DaemonClient`` on first use so the heavy ``api.client`` import
    stays out of the module top-level and off the UI thread, and closes that
    client on :meth:`shutdown`. Subclasses declare only their own result
    signals and ``do_*`` slots.
    """

    def __init__(self, socket_path: str) -> None:
        super().__init__()
        self._socket_path = socket_path
        self._client: DaemonClient | None = None
        #: Set by :meth:`shutdown` on the UI thread and read by :meth:`_backstop`
        #: on this worker's thread. A stale read costs one log level, nothing more.
        self._shut_down = False

    def _backstop(
        self, exc: Exception, subject: str, emit: Callable[[str, str], None] | None
    ) -> None:
        """The last ``except`` of every slot here (`PTA-p`, `PTA-q`, `ROLE-g`).

        An exception escaping a slot is printed and swallowed by Qt, so neither
        result signal fires — and every consumer clears its in-flight state only
        in those slots, leaving a button disabled or a dialog waiting until
        restart. Reachable through a body the parser cannot read, and through
        httpx's ``RuntimeError`` when :meth:`shutdown` closes the client while a
        call is in flight. That second case is teardown, which closes the client
        first on purpose (the project's Qt rules), and nobody is listening any
        more, so it is logged quietly and reported to no one.
        """
        if self._shut_down:
            log.debug("%s: %s ended after shutdown: %r", type(self).__name__, subject, exc)
            return
        log.error("%s: %s failed unexpectedly", type(self).__name__, subject, exc_info=exc)
        if emit is not None:
            emit("error", unexpected_error_message(subject))

    def _refuse_after_shutdown(self) -> None:
        """Raise once :meth:`shutdown` has run, so nothing builds a new client.

        `shutdown` clears ``_client``, so without this the next call — a queued
        slot, or the next read of a loop that the backstop lets continue — would
        open a fresh client and talk to the daemon during teardown. The
        ``RuntimeError`` lands in the slot's backstop, which is quiet after
        shutdown.
        """
        if self._shut_down:
            raise RuntimeError(f"{type(self).__name__} was shut down")

    def _drop_client(self) -> None:
        """Forget this worker's client after the daemon could not be reached.

        The client turns every connection fault into ``DaemonUnavailable``, so
        the ``(ConnectionError, OSError)`` arms that used to do this alone were
        unreachable on that path and a client from before a daemon restart was
        kept. The next call builds a fresh one.
        """
        if self._client is not None:
            with contextlib.suppress(Exception):
                self._client.close()
        self._client = None

    def _ensure_client(self) -> DaemonClient:
        from ventulus.api.client import DaemonClient as _DaemonClient

        self._refuse_after_shutdown()
        if self._client is None:
            self._client = _DaemonClient(socket_path=self._socket_path)
        return self._client

    def shutdown(self) -> None:
        self._shut_down = True
        if self._client is not None:
            with contextlib.suppress(Exception):
                self._client.close()
            self._client = None


class _VerifyWorker(_SocketWorker):
    """Runs in a QThread — executes the blocking ~6 s verify_hwmon_pwm call off
    the UI thread so the rest of the GUI (polling, splitter, menus) keeps
    reacting during the hardware probe."""

    # Both arms echo the header the verify was REQUESTED for, so a consumer can
    # tell whose result this is rather than inferring it from "what did I ask
    # for most recently" (row `ACK-n`). The requested id is used deliberately in
    # preference to the daemon's echo in `HwmonVerifyResult.header_id`: it is
    # the only identity the error arm has at all, and it makes both arms answer
    # the same question.
    verify_ok = Signal(object, str)  # HwmonVerifyResult, requested header_id
    verify_error = Signal(str, str, str)  # category ('unavailable'|'error'), message, header_id

    @Slot(str)
    def do_verify(self, header_id: str) -> None:
        from ventulus.api.errors import DaemonError, DaemonTimeout, DaemonUnavailable

        try:
            result = self._ensure_client().verify_hwmon_pwm(header_id)
            self.verify_ok.emit(result, header_id)
        except DaemonTimeout:
            # DEC-098: a verify timeout means the daemon was slow — the write
            # may still have landed. Don't say "unavailable", which implies
            # the daemon is gone. The category stays "unavailable" so the page's
            # error handler shows this softened message verbatim instead of
            # prefixing it as a hard "Verify error"; only the message is rewritten.
            self.verify_error.emit(
                "unavailable",
                f"Verify timed out (>{VERIFY_TIMEOUT_S:.0f}s). The daemon may have completed the "
                "write — re-check the fan and re-run if needed.",
                header_id,
            )
        except DaemonUnavailable:
            self._drop_client()
            self.verify_error.emit("unavailable", "Daemon unavailable during verify", header_id)
        except DaemonError as e:
            # A refusal is not a failure — show the daemon's message verbatim
            # (soft), not as an error. See `_is_soft_refusal`. Another test
            # holding the slot (often `ventulus-diag`, DEC-503) is said plainly.
            if _is_soft_refusal(e):
                self.verify_error.emit("unavailable", e.message, header_id)
            elif busy := slot_busy_text(e):
                self.verify_error.emit("unavailable", busy, header_id)
            else:
                self.verify_error.emit("error", e.message, header_id)
        except (ConnectionError, OSError) as e:
            log.warning("Verify worker connection error: %s", e)
            with contextlib.suppress(Exception):
                if self._client is not None:
                    self._client.close()
            self._client = None
            self.verify_error.emit("unavailable", "Connection lost during verify", header_id)
        except Exception as e:
            # `PTA-p`: the Hardware page's in-flight count and System State's
            # active header clear only in the two result slots, so silence here
            # left the report's Start refused until restart.
            self._backstop(
                e, "the test", lambda cat, msg: self.verify_error.emit(cat, msg, header_id)
            )


class _GpuVerifyWorker(_SocketWorker):
    """Runs in a QThread — executes the blocking GPU fan calls off the UI
    thread: the ~6s ``verify_gpu_fan`` probe (DEC-120) and the
    ``reset_gpu_fan`` restore-to-automatic (DEC-147), mirroring
    :class:`_VerifyWorker`."""

    verify_ok = Signal(object)  # GpuVerifyResult
    # category ('unavailable' | 'error'), message
    verify_error = Signal(str, str)
    reset_ok = Signal(object)  # GpuFanResetResult
    reset_error = Signal(str, str)  # category ('unavailable' | 'error'), message

    @Slot(str)
    def do_verify(self, gpu_id: str) -> None:
        from ventulus.api.errors import DaemonError, DaemonTimeout, DaemonUnavailable

        try:
            result = self._ensure_client().verify_gpu_fan(gpu_id)
            self.verify_ok.emit(result)
        except DaemonTimeout:
            self.verify_error.emit(
                "unavailable",
                f"GPU verify timed out (>{VERIFY_TIMEOUT_S:.0f}s). The daemon may have "
                "completed the test — re-check the fan and re-run if needed.",
            )
        except DaemonUnavailable:
            self._drop_client()
            self.verify_error.emit("unavailable", "Daemon unavailable during GPU verify")
        except DaemonError as e:
            # A 404 is "GPU not found", never "no such route": the page offers
            # the button only on a daemon that serves it (`gpu_fan_verify`, or
            # its version fallback). Reading it as an old daemon hid the button
            # for the session, with no message, when all that had happened was a
            # GPU id going stale — after a daemon restart, say.
            if getattr(e, "status", None) == 404:
                self.verify_error.emit(
                    "error",
                    f"{e.message}. The daemon no longer reports this GPU — "
                    "refresh System State and try again.",
                )
            elif _is_soft_refusal(e):
                # A refusal — show the daemon's message verbatim, not as an
                # error. See `_is_soft_refusal`.
                self.verify_error.emit("unavailable", e.message)
            elif busy := slot_busy_text(e):
                # The GPU test claims the same slot as every other (DEC-503).
                self.verify_error.emit("unavailable", busy)
            else:
                self.verify_error.emit("error", e.message)
        except (ConnectionError, OSError) as e:
            log.warning("GPU verify worker connection error: %s", e)
            with contextlib.suppress(Exception):
                if self._client is not None:
                    self._client.close()
            self._client = None
            self.verify_error.emit("unavailable", "Connection lost during GPU verify")
        except Exception as e:
            # `PTA-q`: System State re-enables *Test GPU Fan Control* only in the
            # two result slots, so silence left it disabled until restart.
            self._backstop(e, "the test", self.verify_error.emit)

    @Slot(str)
    def do_reset(self, gpu_id: str) -> None:
        """Restore the GPU fan to the firmware's automatic curve (DEC-147).

        Unlike ``do_verify`` there is no ``unsupported`` category: the reset
        route predates every supported daemon, so a 404 here means the GPU id
        itself was not found — a real error, not a version gap.
        """
        from ventulus.api.errors import DaemonError, DaemonTimeout, DaemonUnavailable

        try:
            result = self._ensure_client().reset_gpu_fan(gpu_id)
            self.reset_ok.emit(result)
        except DaemonTimeout:
            self.reset_error.emit(
                "unavailable",
                "GPU restore timed out. The daemon may still have completed "
                "the reset — check the fan behaviour and re-run if needed.",
            )
        except DaemonUnavailable:
            self._drop_client()
            self.reset_error.emit("unavailable", "Daemon unavailable during GPU restore")
        except DaemonError as e:
            self.reset_error.emit("error", e.message)
        except (ConnectionError, OSError) as e:
            log.warning("GPU restore worker connection error: %s", e)
            with contextlib.suppress(Exception):
                if self._client is not None:
                    self._client.close()
            self._client = None
            self.reset_error.emit("unavailable", "Connection lost during GPU restore")
        except Exception as e:
            self._backstop(e, "the restore", self.reset_error.emit)


class _HwDiagWorker(_SocketWorker):
    """Runs in a QThread — executes the blocking GET /diagnostics/hardware call
    off the UI thread. The daemon performs several sysfs/procfs reads to build
    the report, so a synchronous fetch on a slow/contended daemon would freeze
    the GUI — notably the once-per-session auto-fetch when the Fans tab is first
    shown.

    Also hosts the POST /hwmon/rescan call (DEC-147) — the daemon re-walks
    ``/sys/class/hwmon`` synchronously to rebuild the header list, and the
    rescan's natural follow-up is a diagnostics refetch on this same thread.
    """

    fetch_ok = Signal(object)  # HardwareDiagnosticsResult
    fetch_error = Signal(str, str)  # category ('unavailable'|'error'), message
    # list[HwmonHeader], adopted OpenFan port ("" when none) — DEC-266
    rescan_ok = Signal(object, str)
    rescan_error = Signal(str, str)  # category ('unavailable'|'error'), message
    fan_tools_ok = Signal(object)  # FanToolState

    @Slot()
    def do_probe_fan_tools(self) -> None:
        """Look for other fan-control software (``fan_tool_check``). Local, not
        a daemon call; here because ``systemctl`` can block on a stuck systemd."""
        from ventulus.services import fan_tool_check

        try:
            self.fan_tools_ok.emit(fan_tool_check.probe_fan_tools())
        except Exception as e:
            self._backstop(e, "the fan-control software check", None)

    @Slot()
    def do_fetch(self) -> None:
        from ventulus.api.errors import DaemonError, DaemonTimeout, DaemonUnavailable

        try:
            result = self._ensure_client().hardware_diagnostics()
            self.fetch_ok.emit(result)
        except DaemonTimeout:
            self.fetch_error.emit("unavailable", "Diagnostics fetch timed out")
        except DaemonUnavailable:
            self._drop_client()
            self.fetch_error.emit("unavailable", "Daemon unavailable — cannot fetch diagnostics")
        except DaemonError as e:
            self.fetch_error.emit("error", e.message)
        except (ConnectionError, OSError) as e:
            log.warning("HW diagnostics worker connection error: %s", e)
            with contextlib.suppress(Exception):
                if self._client is not None:
                    self._client.close()
            self._client = None
            self.fetch_error.emit("unavailable", "Connection lost during diagnostics fetch")
        except Exception as e:
            self._backstop(e, "the diagnostics fetch", self.fetch_error.emit)

    @Slot()
    def do_rescan(self) -> None:
        """Re-enumerate hwmon devices via POST /hwmon/rescan (DEC-147).

        DEC-265: also asks the daemon to look for an OpenFanController, when it
        advertises that route. "Rescan Hardware" is the action a user reaches for
        when a device is missing, and an OpenFan controller that enumerated after
        the daemon booted is exactly that case — offering a second, separate
        button for it would mean knowing in advance which kind of hardware went
        missing. The OpenFan leg is best-effort: it never fails the hwmon rescan,
        which is the part with a UI contract.
        """
        from ventulus.api.errors import DaemonError, DaemonTimeout, DaemonUnavailable

        try:
            client = self._ensure_client()
            # DEC-266: the contracted leg runs FIRST. The OpenFan leg can spend
            # seconds probing serial candidates, so running it first held the
            # user's "Rescanning..." chip open for an opportunistic extra. It
            # also reused the same client afterwards, so a close() racing
            # teardown surfaced as an httpx RuntimeError out of the second call
            # instead of a clean DaemonUnavailable out of the first.
            headers = client.hwmon_rescan()
            adopted_port = self._try_openfan_rescan(client)
            self.rescan_ok.emit(headers, adopted_port)
        except DaemonTimeout:
            self.rescan_error.emit("unavailable", "Hardware rescan timed out")
        except DaemonUnavailable:
            self._drop_client()
            self.rescan_error.emit("unavailable", "Daemon unavailable — cannot rescan hardware")
        except DaemonError as e:
            self.rescan_error.emit("error", e.message)
        except (ConnectionError, OSError) as e:
            log.warning("Hwmon rescan worker connection error: %s", e)
            with contextlib.suppress(Exception):
                if self._client is not None:
                    self._client.close()
            self._client = None
            self.rescan_error.emit("unavailable", "Connection lost during hardware rescan")
        except Exception as e:
            # DEC-266: backstop. The handlers above are the daemon-error family,
            # but `hwmon_rescan()` can raise outside it — `parse_hwmon_headers`
            # gives `TypeError` on a `"headers": null` body, and httpx raises a
            # bare `RuntimeError` if the client is closed by teardown between
            # entering this slot and issuing the request. Either escaped every
            # handler, so NEITHER signal fired; the page clears
            # `_rescan_in_flight` only in those two slots, so Rescan Hardware
            # stayed dead for the rest of the session with the chip stuck on
            # "Rescanning hardware…". Fixing that on the OpenFan leg alone left
            # the same wedge reachable through this one.
            self._backstop(e, "the hardware rescan", self.rescan_error.emit)

    def _try_openfan_rescan(self, client) -> str:
        """Best-effort OpenFan adoption alongside the hwmon rescan (DEC-265).

        Returns the port a controller was adopted on, or ``""`` for every other
        outcome. The caller reports an adoption to the user: DEC-266 — the result
        line otherwise still said "New fan-control hardware still requires a
        daemon restart", which is precisely what this feature makes untrue, so
        the one case it exists for was the one case the UI mis-advised.

        Capability-gated, so an older daemon is never asked and never 404s. Every
        failure is swallowed deliberately: this is an opportunistic extra, and a
        serial probe that finds nothing is the *normal* outcome on a machine with
        no OpenFan hardware — surfacing that as a rescan failure would report the
        hwmon rescan as broken on every such machine.
        """
        try:
            caps = client.capabilities()
            if not caps.control.openfan_rescan:
                return ""
            result = client.openfan_rescan()
            if result.get("adopted"):
                port = str(result.get("port") or "")
                log.info("OpenFanController adopted via rescan: %s", port)
                return port
        except Exception as e:
            # DEC-266: deliberately broad, matching the precedent in
            # `services/polling.py`. The narrow tuple this replaced did not cover
            # what `parse_capabilities` raises on a malformed body —
            # `AttributeError`/`TypeError` — which escaped BOTH this handler and
            # `do_rescan`'s. Neither `rescan_ok` nor `rescan_error` then fired, so
            # `_rescan_in_flight` never cleared and Rescan Hardware was dead for
            # the rest of the session. The docstring above claimed "every failure
            # is swallowed"; now it is true. Cost of catching broadly here is nil
            # — the leg has no side effect the caller depends on.
            log.debug("OpenFan rescan leg did not adopt a controller: %s", e)
            if isinstance(e, (ConnectionError, OSError)):
                # This leg now runs LAST, so a socket that dies here is no longer
                # seen by `do_rescan`'s connection handler — the hwmon call has
                # already returned. Without this the stale client survives, the
                # user gets a green "Rescan complete", and the very next call
                # (the chained diagnostics refetch) fails instead.
                with contextlib.suppress(Exception):
                    if self._client is not None:
                        self._client.close()
                self._client = None
        return ""


class _HardwareReadinessWorker(_SocketWorker):
    """Runs in a QThread — executes the blocking GET /inventory/hardware-readiness
    call off the UI thread (the daemon runs a sysfs/procfs scan to build the
    combined readiness + Super-I/O snapshot). DEC-207. Also hosts the opt-in ACTIVE
    Super-I/O port probe (POST), whose result updates only the Super-I/O section
    (dedicated ``probe_*`` signals) so the readiness snapshot is left untouched.
    """

    fetch_ok = Signal(object)  # HardwareReadiness
    # category ('unavailable' | 'error' | 'unsupported'), message
    fetch_error = Signal(str, str)
    probe_ok = Signal(object)  # SuperIoReport (enriched with probe hits)
    probe_error = Signal(str, str)  # category ('unavailable' | 'error'), message

    @Slot()
    def do_fetch(self) -> None:
        """First-open / auto fetch — serves the daemon's cached assessment."""
        self._fetch(force=False)

    @Slot()
    def do_refresh(self) -> None:
        """The page's "Refresh hardware assessment" action — forces a fresh scan."""
        self._fetch(force=True)

    def _fetch(self, *, force: bool) -> None:
        from ventulus.api.errors import DaemonError, DaemonTimeout, DaemonUnavailable

        try:
            result = self._ensure_client().hardware_readiness(refresh=force)
            self.fetch_ok.emit(result)
        except DaemonTimeout:
            self.fetch_error.emit("unavailable", "Hardware readiness fetch timed out")
        except DaemonUnavailable:
            self._drop_client()
            self.fetch_error.emit(
                "unavailable", "Daemon unavailable — cannot fetch hardware readiness"
            )
        except DaemonError as e:
            # A daemon predating /inventory/hardware-readiness answers 404 not_found
            # — signal 'unsupported' so the page shows an unavailable state.
            if getattr(e, "status", None) == 404 or getattr(e, "code", "") == "not_found":
                self.fetch_error.emit(
                    "unsupported",
                    unsupported_feature_message("hardware_readiness"),
                )
            elif (
                getattr(e, "status", None) == 503
                or getattr(e, "code", "") == "hardware_unavailable"
            ):
                # DEC-231: 503 hardware_unavailable is a transient, retryable soft
                # state (the daemon's hardware scan is momentarily busy / not
                # ready), not a hard error — surface it as 'unavailable' so it
                # reads as "try again", consistent with the timeout/daemon-down
                # arms above, rather than a dead-end error.
                self.fetch_error.emit(
                    "unavailable",
                    "Hardware readiness temporarily unavailable — try again shortly.",
                )
            else:
                self.fetch_error.emit("error", e.message)
        except (ConnectionError, OSError) as e:
            log.warning("Hardware readiness worker connection error: %s", e)
            with contextlib.suppress(Exception):
                if self._client is not None:
                    self._client.close()
            self._client = None
            self.fetch_error.emit("unavailable", "Connection lost during hardware readiness fetch")
        except Exception as e:
            self._backstop(e, "the hardware readiness fetch", self.fetch_error.emit)

    @Slot()
    def do_probe(self) -> None:
        """DEC-203/207: the opt-in ACTIVE Super-I/O port probe (POST). Returns a
        SuperIoReport enriched with any probe-detected chips — emitted on the
        dedicated ``probe_*`` signals so the page refreshes only its Super-I/O
        section. A daemon-disabled probe returns a normal report, not an error."""
        from ventulus.api.errors import DaemonError, DaemonTimeout, DaemonUnavailable

        try:
            result = self._ensure_client().superio_probe()
            self.probe_ok.emit(result)
        except DaemonTimeout:
            self.probe_error.emit("unavailable", "Super-I/O port probe timed out")
        except DaemonUnavailable:
            self._drop_client()
            self.probe_error.emit("unavailable", "Daemon unavailable — cannot run the port probe")
        except DaemonError as e:
            # A 404 on the PROBE endpoint must NOT flip the panel's unsupported flag
            # (that hides the whole page even though the passive GET works). Report
            # it as a transient error so the page survives (CON review, DEC-203).
            if getattr(e, "status", None) == 404 or getattr(e, "code", "") == "not_found":
                self.probe_error.emit("error", unsupported_feature_message("superio_port_probe"))
            else:
                self.probe_error.emit("error", e.message)
        except (ConnectionError, OSError) as e:
            log.warning("Hardware readiness probe worker connection error: %s", e)
            with contextlib.suppress(Exception):
                if self._client is not None:
                    self._client.close()
            self._client = None
            self.probe_error.emit("unavailable", "Connection lost during Super-I/O port probe")
        except Exception as e:
            # The page shows a probe message verbatim, unprefixed — so a sentence.
            self._backstop(
                e,
                "the Super-I/O port probe",
                lambda cat, msg: self.probe_error.emit(cat, msg[:1].upper() + msg[1:]),
            )


class _ControlPathWorker(_SocketWorker):
    """Reads the persisted control-path relationships off the UI thread (§6.3).

    Read-only since DEC-503: discovery itself runs from ``ventulus-diag
    discover``, and the Hardware page only shows what the daemon has persisted
    on each header card. A short GET, so the page asks once per capability
    refresh rather than polling.
    """

    run_updated = Signal(object)  # ControlPathStatus | None
    run_error = Signal(str, str)  # category ('unavailable'|'error'), message

    @Slot()
    def do_poll(self) -> None:
        from ventulus.api.errors import DaemonError, DaemonUnavailable

        try:
            self.run_updated.emit(self._ensure_client().control_path_status())
        except DaemonUnavailable:
            self._drop_client()
            self.run_error.emit("unavailable", "Daemon unavailable reading control paths")
        except DaemonError as e:
            self.run_error.emit("error", e.message)
        except (ConnectionError, OSError) as e:
            log.warning("Control-path worker connection error: %s", e)
            with contextlib.suppress(Exception):
                if self._client is not None:
                    self._client.close()
            self._client = None
            self.run_error.emit("unavailable", "Connection lost reading control paths")
        except Exception as e:
            # `ROLE-g`: the case seen live is this one-shot GET still in flight
            # when teardown closed the client.
            self._backstop(e, "the control-path read", self.run_error.emit)


class _OpenFanCalibrationWorker(_SocketWorker):
    """Runs the OpenFan calibration calls off the UI thread (DEC-452 / DEC-453).

    All three calls are short because the daemon returns ``202`` and walks the
    channel itself, the polling
    cadence is the dialog's QTimer, and a GUI that dies mid-run does not strand
    the channel — the daemon kicks a stopped fan and restores the duty on every
    exit path.
    """

    run_updated = Signal(object)  # OpenFanCalibrationRun | None
    run_error = Signal(str, str)  # category ('unavailable'|'error'), message

    def _guard(self, call, what: str, *, start: bool = False) -> None:
        from ventulus.api.errors import DaemonError, DaemonTimeout, DaemonUnavailable

        try:
            self.run_updated.emit(call())
        except DaemonTimeout:
            self.run_error.emit(
                "unavailable",
                f"The daemon did not answer the {what} in time. The calibration may "
                "still be running — the daemon restores the channel itself when it ends.",
            )
        except DaemonUnavailable:
            self._drop_client()
            self.run_error.emit("unavailable", f"Daemon unavailable during {what}")
        except DaemonError as e:
            # The shared refusal taxonomy (`_is_soft_refusal`): `thermal_abort` and a
            # retryable `validation_error` are protection, or a controller busy with
            # an OpenFAN firmware update, not failure. This route returns both — the
            # retryable 400 with no fresh CPU reading included, since the predicate
            # keys on `retryable`, not on the status. Only a start can meet a
            # busy slot (DEC-503); a cancel's 409 means nothing was running.
            if _is_soft_refusal(e):
                self.run_error.emit("unavailable", e.message)
            elif start and (busy := slot_busy_text(e)):
                self.run_error.emit("unavailable", busy)
            else:
                self.run_error.emit("error", e.message)
        except (ConnectionError, OSError) as e:
            log.warning("OpenFan calibration worker connection error: %s", e)
            with contextlib.suppress(Exception):
                if self._client is not None:
                    self._client.close()
            self._client = None
            self.run_error.emit("unavailable", f"Connection lost during {what}")
        except Exception as e:
            self._backstop(e, f"the {what}", self.run_error.emit)

    @Slot(int)
    def do_start(self, channel: int) -> None:
        # The acknowledgement is sent only because the dialog's Start is
        # unreachable until the user ticked the per-channel pump confirmation
        # (DEC-453). No `hold_seconds`: the daemon's default applies.
        self._guard(
            lambda: self._ensure_client().start_openfan_calibration(
                channel, acknowledge_below_floor=True
            ),
            "calibration start",
            start=True,
        )

    @Slot()
    def do_poll(self) -> None:
        self._guard(lambda: self._ensure_client().openfan_calibration_status(), "status poll")

    @Slot()
    def do_cancel(self) -> None:
        self._guard(lambda: self._ensure_client().cancel_openfan_calibration(), "cancellation")


class _OpenFanFirmwareWorker(_SocketWorker):
    """Runs the OpenFAN firmware update calls off the UI thread (DEC-481).

    Every call is short: the daemon answers ``202`` and runs the update itself,
    so a GUI that closes or dies mid-run strands nothing — the run carries on,
    and a reopened window picks it up from ``GET /fans/openfan/maintenance``.
    The device read waits on the board's own answers and carries its own
    timeout.

    A start ends one of three ways, each on its own signal, so the window never
    says more than it knows: ``started`` with the run id the daemon's ``202``
    named; ``start_failed`` when the daemon answered and refused, so nothing
    began; ``start_unconfirmed`` when no answer came — a timeout or a lost
    connection — and the request may have started a run all the same. A failed
    read after a ``202`` is ``run_error``: the run is the daemon's, and the next
    poll finds it. A cancel the daemon refused or never answered is
    ``cancel_failed``, apart from a failed read, so the window can offer it again.

    DEC-483: ``do_stage`` hands the daemon the checked file's bytes and answers
    ``staged`` with its verdict, or ``stage_failed`` naming the file by its
    fingerprint (last, after the usual category and message) so the window can
    drop an answer about an earlier one. A start
    that asks the daemon to write hands it the bytes again first: the daemon
    keeps one file, in memory, and a restart or another upload since would
    otherwise refuse the start.
    """

    device_ready = Signal(object)  # OpenFanDevice
    device_error = Signal(str, str)  # category ('unavailable'|'error'), message
    staged = Signal(object)  # OpenFanFirmwareStaged
    stage_failed = Signal(str, str, str)  # category, message, file sha256
    run_updated = Signal(object)  # OpenFanMaintenanceRecord | None
    run_error = Signal(str, str)  # category, message
    started = Signal(str)  # the run id the daemon's 202 named
    start_failed = Signal(str, str)  # category, message
    start_unconfirmed = Signal(str, str)  # category, message
    cancel_failed = Signal(str, str)  # category, message

    def _guard(self, call, what: str, emit_error) -> None:
        from ventulus.api.errors import DaemonError, DaemonTimeout, DaemonUnavailable

        try:
            call()
        except DaemonTimeout:
            emit_error(
                "unavailable",
                f"The daemon did not answer the {what} in time. An update that has "
                "started carries on daemon-side.",
            )
        except DaemonUnavailable:
            self._drop_client()
            emit_error("unavailable", f"Daemon unavailable during the {what}.")
        except DaemonError as e:
            # A refused start is a 409 `validation_error` with `retryable` and a
            # `details.reason`: protection, not failure — the daemon's own words.
            if _is_soft_refusal(e):
                emit_error("unavailable", e.message)
            else:
                emit_error("error", e.message)
        except (ConnectionError, OSError) as e:
            log.warning("OpenFAN firmware worker connection error: %s", e)
            with contextlib.suppress(Exception):
                if self._client is not None:
                    self._client.close()
            self._client = None
            emit_error("unavailable", f"Connection lost during the {what}.")
        except Exception as e:
            self._backstop(e, f"the {what}", emit_error)

    @Slot()
    def do_device(self) -> None:
        self._guard(
            lambda: self.device_ready.emit(self._ensure_client().openfan_device()),
            "controller read",
            self.device_error.emit,
        )

    @Slot(object)
    def do_stage(self, data: bytes) -> None:
        sha256 = hashlib.sha256(data).hexdigest()
        self._guard(
            lambda: self.staged.emit(self._ensure_client().stage_openfan_firmware(data)),
            "file upload",
            lambda category, message: self.stage_failed.emit(category, message, sha256),
        )

    @Slot(str, dict, object, str)
    def do_start(
        self, expected_usb_serial: str, firmware: dict, write_data: object, board: str
    ) -> None:
        # Sent only from the window's Start, which is unreachable until the file
        # passed every check and the user ticked the confirmation. *write_data*
        # is the file's bytes when the daemon is to write it, else None; *board*
        # is which board the update is for (DEC-484).
        from ventulus.api.errors import DaemonError, DaemonTimeout, DaemonUnavailable
        from ventulus.services.openfan_firmware_view import VERDICT_DAEMON_WRITE

        started = False

        def call() -> None:
            nonlocal started
            client = self._ensure_client()
            daemon_write = isinstance(write_data, bytes)
            if daemon_write:
                # Nothing has started yet, whatever happens to this upload.
                try:
                    staged = client.stage_openfan_firmware(write_data)
                except DaemonError as e:
                    category = (
                        "unavailable"
                        if isinstance(e, (DaemonTimeout, DaemonUnavailable))
                        else "error"
                    )
                    self.start_failed.emit(
                        category, f"The daemon could not be given the file again: {e.message}"
                    )
                    return
                self.staged.emit(staged)
                if staged.verdict != VERDICT_DAEMON_WRITE or staged.sha256 != firmware.get(
                    "sha256"
                ):
                    said = staged.message.rstrip(".")
                    self.start_failed.emit(
                        "error",
                        "The daemon will not write this file itself now"
                        + (f": {said}." if said else ".")
                        + " Start again to copy it by hand.",
                    )
                    return
            try:
                run_id = client.start_openfan_maintenance(
                    expected_usb_serial, firmware, daemon_write=daemon_write, board=board
                )
            except DaemonError as e:
                answered = not isinstance(e, (DaemonTimeout, DaemonUnavailable))
                if answered and not 200 <= e.status < 300:
                    raise  # the daemon refused: `_guard` words it, nothing began
                if isinstance(e, DaemonTimeout):
                    why = "The daemon did not answer the start in time."
                elif isinstance(e, DaemonUnavailable):
                    self._drop_client()
                    why = "The daemon could not be reached during the start."
                else:
                    why = "The daemon's answer to the start could not be read."
                self.start_unconfirmed.emit("unavailable", why)
                return
            except (ConnectionError, OSError) as e:
                log.warning("OpenFAN firmware worker connection error: %s", e)
                with contextlib.suppress(Exception):
                    if self._client is not None:
                        self._client.close()
                self._client = None
                self.start_unconfirmed.emit(
                    "unavailable", "The connection was lost during the start."
                )
                return
            except Exception as e:
                self._backstop(e, "the update start", self.start_unconfirmed.emit)
                return
            started = True
            self.started.emit(run_id)
            self.run_updated.emit(client.openfan_maintenance_status())

        def failed(category: str, message: str) -> None:
            (self.run_error if started else self.start_failed).emit(category, message)

        self._guard(call, "update start", failed)

    @Slot()
    def do_poll(self) -> None:
        self._guard(
            lambda: self.run_updated.emit(self._ensure_client().openfan_maintenance_status()),
            "status read",
            self.run_error.emit,
        )

    @Slot()
    def do_cancel(self) -> None:
        cancelled = False

        def call() -> None:
            nonlocal cancelled
            client = self._ensure_client()
            client.cancel_openfan_maintenance()
            cancelled = True
            self.run_updated.emit(client.openfan_maintenance_status())

        def failed(category: str, message: str) -> None:
            (self.run_error if cancelled else self.cancel_failed).emit(category, message)

        self._guard(call, "cancellation", failed)
