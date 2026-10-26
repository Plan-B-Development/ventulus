"""DEC-500 Phase 2 — driver readiness: what the kernel and the board layout say.

The daemon now reports whether the kernel refuses unsigned modules
(``kernel_security``) and which chips the board's GIGABYTE layout expects
(``board_layout.expected_chips``); IT8689E support follows the running kernel.
What can go wrong here:

- the layout's chips raising a second missing-chip warning beside the board
  table's, or a different list reaching the warning, its fan-loss wording, the
  verify hint and the acknowledgement fingerprint;
- the kernel's own it87, which cannot drive the missing chip, being sent round
  the latch ladder instead of told its DKMS build was not rebuilt;
- a signing cause shown where nothing refuses an unsigned driver, or where the
  out-of-tree driver is already running;
- an IT8689E on 7.1 told it needs the out-of-tree driver, or one on 7.0 told it
  does not;
- an older daemon, which sends none of it, behaving any differently.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from ventulus.api.models import (
    BoardInfo,
    BoardLayout,
    ConnectionState,
    FanReading,
    HardwareDiagnosticsResult,
    HwmonChipInfo,
    HwmonDiagnostics,
    HwmonHeader,
    HwmonVerifyResult,
    KernelModuleInfo,
    KernelSecurityInfo,
    parse_hardware_diagnostics,
)
from ventulus.services import health_ack
from ventulus.services.app_state import AppState
from ventulus.services.controls_view import build_member_candidates
from ventulus.services.demo_service import DemoService
from ventulus.services.diagnostics_service import DiagnosticsService
from ventulus.services.duty_drift import NO_DRIFT
from ventulus.services.hardware_view import build_board_layout_panel
from ventulus.services.system_state_view import condition_fingerprint
from ventulus.services.verify_view import build_verify_result_view
from ventulus.ui.hwmon_guidance import (
    IT87_IN_TREE,
    IT87_NOT_LOADED,
    IT87_OUT_OF_TREE,
    IT87_UNKNOWN,
    chip_in_mainline,
    expected_board_chips,
    format_driver_status,
    it87_state,
    kernel_version,
)
from ventulus.ui.pages.hardware_page import HardwarePage
from ventulus.ui.pages.overview_page import OverviewPage
from ventulus.ui.widgets.readiness_report import (
    build_readiness_report_html,
    chip_rows,
    detect_readiness_problems,
    dual_chip_warning_for,
    module_signing_line,
)

GIGABYTE = "Gigabyte Technology Co., Ltd."
SIV = "A008090A"


def _it87(loaded: bool, out_of_tree: bool | None = None) -> KernelModuleInfo:
    return KernelModuleInfo(name="it87", loaded=loaded, out_of_tree=out_of_tree)


def _diag(
    *,
    board_name: str = "X870E AORUS MASTER",
    table: list[str] | None = None,
    layout_chips: list[str] | None = None,
    detected: list[str] = ("it8696",),
    it87: KernelModuleInfo | None = None,
    kernel: str | None = "7.2.10-1-cachyos",
    signed_only: bool | None = None,
) -> HardwareDiagnosticsResult:
    """A Gigabyte board. ``table`` is the curated top-level ``expected_chips``;
    ``layout_chips`` the board layout's; ``detected`` the bound chips."""
    return HardwareDiagnosticsResult(
        board=BoardInfo(vendor=GIGABYTE, name=board_name),
        hwmon=HwmonDiagnostics(
            chips_detected=[
                HwmonChipInfo(chip_name=c, expected_driver="it87", header_count=1) for c in detected
            ],
            total_headers=len(detected),
            writable_headers=len(detected),
        ),
        kernel_modules=[it87 if it87 is not None else _it87(True, True)],
        kernel_release=kernel,
        expected_chips=list(table or []),
        board_layout=(
            BoardLayout(siv=SIV, platform="AMD", in_catalogue=True, expected_chips=layout_chips)
            if layout_chips is not None
            else None
        ),
        kernel_security=(
            KernelSecurityInfo(signed_modules_only=signed_only) if signed_only is not None else None
        ),
    )


def _dual_chip_conditions(diag) -> list[dict]:
    return [
        p for p in detect_readiness_problems(diag, duty_drift=NO_DRIFT) if p["key"] == "dual_chip"
    ]


# ── Wire ─────────────────────────────────────────────────────────────────────


