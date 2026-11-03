"""AIO Phase 8 Batch 1 (DEC-333): safety preflight, control-path discovery, provenance.

The GUI half of `AIO-Phase7-Batch1.md` §7. Its daemon half lives in the paired
repo's `daemon/tests/discovery_phase8.rs`.

Three disciplines from the project rulebook § Hard-won lessons run through this file:

* **Assert a RELATIONSHIP, never a literal.** The pump fixture is a header the
  hardware labels ``AIO_PUMP`` that the user has downgraded to ``chassis_fan``.
  A test passing ``is_pump=True`` as a literal is satisfied by a call site that
  reads the wire ``role`` — the exact DEC-312 defect the line exists to prevent.
* **``isVisibleTo(parent)``, never ``isVisible()``.** Under
  ``QT_QPA_PLATFORM=offscreen`` nothing is shown, so ``isVisible()`` is ``False``
  for every widget and an assertion on it passes with ``setVisible(...)``
  deleted.
* **Test the call site, not just the extracted rule.** A view-model with
  thorough unit tests and nothing asserting the production path calls it is an
  untested rule.
"""

from __future__ import annotations

import json

from PySide6.QtWidgets import QPushButton

from ventulus.api.models import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_UNKNOWN,
    CONTROL_PATH_CONFIRMED,
    CONTROL_PATH_MULTIPLE,
    CONTROL_PATH_NO_RESPONSE,
    DIAGNOSTIC_CONTROL_PATH,
    PREFLIGHT_BLOCKED,
    PREFLIGHT_FAIL,
    PREFLIGHT_NOT_APPLICABLE,
    PREFLIGHT_PASS,
    PREFLIGHT_READY,
    PREFLIGHT_UNKNOWN,
    PREFLIGHT_WARN,
    PROVENANCE_COMMANDED,
    PROVENANCE_DERIVED,
    PROVENANCE_OBSERVED,
    VALIDATION_DIAG_CONTROL_PATH,
    Capabilities,
    ConnectionState,
    ControlCapability,
    ControlPathRecord,
    FanReading,
    HwmonHeader,
    SensorReading,
    ValidationEvidence,
    ValidationSession,
    parse_control_path_run,
    parse_control_path_status,
    parse_preflight_report,
)
from ventulus.services.app_state import AppState
from ventulus.services.control_path_view import (
    build_control_path_view,
    relationship_summary_line,
    restore_note,
)
from ventulus.services.diagnostics_service import DiagnosticsService
from ventulus.services.preflight_view import build_preflight_view
from ventulus.services.provenance import (
    UNVERIFIABLE,
    classified_rows,
    classify,
    from_envelope,
)
from ventulus.services.validation_export import session_json
from ventulus.ui.pages.hardware_page import HardwarePage
from ventulus.ui.widgets.pwm_header_card import PwmHeaderCard

# ── fixtures ─────────────────────────────────────────────────────────────────


def _caps(**control) -> Capabilities:
    control.setdefault("header_roles", True)
    control.setdefault("pwm_characterization", True)
    control.setdefault("cooling_devices", True)
    control.setdefault("validation_sessions", True)
    control.setdefault("control_path_discovery", True)
    control.setdefault("diagnostic_preflight", True)
    return Capabilities(control=ControlCapability(**control))


def _downgraded_pump(**kw) -> HwmonHeader:
    """A header the HARDWARE labels ``AIO_PUMP`` that the USER set to ``chassis_fan``.

    The whole point of this fixture (DEC-312). The wire ``role`` reads
    ``chassis_fan`` because a user assignment fully substitutes for inference in
    the *display* role — while the daemon's safety predicate is a UNION and
    still refuses to stop it. Any call site reading ``role == "pump"`` therefore
    gets the wrong answer here, and only here.
    """
    base = {
        "id": "hwmon:nct6799:isa-0a20:pwm5:AIO_PUMP",
        "label": "AIO_PUMP",
        "chip_name": "nct6799",
        "device_id": "isa-0a20",
        "pwm_index": 5,
        "supports_enable": True,
        "rpm_available": True,
        "is_writable": True,
        "role": "chassis_fan",
        "role_source": "user_assigned",
        "effective_min_pwm_pct": 30,
        "stop_permitted": False,
    }
    base.update(kw)
    return HwmonHeader(**base)


