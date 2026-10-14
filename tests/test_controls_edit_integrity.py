"""Profile edit integrity on the Controls page (GUI audit 2026-10-14, batch A).

The page edits the service's in-memory :class:`Profile` objects in place, so
every path that leaves, renames, copies or rolls back an edit has to act on that
object, not only on the "Unsaved changes" flag. Each class below pins one path
where clearing the flag alone kept, persisted or ran edits the user had thrown
away, or where a read silently rewrote what the profile drives:

- a sidebar switch's **Discard** re-reads the profile, so **Apply** cannot run it;
- an activation from elsewhere discards the left profile's edits, keeps the
  shown one's, and an Apply that saved them clears the chip;
- New / Duplicate ask before leaving edits; Rename is a Save and says so;
- the role dialog's Discard undoes "Edit Members…", which keeps per-member data;
- the curve editor never re-binds a curve's sensor by reading its combo;
- a demo Manual pin does not outlive the card that set it.
"""

from __future__ import annotations

from PySide6.QtWidgets import QInputDialog, QMessageBox, QPushButton

from ventulus.api.models import SensorReading
from ventulus.services.app_state import AppState
from ventulus.services.controls_view import NO_SENSOR_CHOICE
from ventulus.services.demo_controller import DemoController
from ventulus.services.demo_service import DemoService
from ventulus.services.profile_service import (
    ControlMember,
    ControlMode,
    CurveConfig,
    CurvePoint,
    CurveType,
    LogicalControl,
    Profile,
    ProfileService,
)
from ventulus.ui.main_window import MainWindow
from ventulus.ui.pages.controls_page import ControlsPage
from ventulus.ui.widgets import member_editor
from ventulus.ui.widgets.curve_edit_dialog import CurveEditDialog
from ventulus.ui.widgets.curve_editor import CurveEditor
from ventulus.ui.widgets.fan_role_dialog import FanRoleDialog
from ventulus.ui.widgets.member_editor import MemberEditorDialog

EDIT = "Discard me"


def _stored(profile_id: str) -> Profile | None:
    """What is on disk for *profile_id*: a fresh service reading the same store
    (the ``profile_service`` fixture points XDG_CONFIG_HOME at tmp_path)."""
    svc = ProfileService()
    svc.load()
    return svc.get_profile(profile_id)


def _has_edit(profile: Profile | None) -> bool:
    return profile is not None and any(c.name == EDIT for c in profile.controls)


def _sensor(sid: str, *, eligible: bool = True, value_c: float = 45.0) -> SensorReading:
    return SensorReading(
        id=sid,
        kind="cpu_temp",
        label=sid.split(":")[-1],
        value_c=value_c,
        source="hwmon",
        age_ms=100,
        chip_name="k10temp",
        control_eligible=eligible,
    )


def _window(qtbot, app_state, profile_service, settings_service) -> MainWindow:
    win = MainWindow(
        state=app_state,
        profile_service=profile_service,
        settings_service=settings_service,
        demo_mode=False,
    )
    qtbot.addWidget(win)
    return win


def _select_sidebar(win: MainWindow, profile_id: str) -> None:
    """Drive the real selector; its ``currentIndexChanged`` switches the page."""
    combo = win.sidebar.profile_combo
    idx = combo.findData(profile_id)
    assert idx >= 0 and idx != combo.currentIndex(), "precondition: the selection moves"
    combo.setCurrentIndex(idx)


def _active_and_other(profile_service):
    active = profile_service.active_profile
    assert active is not None, "precondition: a profile is active"
    other = next((p for p in profile_service.profiles if p.id != active.id), None)
    assert other is not None, "precondition: a second profile exists"
    return active, other


def _edit(page: ControlsPage) -> None:
    """A real edit through the page's own handler: it adds a role, marks unsaved."""
    page._on_new_control(name=EDIT)
    assert page.has_unsaved_changes(), "precondition: the edit is unsaved"


# ── Discard on a profile switch ──────────────────────────────────────────────