def test_kernel_security_and_expected_chips_parse_and_are_absent_on_an_older_daemon():
    diag = parse_hardware_diagnostics(
        {
            "kernel_security": {
                "secure_boot": True,
                "lockdown": "integrity",
                "module_sig_enforce": False,
                "signed_modules_only": True,
            },
            "board_layout": {"siv": SIV, "expected_chips": ["it8696", "", "it87952"]},
        }
    )
    assert diag.kernel_security == KernelSecurityInfo(
        secure_boot=True, lockdown="integrity", module_sig_enforce=False, signed_modules_only=True
    )
    assert diag.board_layout.expected_chips == ["it8696", "it87952"]

    older = parse_hardware_diagnostics({"board_layout": {"siv": SIV}})
    assert older.kernel_security is None
    assert older.board_layout.expected_chips == []


def test_a_malformed_fact_reads_as_unknown_never_as_a_verdict():
    diag = parse_hardware_diagnostics(
        {
            "kernel_security": {
                "secure_boot": "true",
                "lockdown": 3,
                "module_sig_enforce": 1,
                "signed_modules_only": "false",
            },
            "board_layout": {"siv": SIV, "expected_chips": "it8696"},
        }
    )
    assert diag.kernel_security == KernelSecurityInfo()
    assert diag.board_layout.expected_chips == []
    assert parse_hardware_diagnostics({"kernel_security": []}).kernel_security is None


# ── IT8689E follows the running kernel ───────────────────────────────────────


def test_kernel_version_reads_major_and_minor():
    assert kernel_version("7.2.10-1-cachyos") == (7, 2)
    assert kernel_version("6.12.48+deb13-amd64") == (6, 12)
    assert kernel_version("7") is None
    assert kernel_version("") is None
    assert kernel_version(None) is None


@pytest.mark.parametrize(
    ("release", "mainline"),
    [("7.1.0", True), ("7.3.2-arch1-1", True), ("7.0.12-generic", False), ("6.12.48", False)],
)
def test_an_it8689_is_mainline_from_7_1(release, mainline):
    assert chip_in_mainline("it8689", release) is mainline
    want = "try: sudo modprobe it87" if mainline else "install"
    assert want in format_driver_status("it8689", False, release)


def test_an_unknown_kernel_keeps_the_out_of_tree_answer_and_other_chips_never_move():
    assert chip_in_mainline("it8689", None) is False
    for release in (None, "6.12.0", "7.1.0", "9.9.9"):
        assert chip_in_mainline("it8696", release) is False
        assert chip_in_mainline("it87952", release) is True


def test_the_chip_row_status_agrees_with_its_mainline_column():
    """Contract review: the row's status takes the daemon's per-chip answer
    (``in_mainline_kernel``), the one its Mainline column shows, so the two
    cannot disagree — an older daemon on 7.1 keeps both "out-of-tree"."""

    def row(daemon_says: bool):
        diag = _diag(detected=["it8689"], it87=_it87(True, False), kernel="7.1.4")
        diag.hwmon.chips_detected[0].in_mainline_kernel = daemon_says
        (r,) = chip_rows(diag)
        return r.status, r.mainline

    assert row(True) == ("it87 loaded (mainline kernel)", "Yes")
    status, mainline = row(False)
    assert status.startswith("it87 loaded (out-of-tree") and mainline == "No (out-of-tree)"


def test_driver_tooltips_follow_the_kernel_the_daemon_runs_on(qtbot):
    """Contract review: the Overview row and the Controls member picker name the
    driver for the running kernel, from ``AppState.kernel_release``, which the
    diagnostics read sets and a read without it does not clear."""
    header = HwmonHeader(
        id="hwmon:it8689:it87.2624:pwm2:pwm2", chip_name="it8689", is_writable=True
    )
    fan = FanReading(id=header.id, source="hwmon", rpm=900, age_ms=50)

    state = AppState()
    diag = DiagnosticsService(state)
    diag.set_hw_diagnostics(HardwareDiagnosticsResult(kernel_release="7.1.4"))
    assert state.kernel_release == "7.1.4"
    diag.set_hw_diagnostics(HardwareDiagnosticsResult())
    assert state.kernel_release == "7.1.4"

    state.set_hwmon_headers([header])
    page = OverviewPage(state=state)
    qtbot.addWidget(page)
    state.set_fans([fan])
    assert page._fan_table.rowCount() == 1
    assert "Driver: it87 (mainline)" in page._fan_table.item(0, 1).toolTip()

    def picker_tip(kernel: str | None) -> str:
        # A header with no fan reading is the row that carries the driver line.
        (row,) = build_member_candidates(
            [],
            [header],
            capabilities=None,
            display_name=lambda x: x,
            fallback_name=lambda x: x,
            kernel_release=kernel,
        )
        return row["tooltip"]

    assert "Driver: it87 (mainline)" in picker_tip("7.1.4")
    assert "Driver: it87 (frankcrawford/it87)" in picker_tip("7.0.9")
    assert "Driver: it87 (frankcrawford/it87)" in picker_tip(None)


# ── One list of expected chips ───────────────────────────────────────────────


