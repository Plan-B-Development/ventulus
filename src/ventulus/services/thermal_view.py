"""Rendering for thermal observations, steady state and startup fingerprints.

AIO Phase 8 Batch 3a (DEC-335), §1 / §3. Qt-free and total: every function here
takes plain models and returns frozen dataclasses, so the wording and tone
decisions are testable headlessly. Since DEC-503 its consumer is
``ventulus-diag validation show|status``; the GUI's session dialog, live block,
isolation-template gate and timeline chart left with the sessions.

# Two rules this module exists to enforce

**Unknown is not zero.** A `None` power, temperature or RPM renders as
[`UNKNOWN_TEXT`], never as `0 W`. On the reference host `k10temp` publishes no
power attribute at all, so "not known" is the *common* case for package power,
and a dash that means "we cannot see this" is the honest answer where a `0 W`
would be a claim about an idle machine.

**A startup override is a device behaviour, not a fault.** §1 is explicit: do
not diagnose a temporary high RPM as failed PWM control while command and
readback remain valid. The daemon decides that and sends a token; this module
renders the token and the duty evidence beside it. It never re-derives a verdict
from the RPM, and nothing here can produce a failure tone from a fingerprint.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ventulus.api.models import (
    STARTUP_COMMAND_MISMATCH,
    STARTUP_DEVICE_OVERRIDE,
    STARTUP_NONE_OBSERVED,
    STARTUP_UNRESOLVED,
    STEADY_STATE_DETECTED,
    STEADY_STATE_INSUFFICIENT,
    STEADY_STATE_NOT_ESTABLISHED,
    ValidationStartupFingerprint,
    ValidationSteadyState,
)

#: What every unreadable value renders as. One constant so a `None` cannot
#: appear as a dash in one table and "n/a" in another.
UNKNOWN_TEXT = "—"

#: Tone tokens, matching the ones the rest of the GUI's view-models emit.
TONE_NEUTRAL = "neutral"
TONE_GOOD = "good"
TONE_INFO = "info"
TONE_WARN = "warn"

STEADY_STATE_LABELS = {
    STEADY_STATE_DETECTED: "Steady",
    STEADY_STATE_NOT_ESTABLISHED: "Not established",
    STEADY_STATE_INSUFFICIENT: "Insufficient data",
}

#: **No token maps to a failure tone, and that is deliberate.** §3 forbids
#: turning "did not settle" into a verdict about the cooler: a run stopped early
#: and a loop that genuinely cannot stabilise produce the same token, and the
#: data cannot tell them apart.
STEADY_STATE_TONES = {
    STEADY_STATE_DETECTED: TONE_GOOD,
    STEADY_STATE_NOT_ESTABLISHED: TONE_INFO,
    STEADY_STATE_INSUFFICIENT: TONE_NEUTRAL,
}

STARTUP_LABELS = {
    STARTUP_DEVICE_OVERRIDE: "Device startup override",
    STARTUP_UNRESOLVED: "Override did not resolve",
    STARTUP_NONE_OBSERVED: "No startup override",
    STARTUP_COMMAND_MISMATCH: "Command/readback mismatch",
}

#: Again, no failure tone. `STARTUP_COMMAND_MISMATCH` is the strongest reading
#: available and it is only `warn`: it says the benign explanation is
#: unsupported, which is a weaker claim than asserting a fault.
STARTUP_TONES = {
    STARTUP_DEVICE_OVERRIDE: TONE_INFO,
    STARTUP_UNRESOLVED: TONE_INFO,
    STARTUP_NONE_OBSERVED: TONE_NEUTRAL,
    STARTUP_COMMAND_MISMATCH: TONE_WARN,
}


def _titleise(token: str) -> str:
    """Fallback wording for a token this build does not know.

    273-i: an unrecognised token is **rendered**, never dropped. A newer daemon
    naming a state this GUI predates must still put something on screen.
    """
    return token.replace("_", " ").strip().capitalize() or UNKNOWN_TEXT


def steady_state_label(verdict: str) -> str:
    return STEADY_STATE_LABELS.get(verdict) or _titleise(verdict)


def steady_state_tone(verdict: str) -> str:
    return STEADY_STATE_TONES.get(verdict, TONE_NEUTRAL)


def startup_label(token: str) -> str:
    return STARTUP_LABELS.get(token) or _titleise(token)


def startup_tone(token: str) -> str:
    return STARTUP_TONES.get(token, TONE_NEUTRAL)


def celsius_text(value: float | None) -> str:
    return UNKNOWN_TEXT if value is None else f"{value:.1f} °C"


def slope_text(value: float | None) -> str:
    """Signed, because the sign is the information — is it still climbing?"""
    return UNKNOWN_TEXT if value is None else f"{value:+.2f} °C/min"


def duration_text(ms: int | None) -> str:
    if ms is None:
        return UNKNOWN_TEXT
    seconds = ms // 1000
    if seconds < 60:
        return f"{seconds} s"
    return f"{seconds // 60}m {seconds % 60:02d}s"


@dataclass(frozen=True)
class InfoRow:
    label: str
    value: str
    tone: str = TONE_NEUTRAL


@dataclass(frozen=True)
class SteadyStateView:
    verdict: str
    verdict_label: str
    tone: str
    rows: list[InfoRow] = field(default_factory=list)
    #: The daemon's own criterion string, rendered verbatim (§3 requires the
    #: rule be reported). Empty when the daemon sent none.
    criterion: str = ""


@dataclass(frozen=True)
class StartupFingerprintView:
    member_id: str
    role: str
    interpretation: str
    interpretation_label: str
    tone: str
    rows: list[InfoRow] = field(default_factory=list)


def build_steady_state_view(steady: ValidationSteadyState | None) -> SteadyStateView | None:
    """Render §3's result. ``None`` in, ``None`` out — no temperature recorded."""
    if steady is None:
        return None
    rows = [
        InfoRow("Mean temperature", celsius_text(steady.mean_c)),
        InfoRow("Peak temperature", celsius_text(steady.peak_c)),
        InfoRow("Temperature trend", slope_text(steady.slope_c_per_min)),
        InfoRow(
            "Variation",
            UNKNOWN_TEXT if steady.stddev_c is None else f"±{steady.stddev_c:.2f} °C",
        ),
        InfoRow("Warm-up", duration_text(steady.warmup_ms)),
        # On the samples' own timeline: how far into the session it settled.
        InfoRow(
            "Steady from",
            UNKNOWN_TEXT
            if steady.start_ms is None
            else f"{duration_text(steady.start_ms)} into the session",
        ),
        InfoRow("Confidence", steady.confidence.capitalize() or UNKNOWN_TEXT),
    ]
    return SteadyStateView(
        verdict=steady.verdict,
        verdict_label=steady_state_label(steady.verdict),
        tone=steady_state_tone(steady.verdict),
        rows=rows,
        criterion=steady.criterion or "",
    )