class TestDiscardOnSwitch:
    def test_discarded_edits_neither_come_back_nor_run(
        self, qtbot, app_state, profile_service, settings_service, monkeypatch
    ):
        win = _window(qtbot, app_state, profile_service, settings_service)
        page = win.controls_page
        active, other = _active_and_other(profile_service)
        _edit(page)
        assert _has_edit(profile_service.get_profile(active.id)), "precondition: edit in memory"
        monkeypatch.setattr(page, "confirm_discard_unsaved", lambda: True)

        _select_sidebar(win, other.id)
        _select_sidebar(win, active.id)

        assert page.viewed_profile_id == active.id
        assert not _has_edit(profile_service.get_profile(active.id))
        assert not page.has_unsaved_changes()
        # Apply saves before it activates: what it saves must not hold the edit.
        win.sidebar.apply_profile_btn.click()
        assert profile_service.active_id == active.id
        assert not _has_edit(_stored(active.id))

    def test_no_saved_version_keeps_the_edits_and_the_page(
        self, qtbot, app_state, profile_service, settings_service, monkeypatch
    ):
        win = _window(qtbot, app_state, profile_service, settings_service)
        page = win.controls_page
        active, other = _active_and_other(profile_service)
        _edit(page)
        monkeypatch.setattr(page, "confirm_discard_unsaved", lambda: True)
        monkeypatch.setattr(profile_service, "reload_profile", lambda _pid: None)

        _select_sidebar(win, other.id)

        assert page.viewed_profile_id == active.id
        assert page.has_unsaved_changes()
        assert _has_edit(profile_service.get_profile(active.id))
        assert win.sidebar.profile_combo.currentData() == active.id
        assert "not discarded" in page._unsaved_label.text()

    def test_deleting_an_edited_profile_still_moves_the_page(
        self, qtbot, app_state, profile_service, settings_service, monkeypatch
    ):
        """The deleted profile's edits went with it: nothing blocks the move."""
        win = _window(qtbot, app_state, profile_service, settings_service)
        page = win.controls_page
        _active, other = _active_and_other(profile_service)
        _select_sidebar(win, other.id)
        _edit(page)
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)

        page._on_delete_profile()

        assert profile_service.get_profile(other.id) is None, "precondition: deleted"
        assert page.viewed_profile_id and page.viewed_profile_id != other.id
        assert page._get_current_profile() is not None
        assert not page.has_unsaved_changes()


# ── Activations from elsewhere ───────────────────────────────────────────────