def test_the_board_table_wins_and_the_layout_fills_in_where_it_has_nothing():
    both = _diag(table=["it8696", "it87952"], layout_chips=["it8696"])
    assert expected_board_chips(both).chips == ["it8696", "it87952"]
    assert expected_board_chips(both).layout_siv == ""

    fanless = replace(_diag(table=["it8686", "it8792"]), expected_fanless_chips=["it8792"])
    assert expected_board_chips(fanless).fanless == ["it8792"]

    layout_only = _diag(layout_chips=["it8696", "it87952"])
    expected = expected_board_chips(layout_only)
    assert (expected.chips, expected.fanless, expected.layout_siv) == (
        ["it8696", "it87952"],
        [],
        SIV,
    )

    assert expected_board_chips(_diag()).chips == []
    assert expected_board_chips(_diag(layout_chips=[])).chips == []


def test_a_layout_missing_chip_raises_the_one_warning_and_says_where_it_came_from():
    """A board the table does not list: the layout's chips reach the warning,
    once, and the copy says they come from the layout, not a per-board list."""
    unlisted = _diag(board_name="X870E AORUS PRO ICE X", layout_chips=["it8696", "it87952"])
    html = dual_chip_warning_for(unlisted)
    assert html is not None
    assert "IT87952E" in html and SIV in html and "board catalogue" in html
    assert len(_dual_chip_conditions(unlisted)) == 1

    # Presence first, then absence: no layout, no warning on the same board.
    assert dual_chip_warning_for(replace(unlisted, board_layout=None)) is None
    assert _dual_chip_conditions(replace(unlisted, board_layout=None)) == []

    # Listed by the table too: one warning, and it does not claim the layout.
    listed = _diag(table=["it8696", "it87952"], layout_chips=["it8696", "it87952"])
    assert len(_dual_chip_conditions(listed)) == 1
    assert "board catalogue" not in dual_chip_warning_for(listed)


def test_every_consumer_reads_the_layout_list_the_warning_reads():
    """The verify hint and the acknowledgement fingerprint name the same missing
    chip the warning does — a dismissal made against the warning holds."""
    diag = _diag(layout_chips=["it8696", "it87952"])
    view = build_verify_result_view(
        HwmonVerifyResult(header_id="h", result="no_rpm_effect"), diagnostics=diag
    )
    assert any("2 ITE chips but only 1" in line for line in view.lines), view.lines
    assert condition_fingerprint(diag, "dual_chip") == health_ack.fingerprint({"it87952"})
    # With nothing expected there is nothing to fingerprint.
    assert condition_fingerprint(_diag(), "dual_chip") == health_ack.fingerprint(set())


# ── The kernel's own it87 ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("module", "state"),
    [
        (_it87(False), IT87_NOT_LOADED),
        (_it87(True, False), IT87_IN_TREE),
        (_it87(True, True), IT87_OUT_OF_TREE),
        (_it87(True, None), IT87_UNKNOWN),
    ],
)
def test_it87_state_reads_the_taint_the_daemon_published(module, state):
    assert it87_state([KernelModuleInfo(name="nct6775", loaded=True), module]) == state


def test_the_kernels_own_it87_is_told_its_dkms_build_was_not_rebuilt():
    """X870E on the kernel's own it87: the IT87952E bound, the IT8696E it cannot
    drive missing. The cause is the missed rebuild, not a latched bridge."""
    in_tree = _diag(table=["it8696", "it87952"], detected=["it87952"], it87=_it87(True, False))
    html = dual_chip_warning_for(in_tree)
    assert "loaded is the kernel's own, and it cannot drive <b>IT8696E</b>" in html
    assert "<code>dkms status</code>" in html and "<code>sudo dkms autoinstall</code>" in html
    assert "once the out-of-tree driver is loaded" in html
    assert "First, is the driver loaded?" not in html
    (cond,) = _dual_chip_conditions(in_tree)
    assert "kernel's own" in cond["fix"] and "dkms autoinstall" in cond["fix"]

    out_of_tree = replace(in_tree, kernel_modules=[_it87(True, True)])
    html = dual_chip_warning_for(out_of_tree)
    assert "kernel's own" not in html and "First, is the driver loaded?" in html
    (cond,) = _dual_chip_conditions(out_of_tree)
    assert "kernel's own" not in cond["fix"] and "power down fully at the wall" in cond["fix"]


def test_a_chip_the_kernels_own_it87_drives_is_not_blamed_on_a_rebuild():
    """An IT8689E missing under the kernel's own it87: on 7.1 that driver drives
    it, so the latch ladder stands; on 7.0 it does not, so the rebuild cause."""

    def html(kernel: str) -> str:
        return dual_chip_warning_for(
            _diag(
                board_name="Z790 AORUS ELITE AX",
                table=["it8689"],
                detected=[],
                it87=_it87(True, False),
                kernel=kernel,
            )
        )

    assert "kernel's own" not in html("7.1.2")
    assert "cannot drive <b>IT8689E</b>" in html("7.0.11")


