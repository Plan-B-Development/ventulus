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

from ventulus.api.models import FanReading, HwmonHeader
from ventulus.services.profile_service import (
    CONTROL_ROLE_CHASSIS,
    CONTROL_ROLE_CPU_PUMP,
    ROLE_MINIMUM_PCT,
    ControlMember,
    ControlMode,
    LogicalControl,
    infer_member_role,
)
from ventulus.ui.pages.controls_page import ControlsPage


def _page(qtbot, app_state, profile_service):
    page = ControlsPage(state=app_state, profile_service=profile_service)
    qtbot.addWidget(page)
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
