"""DEC-500 — GIGABYTE board-catalogue names, wire → model → names → safety → page.

The daemon names a fan header, monitor-only fan or temperature its driver left
unlabelled, from frankcrawford/it87's Gigabyte config for the board's SIV. By
the user's decision the name *becomes* the header's name: a ``*_PUMP`` or
``CPU`` name reaches ``member_label`` and so the 30 % floor, and the daemon
protects the header from it too. What can go wrong here:

- a catalogue name outranking a driver label, the user's sensors.d or the
  checked in-repo table — the tier order says it never does;
- a stale layout renaming a channel whose driver has since published a label;
- a board temperature named "CPU" becoming a CPU sensor — names are display only;
- the GUI's own pump inference or floor display disagreeing with the daemon's
  (``header_role_classification.json`` pins the classifier; this pins the rest);
- an older daemon, which sends none of it, behaving any differently.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from PySide6.QtWidgets import QLabel, QTableWidget

from ventulus.api.models import (
    BoardInfo,
    BoardLayout,
    BoardLayoutChannel,
    Capabilities,
    ConnectionState,
    FanReading,
    HardwareDiagnosticsResult,
    HwmonHeader,
    SensorReading,
    VoltageRail,
    parse_hardware_diagnostics,
    parse_hwmon_headers,
)
from ventulus.knowledge import hwmon_label_resolver
from ventulus.knowledge.hwmon_label_resolver import (
    LABEL_SOURCE_BOARD_CATALOGUE,
    LABEL_SOURCE_BOARD_TABLE,
    LABEL_SOURCE_DRIVER,
    LABEL_SOURCE_NONE,
    LABEL_SOURCE_SENSORS_CONF,
    clear_libsensors_cache,
    hwmon_header_label_source,
    resolve_hwmon_header_label,
)
from ventulus.knowledge.sensor_knowledge import (
    EC_TEMP_PROBE_NOTE,
    classify_reading,
    sensor_display_name,
)
from ventulus.services.app_state import AppState
from ventulus.services.controls_view import min_pwm_badge, sensor_combo_label
from ventulus.services.diagnostics_service import DiagnosticsService
from ventulus.services.hardware_view import build_board_layout_panel, build_voltage_panel
from ventulus.services.header_inspector_view import (
    NAME_SOURCE_ALIAS,
    build_header_inspector_view,
)
from ventulus.services.overview_view import build_sensor_rows
from ventulus.services.profile_service import (
    CONTROL_ROLE_CPU_PUMP,
    FLOOR_ROLE_BOARD_NAME,
    ControlMember,
    LogicalControl,
    floor_role_header_roles,
    infer_member_role,
    member_minimum_pct,
    role_minimum_pct,
)
from ventulus.services.pump_protection import header_infers_pump, header_is_pump_protected
from ventulus.ui.pages.hardware_page import HardwarePage
from ventulus.ui.widgets.pwm_header_card import PwmHeaderCard

GIGABYTE = "Gigabyte Technology Co., Ltd."
SIV = "A008090A"
DEV1, DEV2 = "it87.2624", "it87.2656"
PUMP_ID = f"hwmon:it87952:{DEV2}:pwm1:pwm1"
CPU_ID = f"hwmon:it8696:{DEV1}:pwm1:pwm1"
OPT_ID = f"hwmon:it8696:{DEV1}:pwm5:pwm5"
TEMP_ID = f"hwmon:it8696:{DEV1}:temp5"
FAN_ID = f"hwmon:it87952:{DEV2}:fan3:fan3"


@pytest.fixture(autouse=True)
def hermetic_libsensors(tmp_path, monkeypatch):
    """No host /etc/sensors.d may answer a tier (register row BRD-p)."""
    monkeypatch.setattr(
        hwmon_label_resolver, "LIBSENSORS_CONFIG_PATHS", [str(tmp_path / "absent.conf")]
    )
    clear_libsensors_cache()
    yield
    clear_libsensors_cache()


def _caps() -> Capabilities:
    caps = Capabilities()
    caps.control.header_roles = True
    caps.control.cpu_fan_role_floor = True
    return caps


def _header(hid: str, idx: int, chip: str, *, board_label: str = "", **kw) -> HwmonHeader:
    return HwmonHeader(
        id=hid,
        label=kw.pop("label", f"pwm{idx}"),
        chip_name=chip,
        pwm_index=idx,
        is_writable=True,
        board_label=board_label,
        **kw,
    )


def _layout(channels: list[BoardLayoutChannel], **kw) -> BoardLayout:
    return BoardLayout(
        siv=kw.pop("siv", SIV),
        platform="AMD",
        in_catalogue=kw.pop("in_catalogue", True),
        catalogue_commit="bd7a566c8a60fe0308d67e26761e16260368191a",
        listed_boards=kw.pop("listed_boards", ["X870E AORUS MASTER", "X870E AORUS PRO"]),
        board_listed=kw.pop("board_listed", True),
        channels=channels,
    )


# ── Wire → model ─────────────────────────────────────────────────────────────


def test_the_header_board_label_is_parsed_and_absent_on_an_older_daemon():
    headers = parse_hwmon_headers(
        {
            "headers": [
                {"id": PUMP_ID, "label": "pwm1", "pwm_index": 1, "board_label": "SYS_FAN5_PUMP"},
                {"id": CPU_ID, "label": "pwm1", "pwm_index": 1},
            ]
        }
    )
    assert [h.board_label for h in headers] == ["SYS_FAN5_PUMP", ""]


def test_board_layout_parses_and_drops_malformed_channels():
    result = parse_hardware_diagnostics(
        {
            "board_layout": {
                "siv": SIV,
                "platform": "AMD",
                "in_catalogue": True,
                "catalogue_commit": "bd7a566",
                "listed_boards": ["X870E AORUS MASTER"],
                "board_listed": True,
                "channels": [
                    {"id": TEMP_ID, "kind": "temp", "board_label": "VRM MOS"},
                    {"id": f"hwmon:it8696:{DEV1}:pwm6:pwm6", "kind": "pwm", "board_unmapped": True},
                    # Both, neither, no id, not an object: never shown.
                    {"id": "x", "kind": "temp", "board_label": "A", "board_unmapped": True},
                    {"id": "y", "kind": "temp"},
                    {"kind": "temp", "board_label": "Z"},
                    "garbage",
                ],
            }
        }
    )
    layout = result.board_layout
    assert layout is not None
    assert (layout.siv, layout.platform, layout.in_catalogue, layout.board_listed) == (
        SIV,
        "AMD",
        True,
        True,
    )
    assert [(c.id, c.board_label, c.board_unmapped) for c in layout.channels] == [
        (TEMP_ID, "VRM MOS", False),
        (f"hwmon:it8696:{DEV1}:pwm6:pwm6", "", True),
    ]


def test_an_older_daemon_has_no_layout():
    assert parse_hardware_diagnostics({}).board_layout is None
    assert parse_hardware_diagnostics({"board_layout": "nope"}).board_layout is None


# ── The name ladder ──────────────────────────────────────────────────────────


def _resolve(board_label: str, *, sysfs_label="pwm1", board_name="", sensors_paths=None):
    kw = dict(
        sysfs_label=sysfs_label,
        chip_name="it87952",
        sysfs_chip_name="it87952_a008090a",
        pwm_index=1,
        board_label=board_label,
        board_vendor=GIGABYTE,
        board_name=board_name,
        sensors_paths=sensors_paths,
    )
    return resolve_hwmon_header_label(**kw), hwmon_header_label_source(**kw)


def test_the_catalogue_names_an_unlabelled_header():
    assert _resolve("SYS_FAN5_PUMP") == ("SYS_FAN5_PUMP", LABEL_SOURCE_BOARD_CATALOGUE)
    # Without it, the raw channel, exactly as before.
    assert _resolve("") == ("pwm1", LABEL_SOURCE_NONE)


def test_every_other_tier_outranks_the_catalogue(tmp_path):
    # The driver's own label.
    assert _resolve("SYS_FAN5_PUMP", sysfs_label="CHA_FAN9") == ("CHA_FAN9", LABEL_SOURCE_DRIVER)
    # The user's sensors.d, matched on the sysfs spelling.
    cfg = tmp_path / "board.conf"
    cfg.write_text('chip "it87952_a008090a-*"\n    label fan1 "MY_PUMP"\n')
    assert _resolve("SYS_FAN5_PUMP", sensors_paths=[str(cfg)]) == (
        "MY_PUMP",
        LABEL_SOURCE_SENSORS_CONF,
    )
    # The checked in-repo table: same name here, but the source is the table.
    assert _resolve("OTHER", board_name="X870E AORUS MASTER") == (
        "SYS_FAN5_PUMP",
        LABEL_SOURCE_BOARD_TABLE,
    )


def _state_with(headers, layout=None) -> AppState:
    state = AppState()
    state.board_info = BoardInfo(vendor=GIGABYTE, name="X870 AORUS ELITE WIFI7")
    state.set_hwmon_headers(headers)
    state.set_board_layout(layout)
    return state


def test_the_catalogue_name_becomes_member_label_and_earns_the_floor():
    """[SAFETY] The user's "Become the name": the production route from the wire
    to the floor role — ``fan_fallback_name`` → ``infer_member_role``. The
    chassis row is the opposite branch, so a classifier stuck on cpu_or_pump
    cannot pass."""
    headers = [
        _header(PUMP_ID, 1, "it87952", board_label="SYS_FAN5_PUMP"),
        _header(OPT_ID, 5, "it8696", board_label="CPU_OPT"),
        _header(f"hwmon:it87952:{DEV2}:pwm3:pwm3", 3, "it87952", board_label="SYS_FAN4"),
    ]
    state = _state_with(headers)
    roles = {}
    for h in headers:
        name = state.fan_fallback_name(h.id)
        assert name == h.board_label, "precondition: the catalogue answered"
        roles[h.board_label] = infer_member_role(
            ControlMember(source="hwmon", member_id=h.id, member_label=name)
        )
    assert roles == {
        "SYS_FAN5_PUMP": CONTROL_ROLE_CPU_PUMP,
        "CPU_OPT": CONTROL_ROLE_CPU_PUMP,
        "SYS_FAN4": "chassis",
    }


def test_a_stale_profile_label_still_shows_the_floor_the_daemon_enforces():
    """[SAFETY] A member saved as ``pwm5`` before the catalogue named its header
    ``CPU_OPT``: no role covers it, and the daemon floors it on the name
    (``board_label_earns_hard_floor``). The display must show that floor."""
    opt = _header(OPT_ID, 5, "it8696", board_label="CPU_OPT")
    fan = _header(f"hwmon:it8696:{DEV1}:pwm2:pwm2", 2, "it8696", board_label="SYS_FAN1")
    floor_roles = floor_role_header_roles([opt, fan], _caps(), [])
    assert floor_roles == {OPT_ID: FLOOR_ROLE_BOARD_NAME}
    member = ControlMember(source="hwmon", member_id=OPT_ID, member_label="pwm5")
    control = LogicalControl(members=[member], minimum_pct=0.0)
    assert member_minimum_pct(control, member, floor_roles) == role_minimum_pct(
        CONTROL_ROLE_CPU_PUMP
    )
    badge = min_pwm_badge(control, floor_roles)
    assert badge.floor_pct == role_minimum_pct(CONTROL_ROLE_CPU_PUMP)
    assert "board names" in badge.tooltip and "assigned" not in badge.tooltip
    # The opposite branch: a chassis name floors nothing.
    plain = ControlMember(source="hwmon", member_id=fan.id, member_label="pwm2")
    assert member_minimum_pct(
        LogicalControl(members=[plain], minimum_pct=0.0), plain, floor_roles
    ) == role_minimum_pct("chassis")


def test_a_role_the_catalogue_inferred_is_not_worded_as_assigned():
    """The daemon infers ``pump`` from ``SYS_FAN5_PUMP``; nobody assigned it. The
    floor is the same 30% as an assigned pump's, but the badge must say why."""
    inferred = _header(
        PUMP_ID,
        1,
        "it87952",
        board_label="SYS_FAN5_PUMP",
        role="pump",
        role_source="board_catalogue",
    )
    assigned = _header(CPU_ID, 1, "it8696", role="pump", role_source="user_assigned")
    floor_roles = floor_role_header_roles([inferred, assigned], _caps(), [])
    assert floor_roles == {PUMP_ID: FLOOR_ROLE_BOARD_NAME, CPU_ID: "pump"}

    def badge(header_id):
        member = ControlMember(source="hwmon", member_id=header_id, member_label="pwm1")
        return min_pwm_badge(LogicalControl(members=[member], minimum_pct=0.0), floor_roles)

    pump_floor = role_minimum_pct(CONTROL_ROLE_CPU_PUMP)
    by_board, by_user = badge(PUMP_ID), badge(CPU_ID)
    assert by_board.floor_pct == by_user.floor_pct == pump_floor
    assert "board names" in by_board.tooltip and "assigned" not in by_board.tooltip
    assert "assigned the pump role" in by_user.tooltip