class TestActivationFollow:
    def test_activating_another_profile_discards_the_left_ones_edits(
        self, qtbot, app_state, profile_service, settings_service
    ):
        win = _window(qtbot, app_state, profile_service, settings_service)
        page = win.controls_page
        active, other = _active_and_other(profile_service)
        _edit(page)

        profile_service.set_active(other.id)  # the Dashboard, the tray, another client

        assert page.viewed_profile_id == other.id
        assert not page.has_unsaved_changes()
        assert not _has_edit(profile_service.get_profile(active.id))
        assert active.name in page._unsaved_label.text()
        assert "discarded" in page._unsaved_label.text()

    def test_activating_the_profile_on_screen_keeps_its_edits(
        self, qtbot, app_state, profile_service, settings_service
    ):
        win = _window(qtbot, app_state, profile_service, settings_service)
        page = win.controls_page
        _active, other = _active_and_other(profile_service)
        _select_sidebar(win, other.id)
        _edit(page)

        profile_service.set_active(other.id)  # not saved by whoever did this

        assert page.viewed_profile_id == other.id
        assert page.has_unsaved_changes()
        assert _has_edit(profile_service.get_profile(other.id))

    def test_sidebar_apply_saves_the_edits_and_clears_the_chip(
        self, qtbot, app_state, profile_service, settings_service
    ):
        win = _window(qtbot, app_state, profile_service, settings_service)
        page = win.controls_page
        active, _other = _active_and_other(profile_service)
        _edit(page)

        win.sidebar.apply_profile_btn.click()

        assert _has_edit(_stored(active.id)), "precondition: activate saved the edits"
        assert not page.has_unsaved_changes()
        assert not page._revert_btn.isEnabled()

    def test_any_activation_that_saved_clears_the_chip(
        self, qtbot, app_state, profile_service, settings_service
    ):
        """The Dashboard's Apply goes through the same `activate`, which saves."""
        win = _window(qtbot, app_state, profile_service, settings_service)
        page = win.controls_page
        active, _other = _active_and_other(profile_service)
        _edit(page)

        res = profile_service.activate(active.id, client=None)

        assert res.activated, "precondition"
        assert not page.has_unsaved_changes()

    def test_a_failed_activation_that_saved_still_clears_the_chip(
        self, qtbot, app_state, profile_service, settings_service
    ):
        """`activate` saves before it asks the daemon: a refusal after that
        leaves the edits in the store, so they are not unsaved."""
        from unittest.mock import Mock

        from ventulus.api.errors import DaemonError

        win = _window(qtbot, app_state, profile_service, settings_service)
        page = win.controls_page
        active, _other = _active_and_other(profile_service)
        _edit(page)
        client = Mock()
        client.activate_profile.side_effect = DaemonError("refused", message="refused")

        res = profile_service.activate(active.id, client=client)

        assert not res.activated, "precondition: the daemon refused"
        assert _has_edit(_stored(active.id)), "precondition: the save ran"
        assert not page.has_unsaved_changes()

    def test_an_activation_the_page_cannot_follow_keeps_the_selector_on_the_page(
        self, qtbot, app_state, profile_service, settings_service, monkeypatch
    ):
        """No saved version to restore: the page keeps the edits, and the
        sidebar's selector names the profile the page still shows."""
        win = _window(qtbot, app_state, profile_service, settings_service)
        page = win.controls_page
        active, other = _active_and_other(profile_service)
        _edit(page)
        monkeypatch.setattr(profile_service, "reload_profile", lambda _pid: None)

        profile_service.set_active(other.id)

        assert page.viewed_profile_id == active.id
        assert page.has_unsaved_changes()
        assert win.sidebar.profile_combo.currentData() == page.viewed_profile_id

    def test_dashboard_apply_of_another_profile_leaves_the_flag_to_the_follow(
        self, qtbot, app_state, profile_service, settings_service
    ):
        """`note_saved` names a profile; edits on a different one stay flagged."""
        win = _window(qtbot, app_state, profile_service, settings_service)
        page = win.controls_page
        _active, other = _active_and_other(profile_service)
        _select_sidebar(win, other.id)
        _edit(page)

        page.note_saved(profile_service.active_id)

        assert page.has_unsaved_changes()


# ── New / Duplicate / Rename ─────────────────────────────────────────────────