def _plain_fan(**kw) -> HwmonHeader:
    base = {
        "id": "hwmon:nct6799:isa-0a20:pwm1:CHA_FAN1",
        "label": "CHA_FAN1",
        "chip_name": "nct6799",
        "device_id": "isa-0a20",
        "pwm_index": 1,
        "supports_enable": True,
        "rpm_available": True,
        "is_writable": True,
        "role": "chassis_fan",
        "role_source": "label",
        "effective_min_pwm_pct": 0,
        "stop_permitted": True,
    }
    base.update(kw)
    return HwmonHeader(**base)


def _preflight_payload(**overrides) -> dict:
    checks = [
        {"check_id": "target_discoverable", "state": PREFLIGHT_PASS, "detail": "Header found"},
        {"check_id": "header_role", "state": PREFLIGHT_PASS, "detail": "Role 'pump'"},
        {"check_id": "pwm_writable", "state": PREFLIGHT_PASS, "detail": "PWM is writable"},
        {"check_id": "pwm_readback", "state": PREFLIGHT_PASS, "detail": "Reads back 45%"},
        {"check_id": "control_ownership", "state": PREFLIGHT_PASS, "detail": "Available"},
        {"check_id": "safe_minimum", "state": PREFLIGHT_PASS, "detail": "30%-100%"},
        {"check_id": "temperature_source", "state": PREFLIGHT_PASS, "detail": "cpu · 300 ms"},
        {"check_id": "thermal_state", "state": PREFLIGHT_PASS, "detail": "No failsafe"},
        {"check_id": "reclaim_state", "state": PREFLIGHT_PASS, "detail": "No reclaim"},
        {"check_id": "original_state", "state": PREFLIGHT_PASS, "detail": "Captured 45%"},
        {"check_id": "supporting_cooling", "state": PREFLIGHT_PASS, "detail": "2 of 2 running"},
    ]
    payload = {
        "header_id": _downgraded_pump().id,
        "diagnostic": DIAGNOSTIC_CONTROL_PATH,
        "verdict": PREFLIGHT_READY,
        "checks": checks,
        "blocking": [],
    }
    payload.update(overrides)
    return payload


def _run_payload(**overrides) -> dict:
    payload = {
        "run_id": "path-1",
        "header_id": _downgraded_pump().id,
        "state": "complete",
        "delta_pct": 25,
        "requested_cycles": 2,
        "window_seconds": 6,
        "baseline_pct": 40,
        "perturbed_pct": 65,
        "direction": "up",
        "channels": [
            {"tach_id": "pump", "label": "AIO_PUMP", "is_target_header": True},
            {"tach_id": "fan2", "label": "fan2", "monitor_only": True},
            {"tach_id": "fan3", "label": "fan3", "monitor_only": True},
        ],
        "cycles": [
            {
                "cycle": 1,
                "baseline_pct": 40,
                "perturbed_pct": 65,
                "direction": "up",
                "observations": [
                    {
                        "tach_id": "pump",
                        "baseline_rpm": 1350,
                        "perturbed_rpm": 1775,
                        "delta_rpm": 425,
                        "noise_floor_rpm": 50,
                        "responded": True,
                    },
                    {
                        "tach_id": "fan2",
                        "baseline_rpm": 900,
                        "perturbed_rpm": 905,
                        "delta_rpm": 5,
                        "noise_floor_rpm": 50,
                        "responded": False,
                    },
                    {
                        "tach_id": "fan3",
                        "baseline_rpm": 700,
                        "perturbed_rpm": 700,
                        "delta_rpm": 0,
                        "noise_floor_rpm": 50,
                        "responded": False,
                    },
                ],
            }
        ],
        "summary": {
            "relationship": CONTROL_PATH_CONFIRMED,
            "confidence": CONFIDENCE_HIGH,
            "candidates": [
                {
                    "tach_id": "pump",
                    "label": "AIO_PUMP",
                    "monitor_only": False,
                    "confidence": CONFIDENCE_HIGH,
                    "direction": "positive",
                    "baseline_rpm": 1350,
                    "perturbed_rpm": 1775,
                    "change_pct": 31.4,
                    "cycles_responded": 2,
                    "cycles_total": 2,
                }
            ],
            "measurement_resolution_ms": 1000,
            "sample_interval_ms": 500,
            "sample_count": 24,
            "confidence_notes": [],
        },
        "original_pct": 40,
        "restore_failed": False,
        "restore_outcome": "restored",
        "detail": None,
        "completed_unix_ms": 1_700_000_000_000,
    }
    payload.update(overrides)
    return payload