# ── Temperatures ─────────────────────────────────────────────────────────────


def _sensor(sid: str, label: str, chip="it8696", kind="mb_temp") -> SensorReading:
    return SensorReading(id=sid, kind=kind, label=label, value_c=41.0, chip_name=chip)


def test_a_temperature_takes_its_board_name_only_while_unlabelled():
    names = {TEMP_ID: "VRM MOS"}
    assert sensor_display_name(TEMP_ID, "temp5", peers=[], board_names=names) == "VRM MOS"
    # A driver label that appeared since the layout was read wins.
    assert sensor_display_name(TEMP_ID, "SYSTIN", peers=[], board_names=names) == "SYSTIN"
    # No layout: exactly as before.
    assert sensor_display_name(TEMP_ID, "temp5", peers=[], board_names={}) == "temp5"


def test_a_board_cpu_name_never_makes_a_cpu_sensor():
    """[SAFETY] The catalogue calls it8696 temp3 "CPU". Every surface classifies
    through ``AppState.classify_sensor``, from the raw label, so the layout
    changes the name and nothing else; the curve picker never stars it as a CPU
    binding."""
    sid = f"hwmon:it8696:{DEV1}:temp3"
    sensor = _sensor(sid, "temp3")
    state = _state_with([])
    before = state.classify_sensor(sensor)
    state.set_board_layout(_layout([BoardLayoutChannel(id=sid, kind="temp", board_label="CPU")]))
    names = state.board_channel_names
    assert sensor_display_name(sid, sensor.label, peers=[sid], board_names=names) == "CPU"
    assert state.classify_sensor(sensor) == before
    # Not vacuous: the name, were it classified, would give another answer.
    assert classify_reading(replace(sensor, label="CPU"), board_vendor=GIGABYTE, overrides={}) != (
        before
    )
    combo = sensor_combo_label(sensor, {}, peers=[sid], board_names=names)
    assert combo.startswith("CPU (")
    # The opposite branch: the daemon's own CPU sensor is starred.
    cpu = replace(sensor, kind="cpu_temp")
    assert sensor_combo_label(cpu, {}, peers=[sid], board_names=names).startswith("★ ")


