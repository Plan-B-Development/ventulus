"""AIO-MB Phase 3 — PWM/RPM response characterisation (GUI side).

Covers the three things the brief names as correctness requirements, not taste:

1. **The three axes stay separate.** Command acceptance, PWM readback and RPM
   response are reported independently; collapsing them into one pass/fail is a
   defect the brief calls out by name.
2. **A device that does not follow PWM is not a write failure.** A non-monotonic
   or motionless response must never render as "PWM writes failed".
3. **The safety decision reads the UNION, not the wire ``role``** (DEC-312).

Plus the client contract (no client-side clamp — the daemon owns the floor), the
capability gate, and unknown-token tolerance (the 273-i rule).
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QPushButton

from ventulus.api.models import (
    Capabilities,
    CharacterizationRun,
    ConnectionState,
    ControlCapability,
    HwmonHeader,
    OperationMode,
    parse_characterization_run,
)
from ventulus.services.characterization_view import (
    PUMP_STARTUP_WARNING,
    build_characterization_view,
    pre_run_warnings,
)
from ventulus.services.pump_protection import header_is_pump_protected


def _caps(*, characterization: bool = True, roles: bool = True) -> Capabilities:
    return Capabilities(
        daemon_version="2.29.0",
        control=ControlCapability(
            autonomous_control=True,
            header_roles=roles,
            pwm_characterization=characterization,
        ),
    )


def _header(**kw) -> HwmonHeader:
    base = dict(
        id="hwmon:nct6798:dev:pwm1:AIO_PUMP",
        label="AIO_PUMP",
        chip_name="nct6798",
        device_id="dev",
        pwm_index=1,
        is_writable=True,
    )
    base.update(kw)
    return HwmonHeader(**base)


def _run(**kw) -> CharacterizationRun:
    data = {
        "run_id": "char-1",
        "header_id": "h1",
        "state": "complete",
        "requested_points_pct": [30, 60, 100],
        "settle_seconds": 6,
        "points": [],
        "summary": None,
    }
    data.update(kw)
    return parse_characterization_run(data)


def _point(pct, readback=None, rpm=None, accepted=True, rv="match", rpmv="changed"):
    return {
        "requested_pct": pct,
        "command_accepted": accepted,
        "readback_pct": pct if readback is None else readback,
        "rpm_after": rpm,
        "readback_verdict": rv,
        "rpm_verdict": rpmv,
    }


# ── Model parsing ────────────────────────────────────────────────────


class TestModelParsing:
    def test_unknown_tokens_and_fields_are_kept_not_dropped(self):
        """273-i: render what a newer daemon sends; never drop the row."""
        run = parse_characterization_run(
            {
                "state": "some_future_state",
                "requested_points_pct": [30],
                "points": [
                    {
                        "requested_pct": 30,
                        "command_accepted": True,
                        "readback_verdict": "brand_new_verdict",
                        "rpm_verdict": "also_new",
                        "a_field_this_build_has_never_heard_of": 7,
                    }
                ],
                "summary": {"command_acceptance": "pass", "new_axis": "x"},
            }
        )
        assert len(run.points) == 1, "an unknown verdict must not drop the point"
        assert run.points[0].readback_verdict == "brand_new_verdict"
        assert run.state == "some_future_state"
        assert run.summary is not None

    def test_missing_summary_and_points_parse_to_safe_defaults(self):
        run = parse_characterization_run({})
        assert run.points == []
        assert run.summary is None
        assert run.requested_points_pct == []
        assert not run.is_running

    def test_capability_defaults_false_on_an_older_daemon(self):
        assert ControlCapability().pwm_characterization is False


# ── View-model ───────────────────────────────────────────────────────


class TestViewModel:
    def test_the_three_axes_are_reported_independently(self):
        run = _run(
            points=[_point(30, rpm=900), _point(100, rpm=3300)],
            summary={
                "command_acceptance": "pass",
                "pwm_readback": "clamped",
                "rpm_response": "responsive",
            },
        )
        view = build_characterization_view(run, header_label="AIO_PUMP")
        labels = {c.label: (c.value, c.state) for c in view.verdicts}
        assert labels["PWM command"] == ("Accepted", "ok")
        assert labels["PWM readback"] == ("Clamped", "warn")
        assert labels["RPM response"] == ("Responds", "ok")
        assert len(view.verdicts) == 3, "the axes must not be collapsed into one"

    def test_a_motionless_fan_with_a_good_readback_is_an_override_not_a_failure(self):
        run = _run(
            points=[_point(30, rpm=2800, rpmv="unchanged")],
            summary={
                "command_acceptance": "pass",
                "pwm_readback": "pass",
                "rpm_response": "no_response",
                "possible_device_override": True,
            },
        )
        view = build_characterization_view(run, header_label="AIO_PUMP")
        blob = " ".join(view.notes)
        assert PUMP_STARTUP_WARNING in blob
        assert "fail" not in blob.lower()
        labels = {c.label: c.value for c in view.verdicts}
        assert labels["PWM command"] == "Accepted"
        assert labels["PWM readback"] == "Correct"

    def test_a_non_monotonic_run_never_renders_as_a_pwm_write_failure(self):
        run = _run(
            points=[_point(30, rpm=900), _point(60, rpm=1800), _point(100, rpm=1200)],
            summary={
                "command_acceptance": "pass",
                "pwm_readback": "pass",
                "rpm_response": "responsive",
                "monotonic": False,
            },
        )
        view = build_characterization_view(run, header_label="AIO_PUMP")
        assert all(row.result != "Write failed" for row in view.rows)
        assert {c.label: c.value for c in view.verdicts}["PWM command"] == "Accepted"
        assert any("not a fault" in n for n in view.notes)

    def test_a_genuine_write_failure_is_reported_as_one(self):
        run = _run(
            state="failed",
            points=[_point(30, rpm=900), _point(60, accepted=False, rv="unavailable")],
            summary={
                "command_acceptance": "partial",
                "pwm_readback": "pass",
                "rpm_response": "unavailable",
            },
        )
        view = build_characterization_view(run, header_label="AIO_PUMP")
        assert view.rows[1].result == "Write failed"
        assert view.rows[1].state == "critical"
        assert {c.label: c.value for c in view.verdicts}["PWM command"] == "Partly accepted"

    def test_an_unknown_verdict_token_is_rendered_rather_than_dropped(self):
        run = _run(
            points=[_point(30, rpm=900, rv="quantum_flux")],
            summary={
                "command_acceptance": "pass",
                "pwm_readback": "quantum_flux",
                "rpm_response": "responsive",
            },
        )
        view = build_characterization_view(run, header_label="AIO_PUMP")
        assert len(view.rows) == 1
        assert view.rows[0].result == "Quantum flux"
        assert {c.label: c.value for c in view.verdicts}["PWM readback"] == "Quantum flux"

    def test_progress_and_running_state_drive_the_cancel_affordance(self):
        running = _run(state="running", points=[_point(30, rpm=900)])
        view = build_characterization_view(running, header_label="AIO_PUMP")
        assert view.running and view.can_cancel
        assert view.progress_text == "1 of 3 points"
        done = _run(state="complete", points=[_point(30, rpm=900)])
        assert not build_characterization_view(done, header_label="x").can_cancel

    def test_a_failed_restore_is_surfaced(self):
        run = _run(restore_failed=True, points=[_point(30, rpm=900)])
        view = build_characterization_view(run, header_label="AIO_PUMP")
        assert any("Restoring the original speed failed" in n for n in view.notes)

    def test_no_run_yet_renders_without_raising(self):
        view = build_characterization_view(None, header_label="AIO_PUMP")
        assert view.rows == [] and not view.running and view.status_text


# ── Pump protection: the UNION, not the wire role ────────────────────


class TestPumpProtectionUnion:
    def test_a_downgraded_pump_label_is_still_protected(self):
        """DEC-312: assigning chassis_fan to a PUMP-labelled header does NOT
        remove the daemon's protection, so the copy must not claim it did."""
        header = _header(label="AIO_PUMP", role="chassis_fan", role_source="user_assigned")
        assert header_is_pump_protected(header, _caps()) is True

    def test_a_user_assigned_pump_on_an_unlabelled_header_is_protected(self):
        header = _header(label="pwm1", role="pump", role_source="user_assigned")
        assert header_is_pump_protected(header, _caps()) is True

    def test_a_plain_chassis_header_is_not_protected(self):
        header = _header(label="CHA_FAN1", role="chassis_fan")
        assert header_is_pump_protected(header, _caps()) is False

    def test_a_cooler_channel_one_labelled_cpu_fan_is_not_promoted(self):
        header = _header(label="CPU_FAN1", role="cpu_fan", is_aio=True, pwm_index=1)
        assert header_is_pump_protected(header, _caps()) is False

    def test_nothing_is_protected_without_the_role_capability(self):
        header = _header(label="AIO_PUMP", role="pump")
        assert header_is_pump_protected(header, _caps(roles=False)) is False

    def test_the_pump_warning_only_appears_for_a_protected_header(self):
        assert PUMP_STARTUP_WARNING in " ".join(pre_run_warnings(_header(), is_pump=True))
        assert PUMP_STARTUP_WARNING not in " ".join(pre_run_warnings(_header(), is_pump=False))

    def test_every_run_warns_that_curve_control_pauses(self):
        for is_pump in (True, False):
            assert any("paused" in w for w in pre_run_warnings(_header(), is_pump=is_pump)), (
                "the user must be told all fans hold their duty during the sweep"
            )


