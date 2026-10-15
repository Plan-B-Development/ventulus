"""Regression fixtures for the 2026-10-15 board-list review (curator `BLD-nn`).

Each class pins one correction to the in-app guidance, asserted on what the user
sees through the production entry points (`lookup_vendor_quirks`,
`lookup_chip_guidance`, `dual_chip_warning_html`) rather than on the table
literals, so a correction that lands in a table no surface reads still fails.
"""

from __future__ import annotations

import re

from ventulus.ui.hwmon_guidance import (
    VENDOR_QUIRKS_DB,
    dual_chip_warning_html,
    lookup_chip_guidance,
    lookup_vendor_quirks,
)

GIGABYTE = "Gigabyte Technology Co., Ltd."
ASROCK = "ASRock"

_WINDOW = "2026-09-09 to 2026-10-01"


def _text(quirks) -> str:
    return "\n".join(d for q in quirks for d in q.details)


class TestIntel800SeriesBuildWindow:
    """`BLD-01` (it87 #139, #138): on Intel Z890/B860 boards, it87 builds from
    2026-09-09 to 2026-10-01 fail to load or bind nothing — a driver bug, not
    the AM5 bridge latch — so the guidance must send the user to a rebuild
    before the latch recovery, and must not offer `mmio=on` as the fix."""

    def _intel_quirks(self, board: str):
        return lookup_vendor_quirks(GIGABYTE, "it8696", cpu_vendor="Intel", board_name=board)

    def test_z890_quirk_names_the_window_before_the_dual_chip_remediation(self):
        quirks = self._intel_quirks("Z890 AORUS MASTER")
        intel = next(q for q in quirks if q.id == "gb-it8696-intel-dual-it87952e")
        text = "\n".join(intel.details)
        assert _WINDOW in text and "PR #140" in text
        assert text.index(_WINDOW) < text.index("same dual-chip remediation")
        # The window's fallback is mmio=OFF; mmio=on is named only as a thing
        # not to set (it is the default), never as an instruction.
        assert "options it87 mmio=off" in text
        assert "set `options it87 mmio=on`" not in text
        assert "Do not set mmio=on" in text

    def test_every_it8696_quirk_on_an_intel_board_mentions_the_window(self):
        # Both the Intel quirk and the vendor-wide IT8696E quirk fire on a Z890
        # board; the user reads both, so neither may send them straight to the
        # power-cycle ladder.
        quirks = self._intel_quirks("Z890 AORUS MASTER")
        ids = {q.id for q in quirks}
        assert {"gb-it8696-intel-dual-it87952e", "gb-it8696-outcome-varies"} <= ids
        for q in quirks:
            if q.id in {"gb-it8696-intel-dual-it87952e", "gb-it8696-outcome-varies"}:
                assert _WINDOW in "\n".join(q.details), q.id

    def test_the_vendor_wide_quirk_puts_the_window_before_the_latch_recovery(self):
        q = next(
            q
            for q in lookup_vendor_quirks(
                GIGABYTE, "it8696", cpu_vendor="AMD", board_name="X870E AORUS MASTER"
            )
            if q.id == "gb-it8696-outcome-varies"
        )
        text = "\n".join(q.details)
        assert text.index(_WINDOW) < text.index("It is recoverable")

    def test_the_rendered_alert_checks_the_build_before_the_ladder(self):
        html = dual_chip_warning_html("Z890 AORUS MASTER", ["it8696", "it87952"], ["it8696"])
        assert html is not None
        assert _WINDOW in html and "PR #140" in html
        assert html.index(_WINDOW) < html.index("1. Stop whatever is unlocking")


class TestMmioDoesNotClaimEnumeration:
    """`BLD-03`: chips are found over the Super-I/O config ports; #139 found
    both chips with mmio=off. MMIO reaches a secondary's extra headers and its
    control — no quirk may say it fixes enumeration."""

    def test_no_quirk_says_mmio_fixes_enumeration(self):
        mmio_quirks = [q for q in VENDOR_QUIRKS_DB if any("mmio=on" in d for d in q.details)]
        assert mmio_quirks, "precondition: some quirk discusses mmio=on"
        for q in mmio_quirks:
            for d in q.details:
                assert not re.search(r"fix(es)? secondary-chip\s+enumeration", d), q.id

    def test_the_gigabyte_dual_chip_quirks_say_what_mmio_does(self):
        for chip in ("it8686", "it8688"):
            text = _text(lookup_vendor_quirks(GIGABYTE, chip))
            assert "does not decide whether the chip is found" in text, chip


class TestMmioAcpiScope:
    """`BLD-04`: MMIO avoids the ACPI port claim only on the native-MMIO chips;
    IT8686E boards and IT8792E/IT87952E secondaries can still need the
    driver-local parameter (X399 #135/#141, Z890 #139)."""

    def test_the_conflict_quirk_scopes_the_mmio_claim(self):
        q = next(
            q
            for q in lookup_vendor_quirks(GIGABYTE, "it87")
            if q.id == "gb-it87-prefer-driver-local"
        )
        first = q.details[0]
        assert "IT8688E, IT8689E, IT8696E and IT8698E" in first
        assert "IT8686E" in first and "IT87952E" in first
        assert "sidesteps the ACPI I/O port claim on newer ITE chips" not in first


class TestAsrockNct6686:
    """`BLD-02`, `BLD-07`, `BLD-08`, `BLD-15`."""

    def _quirk(self, board: str = "X870E Taichi"):
        quirks = lookup_vendor_quirks(ASROCK, "nct6686", board_name=board)
        return next(q for q in quirks if q.id == "asrock-nct6686-monitoring-works-but")

    def test_the_taichi_note_names_both_pump_headers(self):
        text = "\n".join(self._quirk().details)
        assert "W_PUMP" in text and "AIO_PUMP" in text
        # W_PUMP is the channel nct6687d calls 'CPU Fan'; the user must assign
        # the pump role, because the label only gives it the CPU floor.
        assert "'CPU Fan'" in text and "pump role" in text

    def test_the_asrock_nct6683_list_carries_the_new_boards(self):
        text = "\n".join(self._quirk().details)
        for board in ("TRX40 Creator", "B650E Steel Legend WiFi"):
            assert board in text, board

    def test_steel_legend_is_not_stated_as_a_family_rule(self):
        text = "\n".join(self._quirk().details)
        assert "B850M Steel Legend WiFi has an NCT6796D-S" in text
        notes = lookup_chip_guidance("nct6686").notes
        assert "not the B850M Steel Legend WiFi" in notes

    def test_bios_tips_do_not_contradict_the_read_only_in_kernel_driver(self):
        g = lookup_chip_guidance("nct6686")
        assert any("no BIOS setting will unlock it" in k for k in g.known_issues)
        # Any BIOS tip must be scoped away from the in-kernel driver it would
        # otherwise contradict.
        for tip in g.bios_tips:
            assert "out-of-tree" in tip and "does not apply to the in-kernel" in tip