def test_an_ec_temp_row_says_it_reads_a_probe():
    sid = f"hwmon:it8696:{DEV1}:temp6"
    rows = build_sensor_rows(
        [_sensor(sid, "temp6"), _sensor(TEMP_ID, "temp5")],
        classify=lambda s: classify_reading(s, board_vendor=GIGABYTE, overrides={}),
        board_names={sid: "EC_TEMP1", TEMP_ID: "VRM MOS"},
    )
    by_label = {r.label.lstrip("⚠? "): r for r in rows}
    assert EC_TEMP_PROBE_NOTE in by_label["EC_TEMP1"].tooltip
    assert EC_TEMP_PROBE_NOTE not in by_label["VRM MOS"].tooltip


def test_the_layout_follows_the_latest_diagnostics():
    state = AppState()
    diag = DiagnosticsService(state)
    layout = _layout([BoardLayoutChannel(id=TEMP_ID, kind="temp", board_label="VRM MOS")])
    diag.set_hw_diagnostics(HardwareDiagnosticsResult(board_layout=layout))
    assert state.board_layout is layout
    assert state.board_channel_names == {TEMP_ID: "VRM MOS"}
    # A read without one (a driver reload withdrew the SIV) clears it.
    diag.set_hw_diagnostics(HardwareDiagnosticsResult())
    assert state.board_layout is None and state.board_channel_names == {}