# ── A kernel that refuses unsigned drivers ───────────────────────────────────


@pytest.mark.parametrize(
    ("signed_only", "it87", "shown"),
    [
        (True, _it87(False), True),
        (True, _it87(True, False), True),
        (True, _it87(True, True), False),
        (False, _it87(False), False),
        (None, _it87(False), False),
    ],
)
def test_the_signing_cause_is_shown_only_where_it_can_be_the_cause(signed_only, it87, shown):
    diag = _diag(
        table=["it8696", "it87952"], detected=["it87952"], it87=it87, signed_only=signed_only
    )
    html = dual_chip_warning_for(diag)
    assert ("only loads signed drivers" in html) is shown
    assert ("Key was rejected by service" in html) is shown
    assert ("shim boot loader" in html) is shown
    (cond,) = _dual_chip_conditions(diag)
    assert ("only loads signed drivers" in cond["fix"]) is shown
    assert ("shim boot loader" in cond["fix"]) is shown


def test_no_signing_cause_where_the_kernels_own_driver_drives_the_missing_chip():
    """Contract review: an IT8689E missing on 7.1 needs no out-of-tree build, so
    a kernel that refuses unsigned modules is not its cause — the daemon's note
    stays silent there too. On 7.0 it needs one, and the cause is shown."""

    def html(kernel: str) -> str:
        return dual_chip_warning_for(
            _diag(
                board_name="Z790 AORUS ELITE AX",
                table=["it8689"],
                detected=[],
                it87=_it87(False),
                kernel=kernel,
                signed_only=True,
            )
        )

    assert "only loads signed drivers" in html("7.0.11")
    assert "only loads signed drivers" not in html("7.1.2")


def test_the_report_states_the_signing_facts_and_the_verdict():
    facts = KernelSecurityInfo(
        secure_boot=True, lockdown="none", module_sig_enforce=False, signed_modules_only=False
    )
    diag = replace(_diag(), kernel_security=facts)
    line = module_signing_line(diag)
    assert line == (
        "Secure Boot on · lockdown: none · module.sig_enforce: off. "
        "This kernel loads unsigned drivers."
    )
    refused = replace(diag, kernel_security=replace(facts, signed_modules_only=True))
    assert "only loads signed drivers" in module_signing_line(refused)
    unknown = replace(diag, kernel_security=KernelSecurityInfo())
    assert module_signing_line(unknown) == (
        "Whether this kernel loads unsigned drivers could not be read."
    )

    report = build_readiness_report_html(diag, duty_drift=NO_DRIFT)
    assert "Module signing" in report and "module.sig_enforce: off" in report
    older = build_readiness_report_html(_diag(), duty_drift=NO_DRIFT)
    assert module_signing_line(_diag()) is None and "Module signing" not in older


# ── Board layout panel ───────────────────────────────────────────────────────


def test_the_panel_says_which_expected_chips_were_found():
    layout = BoardLayout(siv=SIV, in_catalogue=True, expected_chips=["it8696", "it87952"])
    panel = build_board_layout_panel(layout, board_name="X", detected_chips=["it8696"])
    assert panel.chips_text.startswith(
        "This layout expects IT8696E (found) and IT87952E (not found)."
    )
    assert "System State page" in panel.chips_text
    found = build_board_layout_panel(layout, board_name="X", detected_chips=["it8696", "it87952"])
    assert found.chips_text == "This layout expects IT8696E (found) and IT87952E (found)."
    assert (
        build_board_layout_panel(replace(layout, expected_chips=[]), board_name="X").chips_text
        == ""
    )


def test_the_hardware_page_shows_the_chips_line(qtbot):
    state = AppState()
    state.set_connection(ConnectionState.CONNECTED)
    diag = DiagnosticsService(state)
    page = HardwarePage(state=state, diagnostics_service=diag, client=None)
    qtbot.addWidget(page)
    page.show()
    diag.set_hw_diagnostics(_diag(layout_chips=["it8696", "it87952"]))
    # A label added under an already-shown parent is shown by a queued call.
    QApplication.processEvents()
    label = page.findChild(QLabel, "Hardware_Label_boardLayoutChips")
    assert label is not None and label.isVisibleTo(page)
    assert "IT87952E (not found)" in label.text()


def test_the_demo_board_reports_both_chips_present_and_no_warning():
    diag = DemoService().hardware_diagnostics()
    assert diag.board_layout.expected_chips == ["it8696", "it87952"]
    assert diag.kernel_security.signed_modules_only is False
    assert dual_chip_warning_for(diag) is None