# ── Dialog ───────────────────────────────────────────────────────────


# ── Capability gate on the page ──────────────────────────────────────


class TestPageGate:
    @staticmethod
    def _page(qtbot, caps):
        from ventulus.services.app_state import AppState
        from ventulus.ui.pages.system_state_page import SystemStatePage

        state = AppState()
        state.set_connection(ConnectionState.CONNECTED)
        state.set_mode(OperationMode.AUTOMATIC)
        state.set_capabilities(caps)
        state.set_hwmon_headers([_header()])
        page = SystemStatePage(state, None)
        qtbot.addWidget(page)
        page._populate_verify_combo()
        return page

    def test_the_quick_verify_button_is_untouched_by_the_new_one(self, qtbot):
        """The brief: 'Do not replace the existing quick PWM verification test.'"""
        page = self._page(qtbot, _caps())
        verify = page.findChild(QPushButton, "SystemState_Btn_verifyPwm")
        assert verify is not None
        assert verify.text() == "Test PWM Control"
        assert verify.isEnabled()


# ── Client contract ──────────────────────────────────────────────────


class TestClientContract:
    def test_start_sends_only_what_the_caller_supplied(self, monkeypatch):
        from ventulus.api.client import DaemonClient

        sent: dict = {}

        def fake_post(self, path, json=None, *, params=None, timeout=None):
            sent["path"] = path
            sent["json"] = json
            return {"run_id": "char-1", "header_id": "h1", "state": "running"}

        monkeypatch.setattr(DaemonClient, "_post", fake_post)
        client = DaemonClient.__new__(DaemonClient)
        run = client.start_characterization("h1")
        assert sent["path"] == "/hwmon/h1/characterize"
        assert sent["json"] == {}, "no client-side clamp — the daemon owns the floor"
        assert run.is_running

        client.start_characterization("h1", points_pct=[40, 80], settle_seconds=4)
        assert sent["json"] == {"points_pct": [40, 80], "settle_seconds": 4}

    def test_status_returns_none_on_404_and_reraises_everything_else(self, monkeypatch):
        from ventulus.api.client import DaemonClient
        from ventulus.api.errors import DaemonError

        def not_found(self, path, *, params=None, timeout=None):
            raise DaemonError(
                code="validation_error",
                message="none yet",
                retryable=False,
                source="validation",
                status=404,
                details=None,
                endpoint=path,
            )

        monkeypatch.setattr(DaemonClient, "_get", not_found)
        client = DaemonClient.__new__(DaemonClient)
        assert client.characterization_status() is None

        def boom(self, path, *, params=None, timeout=None):
            raise DaemonError(
                code="internal_error",
                message="boom",
                retryable=False,
                source="internal",
                status=500,
                details=None,
                endpoint=path,
            )

        monkeypatch.setattr(DaemonClient, "_get", boom)
        with pytest.raises(DaemonError):
            client.characterization_status()

    def test_cancel_targets_the_diagnostics_route(self, monkeypatch):
        from ventulus.api.client import DaemonClient

        seen: dict = {}

        def fake_delete(self, path, json=None, *, timeout=None):
            seen["path"] = path
            return {"run_id": "char-1", "state": "cancelled"}

        monkeypatch.setattr(DaemonClient, "_delete", fake_delete)
        client = DaemonClient.__new__(DaemonClient)
        assert client.cancel_characterization().state == "cancelled"
        assert seen["path"] == "/diagnostics/characterization"