# ── Pump protection (the GUI's reconstruction) ───────────────────────────────


def test_the_gui_infers_a_catalogue_pump_as_the_daemon_does():
    """[SAFETY] Both branches, the daemon's precedence included."""
    caps = _caps()
    assert header_infers_pump(_header(PUMP_ID, 1, "it87952", board_label="SYS_FAN5_PUMP"), caps)
    assert not header_infers_pump(_header(PUMP_ID, 1, "it87952", board_label="SYS_FAN4"), caps)
    # A real driver label is the evidence, recognised or not.
    assert not header_infers_pump(
        _header(PUMP_ID, 1, "it87952", label="CHA_FAN1", board_label="SYS_FAN5_PUMP"), caps
    )
    # And the daemon's own answer wins whenever it gives one.
    stoppable = _header(PUMP_ID, 1, "it87952", board_label="SYS_FAN5_PUMP", stop_permitted=True)
    assert not header_is_pump_protected(stoppable, caps)
    protected = _header(PUMP_ID, 1, "it87952", stop_permitted=False)
    assert header_is_pump_protected(protected, caps)


def test_an_older_daemon_is_judged_exactly_as_before():
    """No ``board_label`` and no ``stop_permitted``: the reconstruction and the
    name are what they were before DEC-500."""
    old = _header(PUMP_ID, 1, "it87952")
    assert not header_is_pump_protected(old, _caps())
    state = _state_with([old])
    assert state.fan_fallback_name(PUMP_ID) == "pwm1"
    assert floor_role_header_roles([old], _caps(), []) == {}


