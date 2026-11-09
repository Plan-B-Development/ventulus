"""Profile editing integrity (`PRF-a`..`PRF-d`, audit 2026-11-09).

Each case is an edit that silently meant something other than what the user did:
a floor input that depended on which menu added the fan (`PRF-b`), a curve
delete that re-indexed a Mix (`PRF-a`), an editor or a revert that reached the
wrong copy of a profile (`PRF-c`), and a role dialog that offered a curve that
forms a Sync cycle (`PRF-d`).
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from ventulus.api.errors import DaemonError, DaemonUnavailable
from ventulus.api.models import FanReading, HwmonHeader
from ventulus.services.profile_service import (
    CONTROL_ROLE_CHASSIS,
    CONTROL_ROLE_CPU_PUMP,
    ROLE_MINIMUM_PCT,
    ControlMember,
    ControlMode,
    CurveConfig,
    CurvePoint,
    CurveType,
    LogicalControl,
    Profile,
    ProfileService,
    infer_member_role,
    remove_curve,
)
from ventulus.ui.pages.controls_page import ControlsPage


def _page(qtbot, app_state, profile_service):
    page = ControlsPage(state=app_state, profile_service=profile_service)
    qtbot.addWidget(page)
    return page


def _page_on(qtbot, app_state, profile_service, profile: Profile) -> ControlsPage:
    profile_service._profiles[profile.id] = profile
    page = _page(qtbot, app_state, profile_service)
    page.select_profile(profile.id)
    assert page._get_current_profile() is profile
    return page


# ---------------------------------------------------------------------------
# PRF-b — quick-assign and the member picker build the same member
# ---------------------------------------------------------------------------

_AIO_ID = "hwmon:kraken:pwm1"
_MB_PUMP_ID = "hwmon:nct6799:pwm3"
_MB_CHASSIS_ID = "hwmon:nct6799:pwm4"


def _aio_header() -> HwmonHeader:
    # A liquid-cooler channel whose label carries no cpu/pump/aio word: the
    # `(AIO …)` tag is its only role signal.
    return HwmonHeader(
        id=_AIO_ID, label="FAN2", chip_name="kraken", is_writable=True, is_aio=True, pwm_index=1
    )


def _mb_pump_header() -> HwmonHeader:
    # A motherboard header the user assigned the pump role: `is_aio` is False by
    # construction (the chip is the Super-I/O) and the label has no pump word.
    return HwmonHeader(
        id=_MB_PUMP_ID, label="SYS_FAN3", chip_name="nct6799", is_writable=True, pwm_index=3,
        role="pump",
    )  # fmt: skip


def _mb_chassis_header() -> HwmonHeader:
    return HwmonHeader(
        id=_MB_CHASSIS_ID, label="SYS_FAN4", chip_name="nct6799", is_writable=True, pwm_index=4
    )


def _picker_member(page, monkeypatch, member_id: str) -> ControlMember:
    """The member the member picker persists for ``member_id``, through the real
    ``_on_edit_members`` → ``MemberEditorDialog.get_members`` path: the row is
    selected, Add is clicked and the dialog accepted."""
    prof = page._get_current_profile()
    ctrl = LogicalControl(id="picker", name="Picked", mode=ControlMode.CURVE)
    prof.controls.append(ctrl)

    def _pick_and_accept(dlg):
        lst = dlg._available_list
        row = next(
            i for i in range(lst.count())
            if lst.item(i).data(Qt.ItemDataRole.UserRole)["id"] == member_id
        )  # fmt: skip
        lst.item(row).setSelected(True)
        dlg._add_btn.click()
        return True

    monkeypatch.setattr("ventulus.ui.pages.controls_page.exec_dialog", _pick_and_accept)
    # A pump is reserved for the cooling device (DEC-319); the user confirms.
    monkeypatch.setattr(
        "ventulus.ui.widgets.member_editor.QMessageBox.question",
        lambda *a, **k: QMessageBox.StandardButton.Yes,
    )
    page._on_edit_members("picker")
    assert [m.member_id for m in ctrl.members] == [member_id]
    return ctrl.members[0]


class TestQuickAssignMatchesPicker:
    @pytest.mark.parametrize("with_fan_reading", [True, False])
    @pytest.mark.parametrize(
        ("header_factory", "expected_role"),
        [
            (_aio_header, CONTROL_ROLE_CPU_PUMP),
            (_mb_pump_header, CONTROL_ROLE_CPU_PUMP),
            (_mb_chassis_header, CONTROL_ROLE_CHASSIS),
        ],
        ids=["aio", "mb-pump-role", "mb-chassis"],
    )
    def test_both_paths_build_identical_members(
        self,
        qtbot,
        app_state,
        profile_service,
        monkeypatch,
        header_factory,
        expected_role,
        with_fan_reading,
    ):
        header = header_factory()
        app_state.hwmon_headers = [header]
        app_state.fans = (
            [FanReading(id=header.id, source="hwmon", rpm=1500)] if with_fan_reading else []
        )
        page = _page(qtbot, app_state, profile_service)

        quick = page._make_member_for_fan(header.id)
        picked = _picker_member(page, monkeypatch, header.id)

        assert quick == picked
        # Not merely equal: both carry the role the header really has, so a shared
        # regression (both paths dropping the tag) does not pass as agreement.
        assert infer_member_role(quick) == expected_role

    def test_openfan_channel_identical_on_both_paths(
        self, qtbot, app_state, profile_service, monkeypatch
    ):
        app_state.fans = [FanReading(id="openfan:ch00", source="openfan", rpm=900)]
        page = _page(qtbot, app_state, profile_service)

        quick = page._make_member_for_fan("openfan:ch00")
        picked = _picker_member(page, monkeypatch, "openfan:ch00")

        assert quick == picked
        assert infer_member_role(quick) == CONTROL_ROLE_CHASSIS

    def test_quick_assign_pump_role_header_gets_pump_floor(
        self, qtbot, app_state, profile_service, monkeypatch
    ):
        """The PRF-b defect end to end: a pump-role motherboard header added from
        the Unassigned menu must save the CPU/pump floor, not the chassis one."""
        # A pump-role header is reserved as a pump (DEC-319); the user confirms.
        monkeypatch.setattr(
            "ventulus.ui.pages.controls_page.QMessageBox.question",
            lambda *a, **k: QMessageBox.StandardButton.Yes,
        )
        app_state.hwmon_headers = [_mb_pump_header()]
        app_state.fans = [FanReading(id=_MB_PUMP_ID, source="hwmon", rpm=2400)]
        page = _page(qtbot, app_state, profile_service)
        prof = page._get_current_profile()
        ctrl = LogicalControl(id="r1", name="Loop", mode=ControlMode.CURVE, minimum_pct=0.0)
        prof.controls.append(ctrl)
        page._refresh_all()

        member = page._make_member_for_fan(_MB_PUMP_ID)
        page._assign_member_to_control("r1", member)

        assert any(m.member_id == _MB_PUMP_ID for m in ctrl.members)
        assert ctrl.minimum_pct == ROLE_MINIMUM_PCT[CONTROL_ROLE_CPU_PUMP]
        assert ctrl.minimum_pct > ROLE_MINIMUM_PCT[CONTROL_ROLE_CHASSIS]


# ---------------------------------------------------------------------------
# PRF-a — a curve that feeds a Mix is not deleted out from under it
# ---------------------------------------------------------------------------


def _mix_profile(mix_function: str, inputs: list[str]) -> Profile:
    """Graph curves ``a``, ``b``, ``c`` and a Mix ``m`` of ``inputs`` driving a role."""
    p = Profile(id="prf_a", name="PRF-a")
    p.curves = [
        CurveConfig(id="a", name="Package", type=CurveType.GRAPH),
        CurveConfig(id="b", name="Ambient", type=CurveType.GRAPH),
        CurveConfig(id="c", name="Spare", type=CurveType.GRAPH),
        CurveConfig(
            id="m", name="Delta", type=CurveType.MIX, mix_function=mix_function,
            mix_curve_ids=list(inputs),
        ),
    ]  # fmt: skip
    p.controls = [LogicalControl(id="r", name="Case", mode=ControlMode.CURVE, curve_id="m")]
    return p


class TestDeleteMixInput:
    @pytest.fixture()
    def warnings(self, monkeypatch) -> list[tuple[str, str]]:
        shown: list[tuple[str, str]] = []
        monkeypatch.setattr(
            "ventulus.ui.pages.controls_page.QMessageBox.warning",
            lambda _parent, title, text, *a, **k: shown.append((title, text)),
        )
        return shown

    def test_subtract_minuend_is_not_deleted(self, qtbot, app_state, profile_service, warnings):
        # Deleting the minuend would make `b - …` out of `a - b`.
        p = _mix_profile("subtract", ["a", "b"])
        page = _page_on(qtbot, app_state, profile_service, p)

        page._curve_cards["a"].delete_requested.emit("a")

        assert "a" in {c.id for c in p.curves}
        assert next(c for c in p.curves if c.id == "m").mix_curve_ids == ["a", "b"]
        assert len(warnings) == 1
        title, text = warnings[0]
        assert title == "Curve not deleted"
        assert "Delta" in text and "Package" in text
        assert page._has_unsaved is False

    def test_only_input_of_a_mix_is_not_deleted(self, qtbot, app_state, profile_service, warnings):
        # Deleting the only input would leave a Mix that controls nothing.
        p = _mix_profile("max", ["a"])
        page = _page_on(qtbot, app_state, profile_service, p)

        page._curve_cards["a"].delete_requested.emit("a")

        assert "a" in {c.id for c in p.curves}
        assert next(c for c in p.curves if c.id == "m").mix_curve_ids == ["a"]
        assert len(warnings) == 1
        assert page._has_unsaved is False

    def test_curve_no_mix_uses_is_deleted(self, qtbot, app_state, profile_service, warnings):
        # The opposite branch: the refusal is about Mix inputs, not every delete.
        p = _mix_profile("subtract", ["a", "b"])
        page = _page_on(qtbot, app_state, profile_service, p)

        page._curve_cards["c"].delete_requested.emit("c")

        assert "c" not in {c.id for c in p.curves}
        assert next(c for c in p.curves if c.id == "m").mix_curve_ids == ["a", "b"]
        assert warnings == []
        assert page._has_unsaved is True

    def test_helper_refuses_on_its_own(self):
        # The rule lives in `remove_curve`, not only in the page that calls it.
        p = _mix_profile("subtract", ["a", "b"])
        with pytest.raises(ValueError, match="Mix"):
            remove_curve(p, "b")
        assert [c.id for c in p.curves] == ["a", "b", "c", "m"]
        assert next(c for c in p.curves if c.id == "m").mix_curve_ids == ["a", "b"]


# ---------------------------------------------------------------------------
# PRF-c — the editor and Revert reach the profile the user is looking at
# ---------------------------------------------------------------------------


class TestEditorFollowsTheProfile:
    def test_switch_to_a_duplicate_closes_the_editor(self, qtbot, app_state, profile_service):
        """Duplicate Profile keeps curve ids, so the copy has a curve with the id
        open in the editor. The editor must not stay on the SOURCE's curve."""
        source = profile_service.create_profile("Source")
        source.curves.append(
            CurveConfig(
                id="g1", name="CPU", type=CurveType.GRAPH,
                points=[CurvePoint(30, 20), CurvePoint(80, 100)],
            )
        )  # fmt: skip
        page = _page(qtbot, app_state, profile_service)
        page.select_profile(source.id)
        page._on_edit_curve("g1")
        assert page._editing_curve_id == "g1"
        assert page._curve_editor.get_curve() is source.get_curve("g1")
        copy = profile_service.duplicate_profile(source.id, "Copy")
        # Precondition the defect needs: the copy has the same id, another object.
        assert copy.get_curve("g1") is not None
        assert copy.get_curve("g1") is not source.get_curve("g1")

        page.select_profile(copy.id)

        assert page._editing_curve_id is None
        assert page._curve_editor.isHidden()
        assert not page._editor_placeholder.isHidden()

    def test_refresh_of_the_same_profile_keeps_the_editor(self, qtbot, app_state, profile_service):
        # The opposite branch: a rebuild that shows the same curve keeps it open.
        prof = profile_service.create_profile("Only")
        prof.curves.append(CurveConfig(id="g1", name="CPU", type=CurveType.GRAPH))
        page = _page(qtbot, app_state, profile_service)
        page.select_profile(prof.id)
        page._on_edit_curve("g1")

        page._refresh_curves_grid(prof)

        assert page._editing_curve_id == "g1"
        assert page._curve_cards["g1"].is_editing is True
        assert not page._curve_editor.isHidden()