def _page(qtbot, *, client=None, caps=None):
    state = AppState()
    state.set_connection(ConnectionState.CONNECTED)
    state.set_capabilities(caps if caps is not None else _caps())
    pump, fan = _downgraded_pump(), _plain_fan()
    state.set_hwmon_headers([pump, fan])
    state.set_fans([FanReading(id=pump.id, rpm=1350), FanReading(id=fan.id, rpm=900)])
    state.set_sensors([SensorReading(id="cpu:pkg", label="CPU Package", value_c=54.0)])
    page = HardwarePage(state=state, diagnostics_service=DiagnosticsService(state), client=client)
    qtbot.addWidget(page)
    return page, state


# ── §7: model parsing and confidence serialisation ──────────────────────────


class TestModelParsing:
    def test_a_run_parses_with_its_confidence_and_candidates(self):
        run = parse_control_path_run(_run_payload())
        assert run.run_id == "path-1"
        assert run.summary is not None
        assert run.summary.relationship == CONTROL_PATH_CONFIRMED
        assert run.summary.confidence == CONFIDENCE_HIGH
        assert run.summary.candidates[0].change_pct == 31.4
        assert run.summary.measurement_resolution_ms == 1000
        assert run.channels[1].monitor_only is True

    def test_an_unknown_relationship_token_survives_parsing(self):
        """273-i: render an unrecognised token, never drop it."""
        run = parse_control_path_run(
            _run_payload(summary={"relationship": "future_shape", "confidence": "very_high"})
        )
        assert run.summary.relationship == "future_shape"
        view = build_control_path_view(run, header_label="AIO Pump")
        # Visible verbatim, and toned neutrally rather than as a failure.
        assert "future_shape" in view.relationship_word.lower().replace(" ", "_")
        assert view.relationship_tone == "muted"

    def test_missing_measurement_resolution_parses_as_unknown_not_zero(self):
        """§4: UNKNOWN rather than a guess — and `0 ms` is a guess."""
        payload = _run_payload()
        del payload["summary"]["measurement_resolution_ms"]
        run = parse_control_path_run(payload)
        assert run.summary.measurement_resolution_ms is None
        view = build_control_path_view(run, header_label="AIO Pump")
        assert "unknown" in view.resolution_text.lower()

    def test_a_status_carries_persisted_records(self):
        status = parse_control_path_status(
            {
                "run": _run_payload(),
                "records": [
                    {
                        "header_id": _downgraded_pump().id,
                        "relationship": CONTROL_PATH_CONFIRMED,
                        "confidence": CONFIDENCE_HIGH,
                        "tach_labels": ["fan5"],
                        "validated_unix_ms": 1_700_000_000_000,
                    }
                ],
            }
        )
        assert status.run is not None
        assert status.record_for(_downgraded_pump().id).confidence == CONFIDENCE_HIGH
        assert status.record_for("nope") is None

    def test_an_empty_status_is_not_an_error(self):
        status = parse_control_path_status({})
        assert status.run is None
        assert status.records == []


# ── §7: multiple / no-response / not-a-failure ──────────────────────────────