# ── Header inspector and card ────────────────────────────────────────────────


def _rows(view) -> dict[str, tuple[str, str]]:
    return {r.label: (r.value, r.note) for r in [*view.identity_rows, *view.safety_rows]}


def test_the_inspector_says_where_a_catalogue_name_came_from():
    header = _header(
        PUMP_ID,
        1,
        "it87952",
        board_label="SYS_FAN5_PUMP",
        role="pump",
        role_source="board_catalogue",
        stop_permitted=False,
    )
    view = build_header_inspector_view(
        header,
        reading=FanReading(id=PUMP_ID, source="hwmon"),
        capabilities=_caps(),
        display_name="SYS_FAN5_PUMP",
        name_source=LABEL_SOURCE_BOARD_CATALOGUE,
        board_siv=SIV,
        board_listed=False,
    )
    rows = _rows(view)
    assert rows["Board header"][0] == "SYS_FAN5_PUMP"
    assert SIV in rows["Board header"][1] and "not verified" in rows["Board header"][1]
    assert "does not list this board" in rows["Board header"][1]
    assert rows["Name source"][0] == "it87 board catalogue"
    assert rows["Header type"][0] == "Fan or pump header"
    assert "never stopped" in rows["Header type"][1]
    assert rows["Connected device"][0] == "Not known"
    assert view.role_source_label == "Board catalogue"
    assert view.pump_protected
    assert view.name_provenance == rows["Board header"][1]


