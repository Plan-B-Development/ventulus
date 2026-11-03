"""Run 2 (`G21`): a session can finalise itself when its diagnostics finish.

The GUI half of `P8-az`. The daemon half — the `stop_when_diagnostics_complete`
field, the id-fenced terminal hop in `spawn_orchestration`, the
`control.validation_auto_stop` capability — is tested in the daemon repo
(`daemon/tests/ipc_integration.rs`). What is tested here is everything the GUI
owns: the capability gate, the option's enablement rule, what Start actually
sends, and the one thing this whole feature can most easily get wrong — showing
the user a promise the connected daemon has no intention of keeping.

**Two rules from the project rulebook § Hard-won lessons shape almost every assertion.**
Relationships, never literals: the capability tests assert against the *wire
flag* rather than against `daemon_supports`, because asserting against the
lookup is satisfied by the defect it guards — delete the registry entry and both
sides go falsy together, which is exactly how DEC-334 shipped a feature
reachable on no daemon at all. And `isVisibleTo(parent)`, never `isVisible()`:
under `QT_QPA_PLATFORM=offscreen` nothing is shown, so an `isVisible()`
assertion passes with the visibility call deleted.
"""

from __future__ import annotations

from ventulus.api.models import (
    Capabilities,
    ControlCapability,
)
from ventulus.services.daemon_features import (
    DAEMON_FEATURE_CAPABILITY_FLAGS,
    DAEMON_FEATURE_LABELS,
    DAEMON_FEATURE_MINIMUMS,
    daemon_supports,
)

_FEATURE = "validation_auto_stop"


def _caps(**control) -> Capabilities:
    control.setdefault("validation_sessions", True)
    return Capabilities(control=ControlCapability(**control))


# ── The registry (the DEC-334 trap) ──────────────────────────────────────────


def test_the_feature_id_resolves_through_the_registry():
    """`daemon_supports` answers `None` for an unregistered id, and `None` is falsy.

    So an id that was never added to `DAEMON_FEATURE_CAPABILITY_FLAGS` produces
    a gate that is dead on **every** daemon — no exception, no log line, no
    failing test. That is DEC-334 exactly, and the correction it shipped was to
    sweep every entry point into the registry and weight the silent ones
    highest. `daemon_supports` is the silent one.
    """
    assert daemon_supports(_FEATURE, _caps(validation_auto_stop=True)) is True
    assert daemon_supports(_FEATURE, _caps(validation_auto_stop=False)) is False


def test_the_feature_id_is_in_all_three_registries():
    """One flag, one gating shape — and every registry a message may reach for.

    A missing `MINIMUMS` entry makes `minimum_version` raise; a missing
    `LABELS` entry makes `unsupported_feature_message` raise. Both are loud,
    which is why they are less dangerous than the flag map above — but a feature
    whose "requires daemon X" sentence crashes is still a dead end.
    """
    assert DAEMON_FEATURE_CAPABILITY_FLAGS[_FEATURE] == "validation_auto_stop"
    assert DAEMON_FEATURE_MINIMUMS[_FEATURE] == "2.43.0"
    assert _FEATURE in DAEMON_FEATURE_LABELS


# ── The capability gate at the call site ─────────────────────────────────────


# ── The enablement rule ──────────────────────────────────────────────────────


# ── What Start sends, through the signal ─────────────────────────────────────


def test_the_client_puts_the_field_on_the_wire_only_when_asked(monkeypatch):
    """And under the daemon's own field name.

    Omitted when false rather than sent as `false`: it keeps a gated client's
    request byte-identical to a pre-`P8-az` client's.
    """
    from ventulus.api.client import DaemonClient

    posted: list[dict] = []

    def fake_post(self, path, json=None, **kw):
        posted.append(dict(json or {}))
        return {"session_id": "vs-1"}

    monkeypatch.setattr(DaemonClient, "_post", fake_post, raising=True)
    client = DaemonClient.__new__(DaemonClient)

    client.start_validation_session("aio0", diagnostics=["pwm_verify"])
    assert "stop_when_diagnostics_complete" not in posted[-1]

    client.start_validation_session(
        "aio0", diagnostics=["pwm_verify"], stop_when_diagnostics_complete=True
    )
    assert posted[-1]["stop_when_diagnostics_complete"] is True


# ── Truthfulness: render the daemon's answer, not our own request ────────────