class TestRelationshipRendering:
    def test_multiple_responding_tachs_are_represented(self):
        payload = _run_payload()
        payload["summary"]["relationship"] = CONTROL_PATH_MULTIPLE
        payload["summary"]["candidates"].append(
            {
                "tach_id": "fan2",
                "label": "fan2",
                "monitor_only": True,
                "confidence": CONFIDENCE_HIGH,
                "direction": "positive",
                "baseline_rpm": 900,
                "perturbed_rpm": 1400,
                "change_pct": 55.5,
                "cycles_responded": 2,
                "cycles_total": 2,
            }
        )
        view = build_control_path_view(parse_control_path_run(payload), header_label="Pump")
        assert len(view.candidates) == 2
        assert {c.tach_id for c in view.candidates} == {"pump", "fan2"}
        # A monitor-only channel is labelled as such — it has no PWM of its own,
        # which is the §2 case the whole monitor-only read path exists for.
        assert any(c.monitor_only for c in view.candidates)

    def test_no_response_is_informational_never_a_failure(self):
        """The Overview forbids calling an unexpected RPM response a hardware fault."""
        payload = _run_payload()
        payload["summary"]["relationship"] = CONTROL_PATH_NO_RESPONSE
        payload["summary"]["confidence"] = CONFIDENCE_LOW
        payload["summary"]["candidates"] = []
        view = build_control_path_view(parse_control_path_run(payload), header_label="Pump")
        assert view.relationship_tone == "info"
        assert view.relationship_tone not in {"crit", "bad"}
        assert view.candidates == []
        # ...and it still says what it looked at, so "no response" is evidence
        # rather than an empty screen.
        assert len(view.quiet) == 3

    def test_unreadable_tachs_are_unknown_not_a_low_confidence_answer(self):
        payload = _run_payload()
        payload["summary"]["relationship"] = CONTROL_PATH_NO_RESPONSE
        payload["summary"]["confidence"] = CONFIDENCE_UNKNOWN
        payload["summary"]["candidates"] = []
        view = build_control_path_view(parse_control_path_run(payload), header_label="Pump")
        assert view.confidence_word == "Unknown"
        assert view.confidence_tone == "muted"

    def test_a_failed_restore_is_surfaced_prominently(self):
        """§1: "Restoration failure must be surfaced prominently"."""
        run = parse_control_path_run(
            _run_payload(restore_failed=True, restore_outcome="write_failed")
        )
        assert "could not be returned" in restore_note(run)
        view = build_control_path_view(run, header_label="Pump")
        assert view.restore_warning

    def test_a_thermal_skip_says_do_not_touch_it(self):
        """The header is high because the ladder put it there — say so, and say
        not to override it. `skipped_thermal_force` must never read as a fault."""
        run = parse_control_path_run(
            _run_payload(restore_failed=True, restore_outcome="skipped_thermal_force")
        )
        note = restore_note(run)
        assert "Thermal safety" in note
        assert "Do not set it manually" in note

    def test_an_unresponsive_driver_is_named_rather_than_left_to_the_fallback(self):
        """`DC-cx` / DEC-420/455: say the driver stopped answering, not the raw
        token the unrecognised-outcome fallback would echo."""
        run = parse_control_path_run(
            _run_payload(restore_failed=True, restore_outcome="skipped_unresponsive")
        )
        note = restore_note(run)
        assert "stopped answering" in note
        assert "skipped_unresponsive" not in note, "the fallback rendered instead"
        assert build_control_path_view(run, header_label="Pump").restore_warning

    def test_a_clean_run_raises_no_restore_warning(self):
        """The opposite branch — without it a note stuck on "always warn" passes."""
        assert restore_note(parse_control_path_run(_run_payload())) == ""

    def test_an_unrecognised_restore_outcome_still_warns(self):
        run = parse_control_path_run(
            _run_payload(restore_failed=True, restore_outcome="something_new")
        )
        assert "something_new" in restore_note(run)


# ── §7: GUI displays a blocked preflight reason ─────────────────────────────