def test_an_assigned_role_says_what_is_connected_and_a_user_name_carries_no_provenance():
    header = _header(
        PUMP_ID,
        1,
        "it87952",
        board_label="SYS_FAN5_PUMP",
        role="chassis_fan",
        role_source="user_assigned",
        stop_permitted=False,
    )
    view = build_header_inspector_view(
        header,
        capabilities=_caps(),
        display_name="Bottom intake",
        name_source=NAME_SOURCE_ALIAS,
        board_siv=SIV,
    )
    rows = _rows(view)
    assert rows["Connected device"][0] == "Chassis fan"
    assert rows["Name source"][0] == "Your name"
    # The union still protects it (DEC-312): the user's role is display only.
    assert view.pump_protected
    assert view.name_provenance == ""


def test_a_header_with_no_catalogue_name_gains_no_rows():
    view = build_header_inspector_view(
        _header(CPU_ID, 1, "it8696", label="CPU_FAN"),
        capabilities=_caps(),
        display_name="CPU_FAN",
        name_source=LABEL_SOURCE_DRIVER,
    )
    rows = _rows(view)
    assert not {"Board header", "Header type", "Connected device"} & rows.keys()
    assert rows["Name source"][0] == "Driver label"


def test_the_card_shows_the_provenance_only_for_a_catalogue_name(qtbot):
    header = _header(PUMP_ID, 1, "it87952", board_label="SYS_FAN5_PUMP")
    view = build_header_inspector_view(
        header,
        capabilities=_caps(),
        display_name="SYS_FAN5_PUMP",
        name_source=LABEL_SOURCE_BOARD_CATALOGUE,
        board_siv=SIV,
    )
    card = PwmHeaderCard(view)
    qtbot.addWidget(card)
    card.show()
    labels = [
        w
        for w in card.findChildren(QLabel)
        if w.objectName().startswith("HeaderCard_Label_provenance_")
    ]
    assert len(labels) == 1
    assert labels[0].isVisibleTo(card) and labels[0].text() == view.name_provenance
    named_by_user = build_header_inspector_view(
        header, capabilities=_caps(), display_name="Mine", name_source=NAME_SOURCE_ALIAS
    )
    card.set_view(named_by_user)
    assert not labels[0].isVisibleTo(card)


def test_the_hardware_page_says_a_catalogue_name_is_unverified(qtbot):
    """The page, not the view builder: the name source and the layout reach the
    card through ``HardwarePage`` (``header_name_source``, ``board_layout``), and
    a name the user gave carries no provenance."""
    state = _state_with(
        [_header(PUMP_ID, 1, "it87952", board_label="SYS_FAN5_PUMP")],
        _layout(
            [BoardLayoutChannel(id=PUMP_ID, kind="pwm", board_label="SYS_FAN5_PUMP")],
            board_listed=False,
        ),
    )
    state.set_connection(ConnectionState.CONNECTED)
    state.set_capabilities(_caps())
    state.set_fans([FanReading(id=PUMP_ID, source="hwmon")])
    page = HardwarePage(state=state, diagnostics_service=DiagnosticsService(state), client=None)
    qtbot.addWidget(page)
    page.show()
    page._refresh_cooling_section()
    card = page._header_cards[PUMP_ID]
    (label,) = [
        w
        for w in card.findChildren(QLabel)
        if w.objectName().startswith("HeaderCard_Label_provenance_")
    ]
    assert label.isVisibleTo(card)
    assert SIV in label.text() and "not verified" in label.text()
    assert "does not list this board" in label.text()

    state.fan_aliases[PUMP_ID] = "Loop pump"
    page._refresh_cooling_section()
    assert page._header_cards[PUMP_ID] is card
    assert not label.isVisibleTo(card)


# ── Board layout panel ───────────────────────────────────────────────────────