def build_startup_views(
    fingerprints: list[ValidationStartupFingerprint],
    *,
    display_name=None,
) -> list[StartupFingerprintView]:
    """Render §1's per-member fingerprints.

    ``display_name`` resolves a member id to the user's name for it, following
    the same injection the other view-models use rather than reaching for the
    alias store from a Qt-free module.
    """
    out: list[StartupFingerprintView] = []
    for f in fingerprints:
        name = display_name(f.member_id) if display_name else f.member_id
        rows = [
            InfoRow("Member", name or f.member_id or UNKNOWN_TEXT),
            InfoRow(
                "Peak RPM",
                UNKNOWN_TEXT if f.peak_rpm is None else f"{f.peak_rpm} RPM",
            ),
            InfoRow(
                "Settled RPM",
                UNKNOWN_TEXT if f.post_override_rpm is None else f"{f.post_override_rpm} RPM",
            ),
            InfoRow("Override duration", duration_text(f.override_duration_ms)),
            InfoRow("Transition", duration_text(f.transition_ms)),
            # The duty pair is what makes the benign reading legible. §1's whole
            # point is that these two agreeing is what rules out a control
            # fault, so they are shown together and never separately.
            InfoRow(
                "Duty during override",
                _duty_pair_text(f.requested_pct_during, f.readback_pct_during),
            ),
        ]
        out.append(
            StartupFingerprintView(
                member_id=f.member_id,
                role=f.role,
                interpretation=f.interpretation,
                interpretation_label=startup_label(f.interpretation),
                tone=startup_tone(f.interpretation),
                rows=rows,
            )
        )
    return out


def _duty_pair_text(requested: int | None, readback: int | None) -> str:
    if requested is None and readback is None:
        return UNKNOWN_TEXT
    req = UNKNOWN_TEXT if requested is None else f"{requested}%"
    rb = UNKNOWN_TEXT if readback is None else f"{readback}%"
    return f"commanded {req} · readback {rb}"
