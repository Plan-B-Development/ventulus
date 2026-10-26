"""The duty-drift notice on the System State page (DEC-404 S4-3, S4-12).

A header the daemon stopped correcting (``duty_not_holding``, DEC-406) raises
one condition card per episode; corrections that held are a reading in the
Interference Monitor; and the card counts everywhere the page's conditions
count — the pill AND the pop-out — so the two cannot disagree (DEC-379).
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QLabel

from tests.pwm_report_fixtures import CPU, SYS, fan
from ventulus.api.models import (
    ConnectionState,
    HardwareDiagnosticsResult,
    HwmonChipInfo,
    HwmonDiagnostics,
    OperationMode,
    ThermalSafetyInfo,
    parse_fans,
)
from ventulus.services.app_state import AppState
from ventulus.services.duty_drift import (
    NO_DRIFT,
    FanFlag,
    drift_key,
    duty_drift_state,
    found_manual_key,
    write_failing_key,
)
from ventulus.services.system_state_view import SilenceState, build_system_state_vm
from ventulus.ui.widgets.readiness_report import build_readiness_report_html


def _diag() -> HardwareDiagnosticsResult:
    return HardwareDiagnosticsResult(
        hwmon=HwmonDiagnostics(
            chips_detected=[
                HwmonChipInfo(chip_name="nct6798", expected_driver="nct6775", header_count=5)
            ],
            total_headers=2,
            writable_headers=2,
        ),
        thermal_safety=ThermalSafetyInfo(state="normal", cpu_sensor_found=True),
    )


def _state_from(fans: list[dict], names: dict[str, str] | None = None):
    names = names or {}
    return duty_drift_state(parse_fans({"fans": fans}), lambda fid: names.get(fid, fid))


# ── Reading the poll ────────────────────────────────────────────────────────


def test_an_older_daemon_reports_nothing_rather_than_no_drift():
    entry = fan(CPU, corrections=None, not_holding=None)
    state = _state_from([entry])
    assert state == NO_DRIFT and state.reported is False


def test_the_poll_is_read_into_one_state():
    state = _state_from(
        [fan(CPU, corrections=5, not_holding=True), fan(SYS, corrections=1)],
        {CPU: "CPU fan"},
    )
    assert state.reported
    assert [(d.header_id, d.name, d.corrections) for d in state.not_holding] == [
        (CPU, "CPU fan", 5)
    ]
    assert state.corrections == ((CPU, "CPU fan", 5), (SYS, SYS, 1))


# ── The card, the pill, the pop-out ─────────────────────────────────────────


def _cards(vm):
    return {c.key: c for c in vm.issue_cards}


def test_a_header_not_holding_raises_one_counted_card():
    quiet = build_system_state_vm(_diag(), duty_drift=NO_DRIFT)
    drift = _state_from([fan(CPU, corrections=3, not_holding=True)], {CPU: "CPU fan"})
    vm = build_system_state_vm(_diag(), duty_drift=drift)
    card = _cards(vm)[drift_key(CPU)]
    assert card.title == "Fan duty is not holding"
    assert "CPU fan" in card.detail and "3 time(s)" in card.detail
    assert vm.issues_requiring_attention == quiet.issues_requiring_attention + 1


def test_corrections_that_held_are_a_reading_not_a_card():
    held = _state_from([fan(CPU, corrections=2, not_holding=False)], {CPU: "CPU fan"})
    vm = build_system_state_vm(_diag(), duty_drift=held)
    assert not any(k.startswith("duty_not_holding_") for k in _cards(vm))
    assert "CPU fan (2)" in vm.interference.corrections_line
    assert vm.interference.title == "No BIOS/EC Reclaim Detected"
    assert vm.interference.severity_state == "ok", "a count, never an alarm"
    # Nothing to say without corrections.
    none = build_system_state_vm(_diag(), duty_drift=_state_from([fan(CPU)]))
    assert none.interference.corrections_line == ""
    assert none.interference.title == "No Interference Detected"


def test_the_pop_out_counts_the_same_card_and_escapes_the_name():
    """DEC-379: the page and its pop-out must never disagree."""
    drift = _state_from([fan(CPU, corrections=3, not_holding=True)], {CPU: "<b>Pump</b> & fan"})
    html = build_readiness_report_html(_diag(), duty_drift=drift)
    assert "Fan duty is not holding" in html
    assert "&lt;b&gt;Pump&lt;/b&gt; &amp; fan" in html
    assert "<b>Pump</b> & fan" not in html
    clean = build_readiness_report_html(_diag(), duty_drift=NO_DRIFT)
    assert "Fan duty is not holding" not in clean


def test_the_card_detail_escapes_the_name():
    drift = _state_from([fan(CPU, corrections=3, not_holding=True)], {CPU: "<i>x</i>"})
    card = _cards(build_system_state_vm(_diag(), duty_drift=drift))[drift_key(CPU)]
    assert "&lt;i&gt;x&lt;/i&gt;" in card.detail and "<i>x</i>" not in card.detail


# ── Once per episode ────────────────────────────────────────────────────────


def test_a_dismissal_covers_its_episode_and_not_the_next():
    first = _state_from([fan(CPU, corrections=3, not_holding=True)])
    token = _cards(build_system_state_vm(_diag(), duty_drift=first))[drift_key(CPU)].silence.token
    silenced = SilenceState(dismissed=frozenset({token}))
    # The same episode stays dismissed…
    vm = build_system_state_vm(_diag(), duty_drift=first, silence=silenced)
    assert drift_key(CPU) not in _cards(vm)
    assert vm.issues_requiring_attention >= 1, "the pill still counts it (DEC-359)"
    # …and a fresh give-up — new corrections, so a new count — speaks again.
    second = _state_from([fan(CPU, corrections=6, not_holding=True)])
    vm = build_system_state_vm(_diag(), duty_drift=second, silence=silenced)
    assert drift_key(CPU) in _cards(vm)


def test_each_header_is_its_own_card():
    drift = _state_from(
        [fan(CPU, corrections=3, not_holding=True), fan(SYS, corrections=4, not_holding=True)]
    )
    cards = _cards(build_system_state_vm(_diag(), duty_drift=drift))
    assert {drift_key(CPU), drift_key(SYS)} <= set(cards)
    assert drift_key(CPU) != drift_key(SYS)
    assert "#" not in drift_key(CPU) and "@" not in drift_key(CPU)


# ── Failing writes and a header found in manual mode ────────────────────────

OPENFAN = "openfan:ch03"


def _flagged(fid: str, **flags) -> dict:
    entry = fan(fid, source="openfan" if fid.startswith("openfan:") else "hwmon")
    entry.update(flags)
    return entry


def test_an_older_daemon_flags_neither():
    state = _state_from([fan(CPU), fan(OPENFAN, source="openfan")])
    assert state.write_failing == () and state.found_in_manual_mode == ()


def test_the_poll_flags_failing_writes_and_manual_mode_per_fan():
    state = _state_from(
        [
            _flagged(CPU, write_failing=True, found_in_manual_mode=False),
            _flagged(SYS, write_failing=False, found_in_manual_mode=True),
            _flagged(OPENFAN, write_failing=True),
        ],
        {CPU: "CPU fan", OPENFAN: "Front intake"},
    )
    assert state.write_failing == (FanFlag(CPU, "CPU fan"), FanFlag(OPENFAN, "Front intake"))
    assert state.found_in_manual_mode == (FanFlag(SYS, SYS),)


def test_a_fan_whose_writes_fail_raises_one_counted_card_that_is_not_critical():
    quiet = build_system_state_vm(_diag(), duty_drift=NO_DRIFT)
    failing = _state_from([_flagged(OPENFAN, write_failing=True)], {OPENFAN: "<b>Front</b>"})
    vm = build_system_state_vm(_diag(), duty_drift=failing)
    card = _cards(vm)[write_failing_key(OPENFAN)]
    assert card.title == "Fan speed cannot be set"
    assert "&lt;b&gt;Front&lt;/b&gt;" in card.detail and "<b>Front</b>" not in card.detail
    assert vm.issues_requiring_attention == quiet.issues_requiring_attention + 1
    assert vm.issue_count_state == "warn", "losing control is ACTION REQUIRED, not CRITICAL"


def test_a_header_found_in_manual_mode_raises_one_counted_card():
    quiet = build_system_state_vm(_diag(), duty_drift=NO_DRIFT)
    found = _state_from([_flagged(SYS, found_in_manual_mode=True)], {SYS: "Rear exhaust"})
    vm = build_system_state_vm(_diag(), duty_drift=found)
    card = _cards(vm)[found_manual_key(SYS)]
    assert card.title == "Header was already in manual mode"
    assert "Rear exhaust" in card.detail
    assert vm.issues_requiring_attention == quiet.issues_requiring_attention + 1
    assert write_failing_key(SYS) not in _cards(vm), "one fact, one card"


def test_the_pop_out_carries_both_cards():
    both = _state_from(
        [_flagged(CPU, write_failing=True), _flagged(SYS, found_in_manual_mode=True)]
    )
    html = build_readiness_report_html(_diag(), duty_drift=both)
    assert "Fan speed cannot be set" in html and "Header was already in manual mode" in html
    clean = build_readiness_report_html(_diag(), duty_drift=NO_DRIFT)
    assert "Fan speed cannot be set" not in clean
    assert "Header was already in manual mode" not in clean


def test_the_three_per_fan_keys_never_collide():
    keys = {drift_key(CPU), write_failing_key(CPU), found_manual_key(CPU)}
    assert len(keys) == 3
    assert not any("#" in k or "@" in k for k in keys)


# ── The live page ────────────────────────────────────────────────────────────


def _page(qtbot):
    from ventulus.services.diagnostics_service import DiagnosticsService
    from ventulus.ui.pages.system_state_page import SystemStatePage

    state = AppState()
    state.set_connection(ConnectionState.CONNECTED)
    state.set_mode(OperationMode.AUTOMATIC)
    page = SystemStatePage(state=state, diagnostics_service=DiagnosticsService(state))
    qtbot.addWidget(page)
    page._on_hw_diag_ok(_diag())
    return page, state


def _title(page, header_id):
    return page.findChild(QLabel, f"SystemState_IssueTitle_{drift_key(header_id)}")


def test_the_page_raises_and_drops_the_card_from_the_poll(qtbot):
    page, state = _page(qtbot)
    assert _title(page, CPU) is None, "precondition: no card before the poll says so"
    state.set_fans(parse_fans({"fans": [fan(CPU, corrections=3, not_holding=True)]}))
    assert _title(page, CPU) is not None
    assert page._duty_drift().not_holding, "the page's one accessor carries the state"
    state.set_fans(parse_fans({"fans": [fan(CPU, corrections=3, not_holding=False)]}))
    # The health card rebuilds with deleteLater; dispatch those deletes so the
    # old card is really gone rather than merely scheduled to go.
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not page._duty_drift().not_holding
    assert _title(page, CPU) is None


def test_the_page_raises_and_drops_a_failing_write_card_from_the_poll(qtbot):
    page, state = _page(qtbot)
    title = f"SystemState_IssueTitle_{write_failing_key(CPU)}"
    assert page.findChild(QLabel, title) is None, "precondition: no card before the poll"
    state.set_fans(parse_fans({"fans": [_flagged(CPU, write_failing=True)]}))
    assert page.findChild(QLabel, title) is not None
    state.set_fans(parse_fans({"fans": [_flagged(CPU, write_failing=False)]}))
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert page.findChild(QLabel, title) is None


def test_a_poll_cards_dismissal_survives_a_render_before_the_first_poll(qtbot):
    """`/diagnostics/hardware` cannot say a per-fan card is gone: only the poll
    can. A payload that lands first must not prune its dismissal."""
    from ventulus.services.diagnostics_service import DiagnosticsService
    from ventulus.ui.pages.system_state_page import SystemStatePage

    found = _state_from([_flagged(SYS, found_in_manual_mode=True)])
    token = _cards(build_system_state_vm(_diag(), duty_drift=found))[
        found_manual_key(SYS)
    ].silence.token
    assert token, "precondition: the card can be dismissed"
    state = AppState()
    state.set_connection(ConnectionState.CONNECTED)
    page = SystemStatePage(state=state, diagnostics_service=DiagnosticsService(state))
    qtbot.addWidget(page)
    page._settings_svc.update(dismissed_health_items=[token])

    page._on_hw_diag_ok(_diag())
    assert page._settings_svc.settings.dismissed_health_items == [token], (
        "a payload before the first poll pruned a poll card's dismissal"
    )
    # The discriminator: once a poll says the header is not flagged, the next
    # payload prunes it, so the first arm is the guard and not a dead prune.
    state.set_fans(parse_fans({"fans": [fan(SYS)]}))
    page._on_hw_diag_ok(_diag())
    assert page._settings_svc.settings.dismissed_health_items == []


def test_a_disconnect_clears_the_live_drift(qtbot):
    page, state = _page(qtbot)
    state.set_fans(parse_fans({"fans": [fan(CPU, corrections=3, not_holding=True)]}))
    assert page._duty_drift().not_holding
    page.set_live(False)
    assert page._duty_drift() == NO_DRIFT