def test_the_panel_lists_names_coverage_and_the_listing():
    layout = _layout(
        [
            BoardLayoutChannel(id=TEMP_ID, kind="temp", board_label="VRM MOS"),
            BoardLayoutChannel(
                id=f"hwmon:it8696:{DEV1}:temp6", kind="temp", board_label="EC_TEMP1"
            ),
            BoardLayoutChannel(id=FAN_ID, kind="fan", board_label="SYS_FAN4"),
            BoardLayoutChannel(id=CPU_ID, kind="pwm", board_label="CPU_FAN"),
            BoardLayoutChannel(
                id=f"hwmon:it8696:{DEV1}:pwm6:pwm6", kind="pwm", board_unmapped=True
            ),
        ]
    )
    panel = build_board_layout_panel(layout, board_name="X870E AORUS MASTER")
    assert panel.has_layout and SIV in panel.title_text
    assert "is one of the boards listed" in panel.listing_text
    assert panel.coverage_text == (
        "Names 1 fan header, 1 monitor-only fan, 2 temperatures · 1 not mapped."
    )
    assert "bd7a566" in panel.source_text
    assert [(r.name, r.channel, r.kind_text) for r in panel.rows] == [
        ("CPU_FAN", "it8696 pwm1", "Fan header"),
        ("Not mapped for this board", "it8696 pwm6", "Fan header"),
        ("SYS_FAN4", "it87952 fan3", "Fan (monitor only)"),
        ("VRM MOS", "it8696 temp5", "Temperature"),
        ("EC_TEMP1", "it8696 temp6", "Temperature"),
    ]
    assert [r.note == EC_TEMP_PROBE_NOTE for r in panel.rows] == [False] * 4 + [True]


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        (dict(board_listed=False), "is not one of the boards listed"),
        (dict(listed_boards=[], board_listed=False), "does not name the boards"),
        (dict(in_catalogue=False, listed_boards=[]), "not in the board catalogue yet"),
    ],
)
def test_the_listing_sentence_says_what_is_known(kw, expected):
    panel = build_board_layout_panel(_layout([], **kw), board_name="B650 AORUS ELITE")
    assert expected in panel.listing_text


def test_no_layout_hides_the_panel(qtbot):
    assert not build_board_layout_panel(None, board_name="X").has_layout
    state = AppState()
    state.set_connection(ConnectionState.CONNECTED)
    diag = DiagnosticsService(state)
    page = HardwarePage(state=state, diagnostics_service=diag, client=None)
    qtbot.addWidget(page)
    page.show()
    diag.set_hw_diagnostics(
        HardwareDiagnosticsResult(
            board=BoardInfo(vendor=GIGABYTE, name="X870E AORUS MASTER"),
            board_layout=_layout(
                [BoardLayoutChannel(id=TEMP_ID, kind="temp", board_label="VRM MOS")]
            ),
        )
    )
    card = page._board_layout_card
    assert card.isVisibleTo(page)
    table = page.findChild(QTableWidget, "Hardware_Table_boardLayout")
    assert table is not None and table.item(0, 0).text() == "VRM MOS"
    diag.set_hw_diagnostics(HardwareDiagnosticsResult())
    assert not card.isVisibleTo(page)


# ── Voltage plausibility ─────────────────────────────────────────────────────


def test_a_named_supply_rail_far_from_nominal_says_so():
    def rail(pin: float, name="+12V", mult=6.0) -> VoltageRail:
        return VoltageRail(
            id="r",
            chip_name="it8696",
            channel=2,
            label="in2",
            value_v=pin,
            board_label=name,
            board_multiplier=mult,
        )

    def row(r):
        return build_voltage_panel([r], read_at=None, now=0.0, refresh_error="").rows[0]

    good, bad = row(rail(2.02)), row(rail(2.30))  # 12.12 V, 13.80 V
    assert good.identification_text == "Named by the board catalogue"
    assert "10%" not in good.caveat
    assert bad.identification_text.endswith("out of range") and "12 V" in bad.caveat
    # The reading is still shown, scaled: display only, never hidden.
    assert bad.value_text == "13.800 V"
    # A rail with no nominal voltage in its name is never judged.
    assert row(rail(2.30, name="CPU VCORE SOC", mult=1.0)).identification_text == (
        "Named by the board catalogue"
    )
