"""DEC-472: every diagnostics worker slot ends in one shared backstop.

`PTA-p` gave `_VerifyWorker` a final ``except Exception``; DEC-266 gave the
rescan one. Every other slot still let an exception outside the daemon-error
family escape, and Qt prints and swallows an exception escaping a slot — so
neither result signal fired and the consumer's in-flight state never cleared
(`PTA-q`: *Test GPU Fan Control* disabled until restart; `ROLE-g`: a status poll
in flight when teardown closed the client).

Each case drives the slot with a client whose call raises httpx's closed-client
``RuntimeError`` — the exception `ROLE-g` saw — and asserts the slot still
answers, exactly once, on its error signal. The quiet-after-shutdown half
asserts the same slot says nothing once the worker has been shut down.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QObject, Slot

from ventulus.services.app_state import AppState
from ventulus.ui.pages.diagnostics_workers import (
    UNEXPECTED_VERIFY_ERROR,
    _ControlPathWorker,
    _GpuVerifyWorker,
    _HardwareReadinessWorker,
    _HwDiagWorker,
    _OpenFanCalibrationWorker,
    _OpenFanFirmwareWorker,
    _VerifyWorker,
    unexpected_error_message,
)
from ventulus.ui.pages.hardware_page import HardwarePage
from ventulus.ui.pages.system_state_page import SystemStatePage

CLOSED = RuntimeError("Cannot send a request, as the client has been closed.")

# (id, worker class, slot name, slot args, client method that raises,
#  error signal, ok signal, the message the error signal must carry)
CASES = [
    (
        "verify",
        _VerifyWorker,
        "do_verify",
        ("h",),
        "verify_hwmon_pwm",
        "verify_error",
        "verify_ok",
        UNEXPECTED_VERIFY_ERROR,
    ),
    (
        "gpu-verify",
        _GpuVerifyWorker,
        "do_verify",
        ("g",),
        "verify_gpu_fan",
        "verify_error",
        "verify_ok",
        unexpected_error_message("the test"),
    ),
    (
        "gpu-reset",
        _GpuVerifyWorker,
        "do_reset",
        ("g",),
        "reset_gpu_fan",
        "reset_error",
        "reset_ok",
        unexpected_error_message("the restore"),
    ),
    (
        "hw-diag",
        _HwDiagWorker,
        "do_fetch",
        (),
        "hardware_diagnostics",
        "fetch_error",
        "fetch_ok",
        unexpected_error_message("the diagnostics fetch"),
    ),
    (
        "rescan",
        _HwDiagWorker,
        "do_rescan",
        (),
        "hwmon_rescan",
        "rescan_error",
        "rescan_ok",
        unexpected_error_message("the hardware rescan"),
    ),
    (
        "readiness",
        _HardwareReadinessWorker,
        "do_fetch",
        (),
        "hardware_readiness",
        "fetch_error",
        "fetch_ok",
        unexpected_error_message("the hardware readiness fetch"),
    ),
    (
        "readiness-refresh",
        _HardwareReadinessWorker,
        "do_refresh",
        (),
        "hardware_readiness",
        "fetch_error",
        "fetch_ok",
        unexpected_error_message("the hardware readiness fetch"),
    ),
    # Shown verbatim and unprefixed by the page, so it starts as a sentence.
    (
        "probe",
        _HardwareReadinessWorker,
        "do_probe",
        (),
        "superio_probe",
        "probe_error",
        "probe_ok",
        "The Super-I/O port probe ended with an unexpected error (details in the application log)",
    ),
    # `ROLE-g`'s own case: the page's one-shot read of the persisted paths.
    (
        "path-poll",
        _ControlPathWorker,
        "do_poll",
        (),
        "control_path_status",
        "run_error",
        "run_updated",
        unexpected_error_message("the control-path read"),
    ),
    (
        "ofan-start",
        _OpenFanCalibrationWorker,
        "do_start",
        (3,),
        "start_openfan_calibration",
        "run_error",
        "run_updated",
        unexpected_error_message("the calibration start"),
    ),
    (
        "ofan-poll",
        _OpenFanCalibrationWorker,
        "do_poll",
        (),
        "openfan_calibration_status",
        "run_error",
        "run_updated",
        unexpected_error_message("the status poll"),
    ),
    (
        "ofan-cancel",
        _OpenFanCalibrationWorker,
        "do_cancel",
        (),
        "cancel_openfan_calibration",
        "run_error",
        "run_updated",
        unexpected_error_message("the cancellation"),
    ),
    (
        "ofw-device",
        _OpenFanFirmwareWorker,
        "do_device",
        (),
        "openfan_device",
        "device_error",
        "device_ready",
        unexpected_error_message("the controller read"),
    ),
    # An unexpected failure of the POST answers on `start_unconfirmed`: it may
    # have reached the daemon, so the window asks rather than says it failed.
    (
        "ofw-start",
        _OpenFanFirmwareWorker,
        "do_start",
        ("S", {}, None, "connected"),
        "start_openfan_maintenance",
        "start_unconfirmed",
        "run_updated",
        unexpected_error_message("the update start"),
    ),
    # DEC-483: the upload before a daemon write fails before anything is sent
    # that could start a run, so it answers on `start_failed`.
    (
        "ofw-start-write",
        _OpenFanFirmwareWorker,
        "do_start",
        ("S", {}, b"uf2", "connected"),
        "stage_openfan_firmware",
        "start_failed",
        "run_updated",
        unexpected_error_message("the update start"),
    ),
    (
        "ofw-stage",
        _OpenFanFirmwareWorker,
        "do_stage",
        (b"uf2",),
        "stage_openfan_firmware",
        "stage_failed",
        "staged",
        unexpected_error_message("the file upload"),
    ),
    (
        "ofw-poll",
        _OpenFanFirmwareWorker,
        "do_poll",
        (),
        "openfan_maintenance_status",
        "run_error",
        "run_updated",
        unexpected_error_message("the status read"),
    ),
    # GSA-h: a cancel that never got an answer is `cancel_failed`, so the window
    # can offer it again; a failed read after an accepted cancel stays `run_error`.
    (
        "ofw-cancel",
        _OpenFanFirmwareWorker,
        "do_cancel",
        (),
        "cancel_openfan_maintenance",
        "cancel_failed",
        "run_updated",
        unexpected_error_message("the cancellation"),
    ),
    (
        "ofw-cancel-read",
        _OpenFanFirmwareWorker,
        "do_cancel",
        (),
        "openfan_maintenance_status",
        "run_error",
        "run_updated",
        unexpected_error_message("the cancellation"),
    ),
]


class _RequestWorker(QObject):
    """A real QObject whose request slot records whether it was reached."""

    def __init__(self, order: list[str], page_signal) -> None:
        super().__init__()
        self._order = order
        self._page_signal = page_signal
        self._args: tuple = ()

    @Slot()
    def do_request(self) -> None:
        self._order.append("request")

    def shutdown(self) -> None:
        self._order.append("shutdown")
        # Still connected here would mean a request could reach the worker
        # after its client closed — the window this ordering closes.
        self._page_signal.emit(*self._args)


# Each page's own request signal: the disconnect under test is the page's.
PAGES = [
    (SystemStatePage, "_verify_request", ("h",)),
    (HardwarePage, "_control_paths_request", ()),
]


@pytest.mark.parametrize(("page_cls", "signal_name", "args"), PAGES)
def test_teardown_drops_the_pages_requests_before_closing_the_client(
    qtbot, page_cls, signal_name, args
):
    page = page_cls(state=AppState())
    qtbot.addWidget(page)
    signal = getattr(page, signal_name)
    order: list[str] = []
    worker = _RequestWorker(order, signal)
    worker._args = args
    signal.connect(worker.do_request)
    other: list[str] = []
    signal.connect(lambda *_: other.append("other"))  # a link that is not to the worker
    thread = MagicMock()
    thread.quit.side_effect = lambda: order.append("quit")
    thread.wait.side_effect = lambda *_: order.append("wait") or True

    signal.emit(*args)
    assert order == ["request"], "precondition: the request reaches the worker before teardown"
    order.clear()

    page._teardown_worker(worker, thread, "t")

    assert order == ["shutdown", "quit", "wait"], order
    signal.emit(*args)
    assert order == ["shutdown", "quit", "wait"], "a request reached the worker after teardown"
    assert len(other) == 3, "teardown must drop only the page's links to this worker"


def test_the_fan_tools_probe_ends_in_the_backstop(qapp, caplog, monkeypatch):
    """`do_probe_fan_tools` calls no daemon and has no error signal: the page
    keeps no in-flight state for it, so a failed probe answers nobody. It must
    still end in the backstop, loud before shutdown and quiet after."""
    from ventulus.services import fan_tool_check

    def boom():
        raise CLOSED

    monkeypatch.setattr(fan_tool_check, "probe_fan_tools", boom)
    worker = _HwDiagWorker("/tmp/x.sock")
    oks: list = []
    worker.fan_tools_ok.connect(oks.append)

    with caplog.at_level(logging.DEBUG):
        worker.do_probe_fan_tools()
    assert oks == []
    assert [r.levelno for r in caplog.records] == [logging.ERROR]

    caplog.clear()
    worker.shutdown()
    with caplog.at_level(logging.DEBUG):
        worker.do_probe_fan_tools()
    assert oks == []
    assert [r.levelno for r in caplog.records] == [logging.DEBUG]


def test_every_worker_slot_is_covered_by_this_file():
    """Enumerate the population, then subtract: a slot added later without a
    case here fails, rather than shipping without the backstop unseen."""
    import inspect

    from ventulus.ui.pages import diagnostics_workers as module

    workers = [
        cls
        for _, cls in inspect.getmembers(module, inspect.isclass)
        if issubclass(cls, module._SocketWorker) and cls is not module._SocketWorker
    ]
    slots = {(cls, name) for cls in workers for name in vars(cls) if name.startswith("do_")}
    covered = {(case[1], case[2]) for case in CASES} | {
        (_HwDiagWorker, "do_probe_fan_tools"),
    }
    assert len(workers) >= 7, "precondition: the worker classes were found"
    assert slots - covered == set(), f"slots with no backstop case: {sorted(slots - covered)}"