class TestProfileActions:
    def test_new_asks_and_keeping_the_edits_creates_nothing(
        self, qtbot, app_state, profile_service, settings_service, monkeypatch
    ):
        win = _window(qtbot, app_state, profile_service, settings_service)
        page = win.controls_page
        active, _other = _active_and_other(profile_service)
        _edit(page)
        count = len(profile_service.profiles)
        monkeypatch.setattr(page, "confirm_discard_unsaved", lambda: False)

        page._on_new_profile(name="Fresh")

        assert len(profile_service.profiles) == count
        assert page.viewed_profile_id == active.id
        assert page.has_unsaved_changes()

    def test_new_after_discard_leaves_no_edits_behind(
        self, qtbot, app_state, profile_service, settings_service, monkeypatch
    ):
        win = _window(qtbot, app_state, profile_service, settings_service)
        page = win.controls_page
        active, _other = _active_and_other(profile_service)
        _edit(page)
        monkeypatch.setattr(page, "confirm_discard_unsaved", lambda: True)

        page._on_new_profile(name="Fresh")

        viewed = profile_service.get_profile(page.viewed_profile_id)
        assert viewed is not None and viewed.name == "Fresh"
        assert not page.has_unsaved_changes()
        assert not _has_edit(profile_service.get_profile(active.id))

    def test_duplicate_copies_the_saved_version_after_a_discard(
        self, qtbot, app_state, profile_service, settings_service, monkeypatch
    ):
        win = _window(qtbot, app_state, profile_service, settings_service)
        page = win.controls_page
        active, _other = _active_and_other(profile_service)
        _edit(page)
        monkeypatch.setattr(page, "confirm_discard_unsaved", lambda: True)

        page._on_duplicate_profile()

        copy = profile_service.get_profile(page.viewed_profile_id)
        assert copy is not None and copy.id != active.id
        assert copy.name == f"{active.name} (copy)"
        assert not _has_edit(copy)
        assert not _has_edit(profile_service.get_profile(active.id))
        assert not page.has_unsaved_changes()

    def test_duplicate_kept_edits_copies_nothing(
        self, qtbot, app_state, profile_service, settings_service, monkeypatch
    ):
        win = _window(qtbot, app_state, profile_service, settings_service)
        page = win.controls_page
        active, _other = _active_and_other(profile_service)
        _edit(page)
        count = len(profile_service.profiles)
        monkeypatch.setattr(page, "confirm_discard_unsaved", lambda: False)

        page._on_duplicate_profile()

        assert len(profile_service.profiles) == count
        assert page.has_unsaved_changes()
        assert _has_edit(profile_service.get_profile(active.id))

    def test_rename_with_edits_cancelled_changes_nothing(
        self, qtbot, app_state, profile_service, settings_service, monkeypatch
    ):
        win = _window(qtbot, app_state, profile_service, settings_service)
        page = win.controls_page
        active, _other = _active_and_other(profile_service)
        old_name = active.name
        _edit(page)
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Renamed", True))
        monkeypatch.setattr(page, "confirm_rename_saves", lambda: False)

        page._on_rename_profile()

        assert profile_service.get_profile(active.id).name == old_name
        assert page.has_unsaved_changes()
        assert not _has_edit(_stored(active.id))

    def test_rename_with_edits_is_a_save(
        self, qtbot, app_state, profile_service, settings_service, monkeypatch
    ):
        """The rename saves the edits too, so the chip must not say they are unsaved."""
        win = _window(qtbot, app_state, profile_service, settings_service)
        page = win.controls_page
        active, _other = _active_and_other(profile_service)
        _edit(page)
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Renamed", True))
        monkeypatch.setattr(page, "confirm_rename_saves", lambda: True)

        page._on_rename_profile()

        stored = _stored(active.id)
        assert stored is not None and stored.name == "Renamed"
        assert _has_edit(stored)
        assert not page.has_unsaved_changes()
        assert page._unsaved_label.text() == "Renamed"

    def test_rename_without_edits_does_not_ask(
        self, qtbot, app_state, profile_service, settings_service, monkeypatch
    ):
        win = _window(qtbot, app_state, profile_service, settings_service)
        page = win.controls_page
        active, _other = _active_and_other(profile_service)
        asked: list[bool] = []
        monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Renamed", True))
        monkeypatch.setattr(page, "confirm_rename_saves", lambda: asked.append(True) or True)

        page._on_rename_profile()

        assert asked == []
        assert _stored(active.id).name == "Renamed"


# ── Edit Members inside the role dialog ──────────────────────────────────────


def _gpu_member(**kw) -> ControlMember:
    return ControlMember(
        source="amd_gpu",
        member_id="amd_gpu:0000:03:00.0",
        member_label="RX 7900",
        fan_zero_rpm=kw.get("fan_zero_rpm", True),
        extra_fields=kw.get("extra_fields", {"future_key": 7}),
    )