class TestPreflightView:
    def test_a_ready_preflight_permits_the_run(self):
        view = build_preflight_view(parse_preflight_report(_preflight_payload()))
        assert view.verdict == PREFLIGHT_READY
        assert view.can_start is True
        assert view.blocked is False
        assert len(view.rows) == 11
        assert all(r.tone == "ok" for r in view.rows)

    def test_a_blocked_preflight_names_its_reason_and_stops_the_run(self):
        checks = _preflight_payload()["checks"]
        checks[7] = {
            "check_id": "thermal_state",
            "state": PREFLIGHT_FAIL,
            "detail": "Thermal safety is forcing fan output (emergency)",
        }
        view = build_preflight_view(
            parse_preflight_report(
                _preflight_payload(
                    verdict=PREFLIGHT_BLOCKED, checks=checks, blocking=["thermal_state"]
                )
            )
        )
        assert view.blocked is True
        assert view.can_start is False
        assert view.blocking_reasons == ["Thermal safety is forcing fan output (emergency)"]
        row = next(r for r in view.rows if r.check_id == "thermal_state")
        assert row.is_blocking is True
        assert row.tone == "crit"

    def test_a_blocker_the_daemon_did_not_publish_as_a_check_still_gets_a_reason(self):
        """`P8-aj`: the one case where the reason matters most.

        `blocking_reasons` was built only from rows, and rows come only from
        `checks` — so a daemon naming a blocker it did not also publish rendered
        "Cannot run this test:" followed by a bullet and nothing. Start was
        correctly refused and the user was told nothing.

        The discriminating arm is a blocker with NO matching check. A blocker
        that does have one is the pre-fix answer by construction and cannot show
        the fallback fired.
        """
        view = build_preflight_view(
            parse_preflight_report(
                _preflight_payload(
                    verdict=PREFLIGHT_BLOCKED,
                    blocking=["some_future_guard"],
                )
            )
        )
        assert view.blocked is True
        assert view.can_start is False
        # Precondition: the daemon really did not publish it as a check, or this
        # asserts nothing about the fallback.
        assert all(r.check_id != "some_future_guard" for r in view.rows)
        assert view.blocking_reasons == ["Some future guard"], (
            "a named blocker with no matching check must still produce a reason; "
            f"got {view.blocking_reasons}"
        )

    def test_a_published_blocker_still_uses_its_own_detail_not_the_fallback(self):
        """The complement: the fallback must not displace a real detail, and must
        not duplicate a reason that already came from a row."""
        checks = _preflight_payload()["checks"]
        checks[7] = {
            "check_id": "thermal_state",
            "state": PREFLIGHT_FAIL,
            "detail": "Thermal safety is forcing fan output (emergency)",
        }
        view = build_preflight_view(
            parse_preflight_report(
                _preflight_payload(
                    verdict=PREFLIGHT_BLOCKED, checks=checks, blocking=["thermal_state"]
                )
            )
        )
        assert view.blocking_reasons == ["Thermal safety is forcing fan output (emergency)"], (
            "a published blocker must keep its detail and must not be listed twice"
        )

    def test_the_view_reads_the_daemon_verdict_rather_than_re_deriving_it(self):
        """§6.1: "the GUI reflects daemon decisions".

        A row marked ``fail`` with the daemon reporting ``ready`` is a contract
        the GUI must not overrule — if it re-derived the roll-up, the two would
        disagree and the user would see the GUI's answer. This asserts the
        deliberate direction of that disagreement.
        """
        checks = _preflight_payload()["checks"]
        checks[0] = {"check_id": "target_discoverable", "state": PREFLIGHT_FAIL, "detail": "x"}
        view = build_preflight_view(
            parse_preflight_report(
                _preflight_payload(verdict=PREFLIGHT_READY, checks=checks, blocking=[])
            )
        )
        assert view.blocked is False
        assert view.can_start is True

    def test_an_unknown_verdict_with_named_blockers_still_blocks(self):
        """`verdict` is matched exactly, so a future token outside
        {ready, warn, blocked} would fail OPEN on the one field that gates a
        hardware-perturbing action. Reading the daemon's own `blocking[]` as
        well — a second daemon-authored field, not a re-derivation — makes that
        case fail safe instead of by luck."""
        checks = _preflight_payload()["checks"]
        checks[7] = {"check_id": "thermal_state", "state": PREFLIGHT_FAIL, "detail": "hot"}
        view = build_preflight_view(
            parse_preflight_report(
                _preflight_payload(
                    verdict="some_future_verdict",
                    checks=checks,
                    blocking=["thermal_state"],
                )
            )
        )
        assert view.blocked is True
        assert view.can_start is False
        # The token itself is still rendered verbatim (273-i), not swallowed.
        assert "future verdict" in view.verdict_word.lower()

    def test_unknown_and_not_applicable_are_muted_never_bad(self):
        """§5's mirror rule: lack of evidence is not a failure either."""
        checks = [
            {"check_id": "supporting_cooling", "state": PREFLIGHT_NOT_APPLICABLE, "detail": "n/a"},
            {"check_id": "pwm_readback", "state": PREFLIGHT_UNKNOWN, "detail": "?"},
        ]
        view = build_preflight_view(
            parse_preflight_report(_preflight_payload(checks=checks, verdict=PREFLIGHT_READY))
        )
        assert [r.tone for r in view.rows] == ["muted", "muted"]
        assert view.can_start is True

    def test_a_warning_preflight_still_permits_the_run(self):
        checks = _preflight_payload()["checks"]
        checks[6] = {
            "check_id": "temperature_source",
            "state": PREFLIGHT_WARN,
            "detail": "Every temperature reading is stale",
        }
        view = build_preflight_view(
            parse_preflight_report(_preflight_payload(verdict="warn", checks=checks))
        )
        assert view.can_start is True
        assert view.blocked is False

    def test_an_unavailable_preflight_does_not_block(self):
        """An older daemon has no preflight route. Refusing the diagnostic on
        that basis would make the feature less usable than before it existed —
        and the daemon still runs its own guards on the POST."""
        view = build_preflight_view(None, unavailable_reason="no route")
        assert view.unavailable is True
        assert view.blocked is False
        assert view.can_start is True

    def test_an_unrecognised_check_id_is_rendered_not_dropped(self):
        view = build_preflight_view(
            parse_preflight_report(
                _preflight_payload(
                    checks=[{"check_id": "future_check", "state": "pass", "detail": "d"}]
                )
            )
        )
        assert len(view.rows) == 1
        assert view.rows[0].label == "Future check"


