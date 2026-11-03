"""AIO Phase 8 Batch 3a — thermal observation, steady state, startup fingerprint.

DEC-335. Discharges the §12 bullets that belong to 3a, plus the project's own
standing test rules:

* call-site tests assert a **relationship**, never a literal (DEC-324) — and the
  right-hand side is chosen so the defect cannot satisfy it;
* ``isVisibleTo(parent)``, never ``isVisible()``, under ``offscreen`` (DEC-324);
* presence before absence (DEC-272);
* unknown is never rendered as zero, which is this batch's own headline rule.
"""

from __future__ import annotations

import pytest

from ventulus.api.models import (
    STARTUP_COMMAND_MISMATCH,
    STARTUP_DEVICE_OVERRIDE,
    STARTUP_NONE_OBSERVED,
    STEADY_STATE_DETECTED,
    STEADY_STATE_INSUFFICIENT,
    STEADY_STATE_NOT_ESTABLISHED,
    Capabilities,
    ControlCapability,
    ValidationStartupFingerprint,
    ValidationSteadyState,
    parse_validation_session,
)
from ventulus.services.daemon_features import daemon_supports
from ventulus.services.thermal_view import (
    TONE_WARN,
    UNKNOWN_TEXT,
    build_startup_views,
    build_steady_state_view,
    startup_tone,
    steady_state_label,
    steady_state_tone,
)

# ── fixtures ─────────────────────────────────────────────────────────────────


def _caps(**control) -> Capabilities:
    control.setdefault("validation_sessions", True)
    control.setdefault("thermal_observation", True)
    return Capabilities(control=ControlCapability(**control))


# ── §12: model parsing ───────────────────────────────────────────────────────


class TestModelParsing:
    def test_the_power_fields_round_trip_and_absence_stays_none(self):
        parsed = parse_validation_session(
            {"samples": [{"package_power_w": 198.5, "gpu_power_w": 33.0}, {}]}
        )
        assert parsed.samples[0].package_power_w == 198.5
        assert parsed.samples[0].gpu_power_w == 33.0
        # Presence before absence: the second sample proves absence stays None
        # only because the first proved the field parses at all.
        assert parsed.samples[1].package_power_w is None

    def test_steady_state_and_fingerprints_parse(self):
        parsed = parse_validation_session(
            {
                "steady_state": {"verdict": "detected", "mean_c": 52.0, "criterion": "x"},
                "startup_fingerprints": [
                    {"member_id": "pump1", "interpretation": "device_startup_override"}
                ],
            }
        )
        assert parsed.steady_state is not None
        assert parsed.steady_state.verdict == STEADY_STATE_DETECTED
        assert parsed.startup_fingerprints[0].interpretation == STARTUP_DEVICE_OVERRIDE

    def test_an_older_daemon_sends_neither_and_that_is_not_a_negative_result(self):
        parsed = parse_validation_session({})
        assert parsed.steady_state is None, "absent means 'this daemon does not derive it'"
        assert parsed.startup_fingerprints == []


# ── §12: the feature id is registered ────────────────────────────────────────


class TestThermalObservationFlag:
    def test_the_feature_id_resolves_through_the_registry(self):
        """The DEC-334 defect, guarded for this batch's own id.

        `daemon_supports` returns `None` for an id absent from
        `DAEMON_FEATURE_CAPABILITY_FLAGS`, and `None` is falsy — so an
        unregistered id makes the gate dead on every daemon, silently.
        `ventulus-diag validation start --kind thermal` gates on it (DEC-503).
        """
        assert daemon_supports("thermal_observation", _caps(thermal_observation=True)) is True
        assert daemon_supports("thermal_observation", _caps(thermal_observation=False)) is False


# ── §12: steady-state detection is observational ─────────────────────────────


class TestSteadyStateRendering:
    @pytest.mark.parametrize(
        "verdict",
        [STEADY_STATE_DETECTED, STEADY_STATE_NOT_ESTABLISHED, STEADY_STATE_INSUFFICIENT],
    )
    def test_no_verdict_renders_as_a_failure(self, verdict):
        """§3 forbids turning 'did not settle' into a verdict about the cooler.

        A run stopped early and a loop that genuinely cannot stabilise produce
        the same token, so nothing here may reach a failure tone.
        """
        assert steady_state_tone(verdict) != "bad"
        assert steady_state_tone(verdict) != "critical"

    def test_the_three_verdicts_are_distinguishable(self):
        """Otherwise a renderer that returned one label for everything passes."""
        labels = {
            steady_state_label(v)
            for v in (
                STEADY_STATE_DETECTED,
                STEADY_STATE_NOT_ESTABLISHED,
                STEADY_STATE_INSUFFICIENT,
            )
        }
        assert len(labels) == 3

    def test_an_unrecognised_verdict_is_rendered_not_dropped(self):
        """273-i: a newer daemon must not be able to make a result vanish."""
        text = steady_state_label("some_future_verdict")
        assert text and text != UNKNOWN_TEXT
        assert "future" in text.lower()

    def test_the_criterion_is_carried_through_verbatim(self):
        """§3 requires the exact rule be reported alongside the verdict.

        Asserted as pass-through, not against a literal: the thresholds live in
        the daemon's constants, and a GUI-side copy would be falsified the
        moment either moved.
        """
        # Content is arbitrary: this asserts PASS-THROUGH, and using the
        # daemon's exact wording here would be the restatement the test
        # exists to prevent.
        criterion = "slope and spread thresholds, held over N windows"
        view = build_steady_state_view(
            ValidationSteadyState(verdict=STEADY_STATE_DETECTED, criterion=criterion)
        )
        assert view is not None
        assert view.criterion == criterion

    def test_no_temperature_recorded_yields_no_view_at_all(self):
        assert build_steady_state_view(None) is None


# ── §12: a startup override is not a control failure ─────────────────────────


class TestStartupFingerprintRendering:
    def test_a_honoured_duty_never_renders_as_a_failure(self):
        """§1's prohibition, asserted directly."""
        views = build_startup_views(
            [
                ValidationStartupFingerprint(
                    member_id="pump1",
                    override_observed=True,
                    peak_rpm=3400,
                    post_override_rpm=1040,
                    requested_pct_during=35,
                    readback_pct_during=35,
                    interpretation=STARTUP_DEVICE_OVERRIDE,
                )
            ]
        )
        assert views[0].tone not in ("bad", "critical")
        # The duty evidence must reach the reader: the two agreeing is exactly
        # what rules the control fault out, so a peak RPM shown alone would
        # invite the reading §1 forbids.
        duty = [r.value for r in views[0].rows if r.label.startswith("Duty")]
        assert duty and "35%" in duty[0] and "readback" in duty[0]

    def test_even_a_mismatch_is_not_a_failure_tone(self):
        """The strongest available reading is `warn`, never a fault."""
        assert startup_tone(STARTUP_COMMAND_MISMATCH) == TONE_WARN
        assert startup_tone(STARTUP_COMMAND_MISMATCH) not in ("bad", "critical")

    def test_the_interpretations_are_distinguishable(self):
        assert startup_tone(STARTUP_DEVICE_OVERRIDE) != startup_tone(STARTUP_COMMAND_MISMATCH)
        assert startup_tone(STARTUP_NONE_OBSERVED) != startup_tone(STARTUP_COMMAND_MISMATCH)