class TestMemberEdits:
    def test_an_untouched_member_comes_back_whole(self, qtbot):
        kept = _gpu_member()
        dlg = MemberEditorDialog([kept], [], role_name="GPU")
        qtbot.addWidget(dlg)

        (member,) = dlg.get_members()

        assert member == kept, "zero-RPM and unmodelled keys must survive"
        assert member is not kept, "a copy: the dialog never aliases the profile's member"

    def test_discarding_the_role_dialog_undoes_an_edit_members(
        self, qtbot, app_state, profile_service, monkeypatch
    ):
        page = ControlsPage(state=app_state, profile_service=profile_service)
        qtbot.addWidget(page)
        control = LogicalControl(
            id="lc1",
            name="Chassis",
            mode=ControlMode.MANUAL,
            members=[ControlMember(source="openfan", member_id="openfan:ch00", member_label="F")],
        )
        profile = profile_service.create_profile("Roles")
        profile.controls.append(control)
        page.select_profile(profile.id)
        before_members = list(control.members)
        before_min = control.minimum_pct
        assert not page.has_unsaved_changes(), "precondition"

        # "Edit Members…" adds a pump: its role floor raises minimum_pct (DEC-095).
        pump = ControlMember(source="hwmon", member_id="hwmon:nct:pwm2", member_label="AIO Pump")

        class _Editor:
            def __init__(self, *a, **k):
                pass

            def exec(self):
                return 1

            def get_members(self):
                return [*before_members, pump]

        monkeypatch.setattr(member_editor, "MemberEditorDialog", _Editor)
        seen: dict = {}

        def _edit_members_then_discard(dlg):
            dlg.findChild(QPushButton, "FanRoleDialog_Btn_editMembers").click()
            seen["members"] = list(control.members)
            seen["min"] = control.minimum_pct
            return 0  # Discard

        monkeypatch.setattr(FanRoleDialog, "exec", _edit_members_then_discard)

        page._on_edit_role("lc1")

        assert pump in seen["members"] and seen["min"] > before_min, (
            "precondition: Edit Members changed the control while the dialog was open"
        )
        assert control.members == before_members
        assert control.minimum_pct == before_min
        assert not page.has_unsaved_changes()

    def test_discarding_after_an_unchanged_edit_members_leaves_no_chip(
        self, qtbot, app_state, profile_service, monkeypatch
    ):
        """Accepting the member editor marks unsaved even with nothing changed;
        Discard must still put the flag back."""
        page = ControlsPage(state=app_state, profile_service=profile_service)
        qtbot.addWidget(page)
        member = ControlMember(source="openfan", member_id="openfan:ch00", member_label="F")
        control = LogicalControl(id="lc1", name="Chassis", members=[member])
        profile = profile_service.create_profile("Roles")
        profile.controls.append(control)
        page.select_profile(profile.id)
        assert not page.has_unsaved_changes(), "precondition"

        class _Editor:
            def __init__(self, *a, **k):
                pass

            def exec(self):
                return 1

            def get_members(self):
                return [ControlMember(source="openfan", member_id="openfan:ch00", member_label="F")]

        monkeypatch.setattr(member_editor, "MemberEditorDialog", _Editor)
        seen: dict = {}

        def _edit_members_then_discard(dlg):
            dlg.findChild(QPushButton, "FanRoleDialog_Btn_editMembers").click()
            seen["unsaved"] = page.has_unsaved_changes()
            return 0

        monkeypatch.setattr(FanRoleDialog, "exec", _edit_members_then_discard)

        page._on_edit_role("lc1")

        assert seen["unsaved"], "precondition: the member editor marked the page unsaved"
        assert not page.has_unsaved_changes()

    def test_the_gpu_section_appears_when_a_gpu_member_is_added(self, qtbot):
        """A role with no GPU member grows the zero-RPM section in place."""
        from PySide6.QtWidgets import QApplication

        control = LogicalControl(
            id="lc1",
            name="Mixed",
            members=[ControlMember(source="openfan", member_id="openfan:ch00", member_label="F")],
        )
        dlg = FanRoleDialog(control, [])
        qtbot.addWidget(dlg)
        dlg.show()
        assert dlg._gpu_section is None, "precondition: no GPU member yet"
        gpu = _gpu_member(fan_zero_rpm=True)

        def _callback(_control_id):
            control.members = [*control.members, gpu]

        dlg.set_edit_members_callback(_callback)
        dlg.findChild(QPushButton, "FanRoleDialog_Btn_editMembers").click()
        QApplication.processEvents()

        assert dlg._gpu_section is not None and dlg._gpu_section.isVisibleTo(dlg)
        assert dlg._member_grid.isVisibleTo(dlg)
        assert dlg.get_result()["gpu_fan_zero_rpm"] == {gpu.member_id: True}

    def test_saving_the_role_dialog_keeps_the_member_edit(
        self, qtbot, app_state, profile_service, monkeypatch
    ):
        page = ControlsPage(state=app_state, profile_service=profile_service)
        qtbot.addWidget(page)
        control = LogicalControl(id="lc1", name="Chassis", mode=ControlMode.MANUAL)
        profile = profile_service.create_profile("Roles")
        profile.controls.append(control)
        page.select_profile(profile.id)
        added = ControlMember(source="openfan", member_id="openfan:ch01", member_label="F2")

        class _Editor:
            def __init__(self, *a, **k):
                pass

            def exec(self):
                return 1

            def get_members(self):
                return [added]

        monkeypatch.setattr(member_editor, "MemberEditorDialog", _Editor)

        def _edit_members_then_save(dlg):
            dlg.findChild(QPushButton, "FanRoleDialog_Btn_editMembers").click()
            return 1

        monkeypatch.setattr(FanRoleDialog, "exec", _edit_members_then_save)

        page._on_edit_role("lc1")

        assert control.members == [added]
        assert page.has_unsaved_changes()

    def test_the_role_dialog_shows_the_edited_members(self, qtbot):
        gpu = _gpu_member(fan_zero_rpm=False)
        control = LogicalControl(id="lc1", name="GPU", members=[gpu])
        dlg = FanRoleDialog(control, [])
        qtbot.addWidget(dlg)
        # The user ticks zero-RPM, then edits members: the tick must survive.
        dlg._gpu_zero_rpm_checks[gpu.member_id].setChecked(True)
        second = ControlMember(source="openfan", member_id="openfan:ch02", member_label="Rear")

        def _callback(_control_id):
            control.members = [gpu, second]

        dlg.set_edit_members_callback(_callback)

        dlg.findChild(QPushButton, "FanRoleDialog_Btn_editMembers").click()

        assert dlg._members_title.text() == "Role Members (2)"
        assert dlg._member_grid.findChild(object, "FanRoleDialog_Chip_member_openfan:ch02")
        assert dlg.get_result()["gpu_fan_zero_rpm"] == {gpu.member_id: True}