# ── §7: GUI exposes Discover Control Path ───────────────────────────────────


# ── §6.3: the relationship row on the card ──────────────────────────────────


class TestRelationshipRow:
    def test_the_row_is_absent_until_something_has_been_discovered(self, qtbot):
        page, _ = _page(qtbot)
        card = next(iter(page.findChildren(PwmHeaderCard)))
        _expand_details(card)
        label = card.findChild(object, f"HeaderCard_Relationship_{_slug(card.header_id())}")
        assert label is not None
        # `isVisibleTo(parent)`, NOT `isVisible()`: offscreen makes the latter
        # False for every widget, so an assertion on it passes with the
        # setVisible call deleted (measured).
        #
        # The Details disclosure is EXPANDED first, or this would read False
        # because an ancestor is collapsed — passing whether or not the row's own
        # visibility rule works, which is no test at all.
        assert label.isVisibleTo(card) is False
        assert label.text() == ""

    def test_a_discovered_relationship_appears_with_its_confidence_and_stamp(self, qtbot):
        page, _ = _page(qtbot)
        page._control_paths = {
            _downgraded_pump().id: ControlPathRecord(
                header_id=_downgraded_pump().id,
                relationship=CONTROL_PATH_CONFIRMED,
                confidence=CONFIDENCE_HIGH,
                tach_ids=["fan5"],
                tach_labels=["fan5_input"],
                validated_unix_ms=1_700_000_000_000,
            )
        }
        page._refresh_cooling_section()
        card = next(
            c for c in page.findChildren(PwmHeaderCard) if c.header_id() == _downgraded_pump().id
        )
        # §6.3 puts the row inside the "Details" disclosure, so it is only
        # visible once that is open — which is the behaviour being asserted.
        _expand_details(card)
        label = card.findChild(object, f"HeaderCard_Relationship_{_slug(card.header_id())}")
        assert label.isVisibleTo(card) is True
        text = label.text()
        assert "fan5_input" in text
        assert "HIGH" in text
        assert "Last validated:" in text

    def test_unchanged_records_do_not_re_render_the_cards(self, qtbot):
        """The read repeats on every capability refresh and the records are
        usually identical, while the cooling section is already re-rendered by
        `fans_updated`. An unconditional refresh would redraw bytes that had not
        changed."""
        from ventulus.api.models import ControlPathStatus

        page, _ = _page(qtbot)
        record = ControlPathRecord(
            header_id=_downgraded_pump().id,
            relationship=CONTROL_PATH_CONFIRMED,
            confidence=CONFIDENCE_HIGH,
            tach_labels=["fan5"],
            validated_unix_ms=1_700_000_000_000,
        )
        calls: list[int] = []
        original = page._refresh_cooling_section
        page._refresh_cooling_section = lambda *a, **k: (calls.append(1), original())[1]

        def _get(records):
            return ControlPathStatus(records=records, from_status_endpoint=True)

        page._on_control_paths(_get([record]))
        assert len(calls) == 1, "the first, changed batch must render"
        page._on_control_paths(_get([record]))
        assert len(calls) == 1, "an identical batch must not render again"

        moved = ControlPathRecord(**{**record.__dict__, "confidence": "low"})
        page._on_control_paths(_get([moved]))
        assert len(calls) == 2, "a genuinely changed batch must render"

        # An EMPTY answer clears the cache: the daemon holds no relationships
        # (one was forgotten, or discovered again elsewhere), and a card must
        # not keep asserting one it dropped.
        page._on_control_paths(_get([]))
        assert len(calls) == 3
        assert page._control_paths == {}

    def test_the_summary_line_names_extra_channels_rather_than_hiding_them(self):
        record = ControlPathRecord(
            relationship=CONTROL_PATH_MULTIPLE,
            tach_labels=["fan2", "fan3", "fan4"],
        )
        line = relationship_summary_line(record)
        assert "fan2" in line
        assert "+2 more" in line

    def test_no_record_yields_no_line(self):
        assert relationship_summary_line(None) == ""
        assert relationship_summary_line(ControlPathRecord()) == ""