class TestRestoreOutcomeNotes:
    """`AUD2-c`: the daemon used to publish `restore_failed: false` on three
    exits that deliberately did NOT restore, so the GUI said nothing about a
    header parked at a test duty. It now says which — and the wording has to
    differ per reason, because the single old note's advice ("re-activate your
    profile") is the one thing a user must not act on under a thermal force.
    """

    def _notes(self, **kw) -> str:
        run = _run(state="aborted", points=[_point(30, rpm=900)], **kw)
        return "\n".join(build_characterization_view(run, header_label="AIO_PUMP").notes)

    def test_a_restored_header_says_nothing_about_the_restore(self):
        assert "restor" not in self._notes(restore_failed=False, restore_outcome="restored").lower()

    def test_a_failed_restore_still_tells_the_user_to_retake_control(self):
        notes = self._notes(restore_failed=True, restore_outcome="write_failed")
        assert "Re-activate your profile" in notes

    def test_a_thermal_skip_does_not_tell_the_user_to_retake_control(self):
        """The wrong-advice case, stated as an absence AND a presence — an
        absence assertion on its own passes vacuously (the project rulebook § Hard-won
        lessons)."""
        notes = self._notes(restore_failed=True, restore_outcome="skipped_thermal_force")
        assert "Thermal safety" in notes, "the reason must be surfaced at all"
        assert "Re-activate your profile" not in notes, (
            "telling the user to retake control while the ladder is forcing is "
            "exactly the action the reason token exists to prevent"
        )

    def test_a_shutdown_skip_is_explained_rather_than_called_a_failure(self):
        notes = self._notes(restore_failed=True, restore_outcome="skipped_shutting_down")
        assert "shutting down" in notes
        assert "failed" not in notes.lower()

    def test_an_unreadable_pre_sweep_duty_is_explained(self):
        notes = self._notes(restore_failed=True, restore_outcome="no_original_duty")
        assert "could not be read" in notes

    def test_an_unresponsive_driver_is_named_rather_than_left_to_the_fallback(self):
        """`DC-cx` / DEC-420/455: the 273-i fallback was true but never said why.
        The note must name the cause AND not be the fallback's echo of the raw
        token — only the first half passes if the entry is removed."""
        notes = self._notes(
            restore_failed=True, restore_outcome="skipped_unresponsive", original_pct=45
        )
        assert "stopped answering" in notes
        assert "Skipped unresponsive" not in notes, "the 273-i fallback rendered instead"
        assert "It was at 45% before the sweep." in notes

    def test_an_unrecognised_reason_is_rendered_not_dropped(self):
        """273-i: the client owns the wording, so a token this build has never
        seen must still produce a note rather than silence."""
        notes = self._notes(restore_failed=True, restore_outcome="seized_by_firmware")
        assert "Seized by firmware" in notes

    def test_an_older_daemon_that_sends_no_reason_keeps_the_failure_note(self):
        """Pre-2.30.0 `restore_failed: true` could only mean the write failed."""
        notes = self._notes(restore_failed=True)
        assert "Re-activate your profile" in notes


