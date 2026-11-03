"""A fan's display name, Qt-free, for every client of this package (DEC-227/229/503).

The GUI's ``AppState`` and the ``ventulus-diag`` CLI resolve names through this
one function, so a header reads the same in both. The name matters beyond
display: it is what a profile member's ``member_label`` is built from, which
feeds the CPU/pump floor.

Priority (the user alias sits above this, with the caller that owns the aliases):

1. GPU model name (``amd_gpu:`` / ``intel_gpu:`` / ``nvidia_gpu:``)
2. OpenFan channel label (``openfan:ch00`` -> ``OpenFan CH0``)
3. the hwmon label resolver: the daemon-supplied sysfs label, then
   ``/etc/sensors.d``, then the in-repo board table, then the daemon's board
   catalogue, then raw ``pwmN``. A label the daemon merely synthesised from the
   node id is skipped rather than treated as authoritative (DEC-229)
4. the raw id
"""

from __future__ import annotations

from collections.abc import Iterable

from ventulus.knowledge.hwmon_label_resolver import resolve_hwmon_header_label

OPENFAN_CH_PREFIX = "openfan:ch"


def fallback_fan_name(
    fan_id: str,
    *,
    capabilities: object | None,
    headers: Iterable[object],
    board_vendor: str,
    board_name: str,
) -> str:
    """The best display name for *fan_id*, ignoring any user alias."""
    if fan_id.startswith("amd_gpu:"):
        gpu = getattr(capabilities, "amd_gpu", None)
        if gpu is not None and gpu.present:
            return f"{gpu.display_label} Fan"
        return "D-GPU Fan"
    if fan_id.startswith("intel_gpu:"):
        gpu = getattr(capabilities, "intel_gpu", None)
        if gpu is not None and gpu.present:
            return f"{gpu.display_label} Fan"
        return "Intel D-GPU Fan"
    if fan_id.startswith("nvidia_gpu:"):
        gpu = getattr(capabilities, "nvidia_gpu", None)
        if gpu is not None and gpu.present:
            return f"{gpu.display_label} Fan"
        return "NVIDIA D-GPU Fan"
    # DEC-227: an OpenFan channel has no label source at all — the daemon
    # reports only a channel count, and no hwmon header carries an "openfan:"
    # id — so without this every unnamed channel rendered as its raw daemon id.
    if fan_id.startswith(OPENFAN_CH_PREFIX):
        channel = fan_id[len(OPENFAN_CH_PREFIX) :]
        # isdecimal, not isdigit: isdigit accepts superscripts that int() rejects.
        if channel.isdecimal():
            return f"OpenFan CH{int(channel)}"
    for h in headers:
        if getattr(h, "id", None) == fan_id:
            # DEC-229: the resolver owns the hwmon tiers, including whether the
            # daemon's label is real or a synthesised "pwmN" placeholder.
            return resolve_hwmon_header_label(
                sysfs_label=h.label,
                chip_name=h.chip_name,
                sysfs_chip_name=h.sysfs_chip_name,
                pwm_index=h.pwm_index,
                board_label=h.board_label,
                board_vendor=board_vendor,
                board_name=board_name,
            )
    return fan_id