# ── §7: the dialog's first state is the preflight ───────────────────────────


# ── call sites: the buttons invoke the EXISTING implementation ──────────────


class TestClientContract:
    def test_the_client_calls_the_agreed_routes(self, monkeypatch):
        from ventulus.api.client import DaemonClient

        client = DaemonClient.__new__(DaemonClient)
        calls: list[tuple[str, str, object]] = []

        def fake_get(path, **kw):
            calls.append(("GET", path, None))
            return _preflight_payload() if "preflight" in path else {"run": None, "records": []}

        def fake_post(path, json=None, **kw):
            calls.append(("POST", path, json))
            return _run_payload()

        def fake_delete(path, **kw):
            calls.append(("DELETE", path, None))
            return _run_payload()

        monkeypatch.setattr(client, "_get", fake_get, raising=False)
        monkeypatch.setattr(client, "_post", fake_post, raising=False)
        monkeypatch.setattr(client, "_delete", fake_delete, raising=False)

        client.diagnostic_preflight("hwmon:a:b:pwm1:X", DIAGNOSTIC_CONTROL_PATH)
        client.start_control_path_discovery("hwmon:a:b:pwm1:X")
        client.control_path_status()
        client.cancel_control_path_discovery()

        methods_paths = [(m, p) for m, p, _ in calls]
        assert methods_paths[1] == (
            "POST",
            "/hwmon/hwmon:a:b:pwm1:X/discover-control-path",
        )
        assert methods_paths[2] == ("GET", "/diagnostics/control-path")
        assert methods_paths[3] == ("DELETE", "/diagnostics/control-path")
        assert methods_paths[0][0] == "GET"
        assert methods_paths[0][1].startswith("/diagnostics/preflight?header=")
        assert f"diagnostic={DIAGNOSTIC_CONTROL_PATH}" in methods_paths[0][1]

    def test_the_start_call_sends_no_client_side_duty(self, monkeypatch):
        """The daemon owns the perturbation, the direction and the floor. A duty
        computed here would be a second copy of a safety rule."""
        from ventulus.api.client import DaemonClient

        client = DaemonClient.__new__(DaemonClient)
        sent: dict = {}

        def fake_post(path, json=None, **kw):
            sent.update({"path": path, "body": json})
            return _run_payload()

        monkeypatch.setattr(client, "_post", fake_post, raising=False)
        client.start_control_path_discovery("h1")
        assert sent["body"] == {}


# ── §7: evidence provenance survives the export round-trip ──────────────────