# ── The curve's sensor ───────────────────────────────────────────────────────

GONE = "hwmon:gone:temp9"


def _graph(sensor_id: str) -> CurveConfig:
    return CurveConfig(
        id="g1",
        name="G",
        type=CurveType.GRAPH,
        sensor_id=sensor_id,
        points=[CurvePoint(30.0, 25.0), CurvePoint(70.0, 90.0)],
    )


class TestCurveSensorBinding:
    def test_reading_the_editor_never_rebinds_the_curve(self, qtbot):
        editor = CurveEditor()
        qtbot.addWidget(editor)
        editor.set_available_sensors([("hwmon:a:temp1", "A"), ("hwmon:b:temp1", "B")])
        curve = _graph(GONE)

        editor.set_curve(curve)

        assert editor.get_curve().sensor_id == GONE
        assert editor._sensor_combo.currentData() == GONE
        assert "unavailable" in editor._sensor_combo.currentText()

    def test_the_sensor_tick_leaves_an_unlisted_binding_alone(
        self, qtbot, app_state, profile_service
    ):
        page = ControlsPage(state=app_state, profile_service=profile_service)
        qtbot.addWidget(page)
        page.show()
        profile = profile_service.create_profile("Curves")
        curve = _graph(GONE)
        profile.curves.append(curve)
        page.select_profile(profile.id)
        page._on_edit_curve(curve.id)
        assert page._curve_editor.get_curve() is curve, "precondition: the curve is open"

        app_state.set_sensors([_sensor("hwmon:a:temp1"), _sensor("hwmon:b:temp1")])
        app_state.set_sensors([_sensor("hwmon:b:temp1")])  # a vanishes: list rebuilt

        assert curve.sensor_id == GONE
        assert not page.has_unsaved_changes()
        assert page._curve_editor._sensor_combo.currentData() == GONE

    def test_reading_the_editor_keeps_a_sensor_changed_elsewhere(self, qtbot):
        """`get_curve` is a read. The DEC-492 memory-id re-key rewrites an open
        curve's ``sensor_id`` from outside the editor; a read that copied the
        combo back would undo it on the next tick."""
        editor = CurveEditor()
        qtbot.addWidget(editor)
        editor.set_available_sensors([("hwmon:a:temp1", "A"), ("hwmon:b:temp1", "B")])
        curve = _graph("hwmon:a:temp1")
        editor.set_curve(curve)

        curve.sensor_id = "hwmon:b:temp1"  # re-keyed while the editor is open

        assert editor.get_curve().sensor_id == "hwmon:b:temp1"

    def test_a_curve_re_keyed_elsewhere_is_shown_by_its_new_id(
        self, qtbot, app_state, profile_service
    ):
        page = ControlsPage(state=app_state, profile_service=profile_service)
        qtbot.addWidget(page)
        page.show()
        sensors = [_sensor("hwmon:a:temp1"), _sensor("hwmon:b:temp1")]
        app_state.set_sensors(sensors)
        profile = profile_service.create_profile("Curves")
        curve = _graph("hwmon:a:temp1")
        profile.curves.append(curve)
        page.select_profile(profile.id)
        page._on_edit_curve(curve.id)
        assert page._curve_editor._sensor_combo.currentData() == "hwmon:a:temp1"

        curve.sensor_id = "hwmon:b:temp1"  # the DEC-492 re-key, same sensor set
        app_state.set_sensors(sensors)

        assert page._curve_editor._sensor_combo.currentData() == "hwmon:b:temp1"
        assert curve.sensor_id == "hwmon:b:temp1"

    def test_a_curve_with_no_sensor_says_so(self, qtbot):
        editor = CurveEditor()
        qtbot.addWidget(editor)
        editor.set_available_sensors([("hwmon:a:temp1", "A")])
        curve = _graph("")

        editor.set_curve(curve)

        assert editor._sensor_combo.currentText() == NO_SENSOR_CHOICE
        assert editor.get_curve().sensor_id == ""
        # It describes the curve; it is not a choice that would unbind one.
        from PySide6.QtCore import Qt

        flags = editor._sensor_combo.model().item(0).flags()
        assert not flags & Qt.ItemFlag.ItemIsEnabled
        assert editor._sensor_combo.model().item(1).flags() & Qt.ItemFlag.ItemIsEnabled

    def test_a_reported_but_ineligible_sensor_is_not_called_unavailable(self, qtbot):
        editor = CurveEditor()
        qtbot.addWidget(editor)
        editor.set_available_sensors(
            [("hwmon:a:temp1", "A")], {"hwmon:ath12k:temp1": "ath12k temp1"}
        )
        curve = _graph("hwmon:ath12k:temp1")

        editor.set_curve(curve)

        assert editor._sensor_combo.currentData() == "hwmon:ath12k:temp1"
        assert "not offered" in editor._sensor_combo.currentText()
        assert "unavailable" not in editor._sensor_combo.currentText()

    def test_picking_a_sensor_still_binds_it(self, qtbot):
        editor = CurveEditor()
        qtbot.addWidget(editor)
        editor.set_available_sensors([("hwmon:a:temp1", "A"), ("hwmon:b:temp1", "B")])
        curve = _graph(GONE)
        editor.set_curve(curve)

        editor._sensor_combo.setCurrentIndex(editor._sensor_combo.findData("hwmon:b:temp1"))

        assert curve.sensor_id == "hwmon:b:temp1"

    def test_a_new_curve_starts_on_the_first_offered_sensor(
        self, qtbot, app_state, profile_service
    ):
        page = ControlsPage(state=app_state, profile_service=profile_service)
        qtbot.addWidget(page)
        profile = profile_service.create_profile("Curves")
        page.select_profile(profile.id)
        app_state.set_sensors(
            [_sensor("hwmon:ath12k:temp1", eligible=False), _sensor("hwmon:k10temp:temp1")]
        )

        page._on_add_curve(CurveType.GRAPH)
        page._on_add_curve(CurveType.FLAT)

        graph, flat = profile.curves[-2:]
        assert graph.sensor_id == "hwmon:k10temp:temp1"
        assert flat.sensor_id == "", "a Flat curve reads no sensor"

    def test_the_dialog_keeps_an_unlisted_sensor_on_save(self, qtbot):
        curve = CurveConfig(id="l1", name="L", type=CurveType.LINEAR, sensor_id=GONE)
        dlg = CurveEditDialog(curve, [("hwmon:a:temp1", "A"), ("hwmon:b:temp1", "B")])
        qtbot.addWidget(dlg)

        dlg.apply_to_curve()

        assert curve.sensor_id == GONE

    def test_the_dialog_does_not_offer_an_ineligible_sensor(
        self, qtbot, app_state, profile_service, monkeypatch
    ):
        page = ControlsPage(state=app_state, profile_service=profile_service)
        qtbot.addWidget(page)
        profile = profile_service.create_profile("Curves")
        curve = CurveConfig(id="l1", name="L", type=CurveType.LINEAR, sensor_id="hwmon:k:temp1")
        profile.curves.append(curve)
        page.select_profile(profile.id)
        app_state.set_sensors(
            [_sensor("hwmon:ath12k:temp1", eligible=False), _sensor("hwmon:k:temp1")]
        )
        offered: dict = {}

        def _capture(dlg):
            combo = dlg._sensor_combo
            offered["ids"] = [combo.itemData(i) for i in range(combo.count())]
            return 0

        monkeypatch.setattr(CurveEditDialog, "exec", _capture)

        page._on_edit_curve(curve.id)

        assert offered["ids"] == ["hwmon:k:temp1"]


