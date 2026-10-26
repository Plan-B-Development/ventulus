"""What the support bundle carries beyond the GUI's own state: the distribution,
the fan drivers DKMS built, the kernel's signing verdict, each header's
channels, and the daemon's safety and skip state, without anything the user
typed or any unrelated software."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from ventulus.api.models import (
    DaemonStatus,
    HardwareDiagnosticsResult,
    HwmonHeader,
    KernelSecurityInfo,
    PumpStall,
    ReadinessRollup,
    SkippedControl,
    UnavailableSensor,
)
from ventulus.services.app_state import AppState
from ventulus.services.diagnostics_service import DiagnosticsService

# `dkms status` as dkms 3 prints it on a CachyOS box, plus an old-format line.
_DKMS_OUT = """\
hid-xpadneo/v0.10.5, 7.3.0-3-cachyos, x86_64: installed
it87/349.c567739, 6.18.55-2-cachyos-lts, x86_64: installed (Original modules exist)
it87/349.c567739, 7.3.0-3-cachyos, x86_64: installed (Original modules exist)
r8126/10.016.00, 7.3.0-3-cachyos, x86_64: installed
nct6687d, 1, 6.12.0-1-amd64, x86_64: installed
asus-ec-sensors/0.1, 7.3.0-3-cachyos, x86_64: built