class TestProvenance:
    def test_fixed_fields_classify_by_definition(self):
        assert classify("requested_pct") == PROVENANCE_COMMANDED
        assert classify("readback_pct") == PROVENANCE_OBSERVED
        assert classify("confidence") == PROVENANCE_DERIVED

    def test_the_pre_run_duty_is_a_reading_not_a_command(self):
        """`PTR-ac`: `original_pct` is a sysfs read of the duty the header held
        before the run. The daemon's `provenance_legend` says OBSERVED, and the
        validation export writes this table into its legend."""
        assert classify("original_pct") == PROVENANCE_OBSERVED

    def test_an_unclassifiable_field_says_so_rather_than_guessing(self):
        assert classify("some_field_nobody_classified") == ""

    def test_a_daemon_envelope_wins_over_the_static_table(self):
        """The GUI must never overrule an observation the daemon actually made —
        that is the "silent promotion" the design principle forbids."""
        rows = classified_rows(
            {
                "requested_pct": 40,
                "rpm": {"value": 1284, "provenance": PROVENANCE_DERIVED},
            }
        )
        by_field = {f: (v, p) for f, v, p in rows}
        assert by_field["requested_pct"] == (40, PROVENANCE_COMMANDED)
        # Table says OBSERVED; the wire said DERIVED, and the wire wins.
        assert by_field["rpm"] == (1284, PROVENANCE_DERIVED)

    def test_a_plain_scalar_is_not_mistaken_for_an_envelope(self):
        assert from_envelope(1284) is None
        assert from_envelope({"value": 1}) is None
        assert from_envelope({"value": 1, "provenance": "OBSERVED"}) is not None

    def test_the_export_carries_the_provenance_legend(self):
        doc = json.loads(session_json(ValidationSession(session_id="v1")))
        assert "provenance" in doc
        assert doc["provenance"]["fields"]["requested_pct"] == PROVENANCE_COMMANDED
        assert doc["provenance"]["fields"]["readback_pct"] == PROVENANCE_OBSERVED
        assert set(doc["provenance"]["classifications"]) >= {
            PROVENANCE_COMMANDED,
            PROVENANCE_OBSERVED,
            PROVENANCE_DERIVED,
        }

    def test_the_export_names_what_software_cannot_establish(self):
        """§5: never let an untested item read as a pass — and an omitted row
        reads as a pass to most people."""
        doc = json.loads(session_json(ValidationSession(session_id="v1")))
        listed = {row["property"] for row in doc["provenance"]["unverified"]}
        assert listed == {key for key, _ in UNVERIFIABLE}
        assert "coolant_flow" in listed
        assert "physical_rpm" in listed

    def test_the_export_tags_each_discovery_value_with_its_provenance(self):
        """§3's worked example: field / value / provenance, attached to the values
        the entry really carries — not just a legend the reader must cross-apply.

        This is also what gives `classified_rows` (and through it `from_envelope`
        and `classify`) a PRODUCTION call site. A classifier exercised only by its
        own unit tests is decoration that looks covered — the DEC-301 trap.
        """
        session = ValidationSession(
            session_id="v1",
            evidence=[
                ValidationEvidence(
                    kind=VALIDATION_DIAG_CONTROL_PATH,
                    control_path=parse_control_path_run(_run_payload()),
                )
            ],
        )
        doc = json.loads(session_json(session))
        rows = {r["field"]: r["provenance"] for r in doc["evidence"][0]["provenance_rows"]}
        assert rows["relationship"] == PROVENANCE_DERIVED
        assert rows["confidence"] == PROVENANCE_DERIVED
        assert rows["measurement_resolution_ms"] == PROVENANCE_DERIVED
        # An unclassifiable field is omitted, not tagged UNKNOWN.
        assert "candidates" not in rows

    def test_an_evidence_entry_with_no_run_carries_no_provenance_rows(self):
        """The opposite branch — without it, code that always emitted the key
        would pass the test above."""
        session = ValidationSession(
            session_id="v1",
            evidence=[ValidationEvidence(kind="pwm_verify")],
        )
        doc = json.loads(session_json(session))
        assert "provenance_rows" not in doc["evidence"][0]

    def test_a_discovery_run_survives_the_export_round_trip(self):
        """§7: "evidence provenance survives API/export round-trip"."""
        session = ValidationSession(
            session_id="v1",
            evidence=[
                ValidationEvidence(
                    kind=VALIDATION_DIAG_CONTROL_PATH,
                    member_id=_downgraded_pump().id,
                    outcome="observed",
                    control_path=parse_control_path_run(_run_payload()),
                )
            ],
        )
        doc = json.loads(session_json(session))
        evidence = doc["evidence"][0]
        assert evidence["kind"] == VALIDATION_DIAG_CONTROL_PATH
        run = evidence["control_path"]
        # Verbatim: every verdict is the daemon's, recomputed nowhere.
        assert run["summary"]["relationship"] == CONTROL_PATH_CONFIRMED
        assert run["summary"]["confidence"] == CONFIDENCE_HIGH
        assert run["summary"]["measurement_resolution_ms"] == 1000
        assert run["summary"]["candidates"][0]["change_pct"] == 31.4


# ── the session dialog offers discovery only where the daemon has it ────────


# ── helpers ─────────────────────────────────────────────────────────────────


def _slug(header_id: str) -> str:
    from ventulus.ui.widgets.pwm_header_card import _slug as real_slug

    return real_slug(header_id)


def _expand_details(card) -> None:
    """Open a header card's "Details" disclosure.

    Clicks the section's own header button rather than reaching into private
    state, so the test exercises the same path a user does.
    """
    section = card.findChild(object, f"HeaderCard_Details_{_slug(card.header_id())}")
    assert section is not None
    button = card.findChild(QPushButton, f"HeaderCard_Details_{_slug(card.header_id())}_Header")
    assert button is not None
    if not button.isChecked():
        button.click()