class TestRestoreNoteDoesNotTrustOneField:
    """`restore_note` reconstructs "was it put back?" from both fields.

    The daemon derives one from the other, so they cannot disagree today. Taking
    its word for it is the thing `AUD2-c` was, though: a version-skewed or
    partial response naming a skip while reporting `restore_failed: false` would
    fall silent in exactly the old way.
    """

    def _notes(self, **kw) -> str:
        run = _run(state="aborted", points=[_point(30, rpm=900)], **kw)
        return "\n".join(build_characterization_view(run, header_label="AIO_PUMP").notes)

    def test_a_skip_reason_is_surfaced_even_if_the_boolean_says_otherwise(self):
        notes = self._notes(restore_failed=False, restore_outcome="skipped_thermal_force")
        assert "Thermal safety" in notes

    def test_a_running_or_absent_outcome_with_a_false_boolean_stays_silent(self):
        for outcome in ("", "pending", "restored"):
            assert (
                "restor" not in self._notes(restore_failed=False, restore_outcome=outcome).lower()
            ), f"{outcome!r} must not produce a note"


# ── Call sites (register row `AUD2-f`) ───────────────────────────────
#
# Everything above this line tests the pieces. `AUD2-f` is about the wiring:
# `grep -rn _open_characterization tests/` used to return zero hits, so the
# whole click → page → dialog path was unexecuted, and every `TestDialog` case
# above passes `is_pump=True` as a LITERAL. That means `system_state_page.py`'s
#
#     is_pump=header_is_pump_protected(header, …)
#
# could have been written `header.role == "pump"` — the exact DEC-312 defect the
# line exists to prevent — with the entire file still green. This is the project rulebook's
# most-repeated lesson: *extracting a rule into a testable function does not
# test the call site.*
