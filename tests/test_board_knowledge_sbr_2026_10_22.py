"""Regression fixtures for the 2026-10-22 supported-boards review (curator `SBR-nn`).

Asserted on what the user sees through the production entry points
(`lookup_chip_guidance`, `lookup_vendor_quirks`, `classify_sensor`), not on the
table literals, so a correction that lands where no surface reads still fails.
"""

from __future__ import annotations

import re

from ventulus.knowledge.sensor_knowledge import classify_sensor
from ventulus.ui.hwmon_guidance import lookup_chip_guidance, lookup_vendor_quirks

ASUS = "ASUSTeK COMPUTER INC."

# The retracted claim, in each form our text used: a BIOS at WMI method
# version >= 2 fixes / should rectify / is the durable fix.
_RETRACTED = re.compile(
    r"rectify|durable fix|BIOS (with|whose) WMI method version (is )?2", re.IGNORECASE
)


def _wmi_guidance_texts() -> dict[str, str]:
    guidance = lookup_chip_guidance("asus_wmi_sensors")
    assert guidance is not None
    texts = {"chip guidance": "\n".join(guidance.bios_tips + guidance.known_issues)}
    for q in lookup_vendor_quirks(ASUS, "asus_wmi_sensors", board_name="PRIME X470-PRO"):
        texts[q.id] = "\n".join(q.details)
    cls = classify_sensor("asus_wmi_sensors", "CPU Temperature", board_vendor=ASUS)
    texts["sensor notes"] = "\n".join(cls.notes)
    return texts


class TestAsusWmiBiosAdvice:
    """`SBR-01`: `asus_wmi_sensors` refuses to bind when the BIOS reports WMI
    method version < 2 (v7.3 `asus_wmi_sensors.c`), so "a BIOS with method
    version >= 2 should rectify the issue" cannot help anyone the driver runs
    on; the kernel doc queued for 7.4 (`58d7d43e4804`) says only that a more
    recent BIOS "might help"."""

    def test_every_surface_is_reached(self):
        texts = _wmi_guidance_texts()
        # Both ASUS quirks that carry the polling warning fire on this board.
        assert {
            "asus-asuswmi-high-frequency-polling",
            "asus-asuswmisensors-kernel-documented-buggy",
        } <= set(texts)

    def test_no_surface_presents_a_bios_version_as_the_fix(self):
        for where, text in _wmi_guidance_texts().items():
            # Presence first: each surface still tells the user what may help.
            assert "might help" in text, where
            assert not _RETRACTED.search(text), where

    def test_where_method_version_2_is_named_it_is_named_as_not_the_remedy(self):
        texts = _wmi_guidance_texts()
        naming = {w: t for w, t in texts.items() if "method version 2" in t}
        assert naming, "the chip guidance explains why the version is not the fix"
        for where, text in naming.items():
            assert "not the remedy" in text, where