class TestSyncTarget:
    def test_a_sync_curve_with_no_target_is_not_accepted(self, qtbot, monkeypatch):
        warned: list = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a))
        curve = CurveConfig(id="s1", name="S", type=CurveType.SYNC, sync_control_id="")
        dlg = CurveEditDialog(curve, sync_candidates=[("lc1", "Chassis")])
        qtbot.addWidget(dlg)
        assert dlg._sync_control_combo.currentData() == "", "precondition: no target"

        dlg.findChild(QPushButton, "CurveEditDialog_Btn_save").click()

        assert dlg.result() != CurveEditDialog.DialogCode.Accepted
        assert len(warned) == 1

    def test_a_sync_curve_with_a_target_is_accepted(self, qtbot, monkeypatch):
        warned: list = []
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a))
        curve = CurveConfig(id="s1", name="S", type=CurveType.SYNC, sync_control_id="lc1")
        dlg = CurveEditDialog(curve, sync_candidates=[("lc1", "Chassis")])
        qtbot.addWidget(dlg)

        dlg.findChild(QPushButton, "CurveEditDialog_Btn_save").click()

        assert dlg.result() == CurveEditDialog.DialogCode.Accepted
        assert warned == []


# ── Demo Manual pins ─────────────────────────────────────────────────────────


class TestDemoPins:
    def test_a_rebuild_releases_the_demo_pin(self, qtbot):
        curve = CurveConfig(id="c", type=CurveType.FLAT, flat_output_pct=70.0)
        ctrl = LogicalControl(
            id="lc",
            curve_id="c",
            members=[ControlMember(source="openfan", member_id="openfan:ch00")],
        )
        state = AppState()
        demo = DemoService()
        profiles = ProfileService()
        profiles._profiles["p"] = Profile(id="p", name="P", controls=[ctrl], curves=[curve])
        profiles.set_active("p")
        controller = DemoController(profiles, demo, state)
        page = ControlsPage(state=state, profile_service=profiles)
        qtbot.addWidget(page)
        page.set_demo_controller(controller)
        page._refresh_all()

        page._control_cards["lc"].manual_toggled.emit("lc", True, 25)
        assert demo._fan_pwm["openfan:ch00"] == 25, "precondition: the pin drives the fan"

        page._refresh_all()  # e.g. a save: the card comes back without Manual

        assert demo._fan_pwm["openfan:ch00"] == 70
        assert controller._manual == {}