"""


def _dkms_run(stdout: str = _DKMS_OUT, returncode: int = 0, calls: list | None = None):
    def run(args, **kwargs):
        if calls is not None:
            calls.append(args)
        return SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)

    return run


def test_dkms_keeps_the_fan_drivers_and_counts_the_rest(monkeypatch):
    calls: list = []
    monkeypatch.setattr(
        "ventulus.services.diagnostics_service.subprocess.run", _dkms_run(calls=calls)
    )
    out = DiagnosticsService.collect_dkms_status()
    assert calls == [["dkms", "status"]]
    assert out == {
        "modules": [
            "it87/349.c567739, 6.18.55-2-cachyos-lts, x86_64: installed (Original modules exist)",
            "it87/349.c567739, 7.3.0-3-cachyos, x86_64: installed (Original modules exist)",
            "nct6687d, 1, 6.12.0-1-amd64, x86_64: installed",
            "asus-ec-sensors/0.1, 7.3.0-3-cachyos, x86_64: built",
        ],
        "other_modules_omitted": 2,
    }
    assert "xpadneo" not in json.dumps(out) and "r8126" not in json.dumps(out)


@pytest.mark.parametrize(
    ("raised", "stdout", "expected"),
    [
        (FileNotFoundError("dkms"), "", "dkms is not installed"),
        (subprocess.TimeoutExpired("dkms", 5), "", "dkms status timed out after 5s"),
        (None, "", "dkms status exited 3"),
    ],
)
def test_dkms_that_does_not_run_says_why(monkeypatch, raised, stdout, expected):
    def run(*a, **k):
        if raised is not None:
            raise raised
        return SimpleNamespace(stdout=stdout, returncode=3)

    monkeypatch.setattr("ventulus.services.diagnostics_service.subprocess.run", run)
    assert DiagnosticsService.collect_dkms_status() == {"error": expected}


def test_dkms_that_fails_but_lists_modules_keeps_them(monkeypatch):
    """One broken module tree can fail `dkms status` without hiding the rest."""
    monkeypatch.setattr(
        "ventulus.services.diagnostics_service.subprocess.run", _dkms_run(returncode=1)
    )
    out = DiagnosticsService.collect_dkms_status()
    assert out["exit_status"] == 1
    assert len(out["modules"]) == 4 and out["other_modules_omitted"] == 2


def test_the_distribution_is_named_without_the_rest_of_os_release(monkeypatch):
    release = {
        "NAME": "Ubuntu",
        "ID": "ubuntu",
        "ID_LIKE": "debian",
        "VERSION": "26.04 LTS (Resolute Raccoon)",
        "VERSION_ID": "26.04",
        "HOME_URL": "https://www.ubuntu.com/",
        "PRIVACY_POLICY_URL": "https://example.invalid/privacy",
    }
    monkeypatch.setattr(
        "ventulus.services.diagnostics_service.platform.freedesktop_os_release",
        lambda: release,
    )
    assert DiagnosticsService.collect_distribution() == {
        "name": "Ubuntu",
        "id": "ubuntu",
        "id_like": "debian",
        "version": "26.04 LTS (Resolute Raccoon)",
        "version_id": "26.04",
    }

    def missing():
        raise OSError("no os-release")

    monkeypatch.setattr(
        "ventulus.services.diagnostics_service.platform.freedesktop_os_release", missing
    )
    assert DiagnosticsService.collect_distribution() is None


# ── The whole bundle ─────────────────────────────────────────────────────────

_USER_TEXT = "Rads behind the desk"


def _service() -> DiagnosticsService:
    state = AppState()
    state.set_hwmon_headers(
        [
            HwmonHeader(
                id="hwmon:it8696:it87.2608:pwm1:CPU_FAN",
                label="CPU_FAN",
                chip_name="it8696",
                is_writable=True,
                supports_enable=True,
                pwm_mode=1,
                role="cpu_fan",
                role_source="label",
            ),
            HwmonHeader(
                id="hwmon:asusec:asus-ec-sensors.0:pwm1:pwm1",
                label="pwm1",
                chip_name="asusec",
                is_writable=False,
            ),
        ]
    )
    state.set_status(
        DaemonStatus(
            overall_status="degraded",
            thermal_state="emergency",
            emergency_causes=["cpu"],
            uptime_seconds=3600,
            readiness=ReadinessRollup(overall="warning", warning=1, top_code="no_pwm_controls"),
            pump_stalls=[PumpStall(header_id="hwmon:x:y:pwm2:PUMP", state="stalled")],
            unavailable_sensors=[
                UnavailableSensor(id="hwmon:ath12k:t1", label="wifi", reason="enodata")
            ],
            skipped_controls=[
                SkippedControl(
                    control_id="ctl-1", control_name=_USER_TEXT, reason="sensor_unavailable"
                )
            ],
        )
    )
    svc = DiagnosticsService(state=state)
    svc.set_hw_diagnostics(
        HardwareDiagnosticsResult(
            kernel_security=KernelSecurityInfo(
                secure_boot=True,
                lockdown="integrity",
                module_sig_enforce=False,
                signed_modules_only=True,
            )
        )
    )
    return svc


def _complete(monkeypatch, svc: DiagnosticsService) -> str:
    monkeypatch.setattr(svc, "fetch_journal_entries", lambda: "")
    monkeypatch.setattr(DiagnosticsService, "collect_kernel_modules", staticmethod(lambda: ""))
    monkeypatch.setattr(DiagnosticsService, "fetch_kernel_log_amdgpu", staticmethod(lambda: ""))
    monkeypatch.setattr(
        DiagnosticsService, "collect_distribution", staticmethod(lambda: {"id": "cachyos"})
    )
    monkeypatch.setattr("ventulus.services.diagnostics_service.subprocess.run", _dkms_run())
    return svc.complete_support_bundle(svc.snapshot_support_bundle())


def test_the_bundle_carries_the_new_sections(monkeypatch):
    bundle = json.loads(_complete(monkeypatch, _service()))
    system = bundle["system"]
    assert system["distribution"] == {"id": "cachyos"}
    assert system["dkms"]["other_modules_omitted"] == 2
    assert bundle["hardware_diagnostics"]["kernel_security"] == {
        "secure_boot": True,
        "lockdown": "integrity",
        "module_sig_enforce": False,
        "signed_modules_only": True,
    }
    headers = {h["id"]: h for h in bundle["hwmon_headers"]}
    assert headers["hwmon:it8696:it87.2608:pwm1:CPU_FAN"]["is_writable"] is True
    assert headers["hwmon:asusec:asus-ec-sensors.0:pwm1:pwm1"]["is_writable"] is False
    status = bundle["daemon_status"]
    assert status["thermal_state"] == "emergency"
    assert status["emergency_causes"] == ["cpu"]
    assert status["readiness"]["top_code"] == "no_pwm_controls"
    assert status["pump_stalls"][0]["header_id"] == "hwmon:x:y:pwm2:PUMP"
    assert status["unavailable_sensors"] == [
        {"id": "hwmon:ath12k:t1", "reason": "enodata", "unavailable_for_ms": 0}
    ]
    assert status["skipped_controls"] == [
        {"control_id": "ctl-1", "reason": "sensor_unavailable", "skipped_for_ms": 0}
    ]


def test_a_skipped_controls_name_never_reaches_the_bundle(monkeypatch):
    """The control's name is the user's own text, like their notes."""
    text = _complete(monkeypatch, _service())
    assert '"skipped_controls"' in text, "precondition: the section is there"
    assert _USER_TEXT not in text


def test_the_saved_file_is_the_previewed_text(monkeypatch, tmp_path):
    """`finish_support_bundle` writes exactly what `complete_support_bundle`
    returns, so what the preview shows is what lands on disk."""
    svc = _service()
    previewed = _complete(monkeypatch, svc)
    out = tmp_path / "bundle.json"
    svc.finish_support_bundle(svc.snapshot_support_bundle(), out)
    written = json.loads(out.read_text())
    shown = json.loads(previewed)
    for bundle in (written, shown):
        bundle.pop("timestamp")
    assert written == shown