class _DaemonStub:
    """A daemon that holds an older version of the profile and refuses (or
    cannot take) the next upload."""

    def __init__(self, document: dict, upload_error: Exception) -> None:
        self.document = document
        self.upload_error = upload_error
        self.reads: list[str] = []

    def get_profile(self, profile_id: str) -> dict:
        self.reads.append(profile_id)
        return self.document

    def update_profile(self, _profile_id: str, _document: dict) -> dict:
        raise self.upload_error


class TestRevertKeepsALocalSave:
    @pytest.mark.parametrize(
        "upload_error",
        [
            DaemonUnavailable(),
            DaemonError(code="validation_error", message="refused", status=400),
        ],
        ids=["offline", "refused"],
    )
    def test_revert_returns_to_the_local_save(self, tmp_path, monkeypatch, upload_error):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        svc = ProfileService()
        svc.load()
        pid = svc.active_id
        daemon_version = svc.get_profile(pid).to_dict()
        stub = _DaemonStub(daemon_version, upload_error)
        svc._client = stub
        svc._daemon_ids.add(pid)
        assert svc.is_published(pid)  # precondition: the daemon holds it

        prof = svc.get_profile(pid)
        prof.controls.append(LogicalControl(id="saved", name="Saved", mode=ControlMode.MANUAL))
        svc.save_profile(prof)  # stays a local draft
        assert not svc.is_published(pid)
        svc.get_profile(pid).controls.append(
            LogicalControl(id="unsaved", name="Unsaved", mode=ControlMode.MANUAL)
        )

        reloaded = svc.reload_profile(pid)

        assert reloaded is not None
        ids = {c.id for c in reloaded.controls}
        assert "saved" in ids  # the last save, not the daemon's older version
        assert "unsaved" not in ids
        assert stub.reads == []
        # The local mirror was not overwritten with the daemon's version either.
        again = svc.reload_profile(pid)
        assert again is not None and "saved" in {c.id for c in again.controls}
