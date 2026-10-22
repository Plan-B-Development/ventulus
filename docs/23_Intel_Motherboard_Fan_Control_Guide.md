# Intel Motherboard Fan Control Guide

How motherboard fan control works on Intel desktop boards under Linux, vendor by
vendor, for LGA1700 (12th–14th Gen Core) and LGA1851 (Core Ultra). It mirrors the
[AMD guide](21_AMD_Motherboard_Fan_Control_Guide.md). To install a driver, follow the
manual's [Driver Setup](../manual/driver-setup.md). The full chip matrix, with sources,
is the [Hardware Compatibility Guide](19_Hardware_Compatibility.md#intel-platform--typical-chip-mapping);
for a symptom, start at [Hardware Troubleshooting](../manual/hardware-troubleshooting.md).

## The Super-I/O chip decides, not the chipset

As on AMD, fan control on desktop Intel boards is done by the motherboard's Super-I/O
chip or embedded controller (EC), not by the Intel chipset. Chipset names (Z690, Z790,
Z890, B760, H770, …) identify the board's generation, socket and feature tier; they do
**not** decide which Linux driver controls the fans.

So work out fan control in this order:

1. **Board vendor and model** (from DMI: `board_vendor`, `board_name`)
2. **Super-I/O chip and hwmon driver** (`nct6775`, `nct6683`, `it87`, …)
3. **What actually reads and writes** in `/sys/class/hwmon/`
4. **Intel chipset**, as a grouping hint only

Do not expect all "Z790 boards" to behave alike. An ASUS ROG STRIX Z790-E with a
Nuvoton NCT6798D and a Gigabyte Z790 AORUS MASTER with an ITE IT8689E + IT87952E pair
use different drivers and have different quirks.

## Platform overview

The driver column is the fan control path (Super-I/O / EC), not the CPU temperature
path, which is always `coretemp` on Intel.

| Intel Platform | Typical Boards | Common Linux Driver Path | Notes |
|---|---|---|---|
| **LGA1700 600-series** (Z690, B660, H670, H610) | ASUS ROG STRIX / TUF GAMING / PRIME Z690; MSI MAG/MEG/MPG Z690; Gigabyte Z690 AORUS; ASRock Z690 Steel Legend/Extreme | `nct6775` (mainline) on NCT6798D / NCT6796D-E boards; `Fred78290/nct6687d` on MSI Z690 (NCT6687D, default register map: no module parameter; blacklist the read-only in-kernel `nct6683`); `frankcrawford/it87` on Gigabyte IT8689E (+ IT87952E on the PRO / MASTER); `asus_ec_sensors` (mainline) for extra ASUS Z690 sensors | Strong mainline coverage. Z690 has the only LGA1700-era ASRock board with an upstream lm-sensors config (Z690 Extreme). |
| **LGA1700 700-series** (Z790, B760, H770, H610 refresh) | ASUS ROG STRIX Z790-E/-H/-I; MSI MAG Z790 TOMAHAWK / MPG Z790 EDGE WIFI; Gigabyte Z790 AORUS ELITE/MASTER/XTREME; ASRock Z790 Steel Legend/Taichi | Similar to Z690. MSI Z790 ships the NCT6687D with the default map. Gigabyte Z790 AORUS MASTER / XTREME / PRO X are dual-chip (IT8689E + IT87952E); the Z790 AORUS ELITE / ELITE AX has the IT8689E only. ASRock's Z790 Taichi puts five headers on an NCT6686D, read-only in the kernel driver. | The kernel `asus_ec_sensors` list includes ROG STRIX Z790-E GAMING WIFI II, Z790-H and Z790-I GAMING WIFI and ROG MAXIMUS Z790 EXTREME (7.3 adds Z790 HERO). |
| **LGA1851 800-series** (Z890, B860, H810) | MSI MAG/MEG/MPG Z890; ASUS ROG STRIX Z890; Gigabyte Z890 AORUS; ASRock Z890 Taichi/Steel Legend | MSI Z890 ships the NCT6687D with the alternate "msi_alt1" EC map (monitoring tools call it *NCT6687DR*), which **requires `fan_config=msi_alt1`**, set automatically for boards on the upstream list. ASUS Z890 / B860 carry an NCT6701D, bound as `nct6799`. Gigabyte Z890 AORUS MASTER uses IT8696E + IT87952E, as, per the it87 SIV catalogue, do the XTREME AI TOP, PRO ICE, ELITE X ICE, TACHYON ICE and TACHYON DUO X ICE, the Z890 AI TOP, the Z890 AERO D and the W880 AI TOP; the Z890 AORUS ELITE WIFI7 has the IT8696E only. it87 driver builds from 2026-09-09 to 2026-10-01 can fail to load on these Gigabyte boards; rebuild. ASRock Z890 fans sit on an NCT6686D, read-only in the kernel driver; ASRock's B860 Pro RS / Pro-A boards carry a plain NCT6796D for mainline `nct6775`. | The newest platform: treat upstream support as still settling. |

The mainline `coretemp` driver reports CPU temperature on all of these generations
(per-core + `Package id 0`). It is **not** a fan-control driver: it provides the
temperatures the fan curves follow.

Two cautions apply to every Intel board, as to AMD ones:

- **Do not run `sensors-detect` on a Gigabyte board.** It writes the Super-I/O unlock
  key, which on AMD AM5 Gigabyte boards has been measured latching the ITE bridge in
  front of the secondary chip, so the secondary silently fails to enumerate, and the
  latch can survive a reboot. No Intel board has been measured doing this yet, but the
  Gigabyte LGA1700/LGA1851 dual-chip boards put their secondary behind the same kind of
  bridge, so treat the risk as the same. The daemon package's guard keeps `nct6775` and
  `w83627ehf` off every Gigabyte board, but it cannot stop `sensors-detect`, which
  probes the ports itself.
- **Do not run `pwmconfig` or `fancontrol`** while Ventulus drives your fans. Two
  programs writing the same header fight over it; see the manual's
  [Setup Checklist](../manual/setup-checklist.md#step-5--stop-competing-fan-control-software).

## ASUS

### LGA1700 (Z690 / Z790)

**Fan chip:** a Nuvoton NCT6798D (it reports `0xd42b`; the driver matches the `0xd428`
class). The in-kernel `nct6775` driver supports monitoring and PWM writes out of the
box.

**Extra sensors:** several ASUS Z690 / Z790 ROG boards are on the upstream
`asus_ec_sensors` list (hwmon device name `asusec`). The list grows with every kernel
(55 boards in 7.2, 60 in 7.3), so check
[docs.kernel.org/hwmon/asus_ec_sensors.html](https://docs.kernel.org/hwmon/asus_ec_sensors.html)
for the kernel you run. The LGA1700 entries in 7.2 are:

- ROG MAXIMUS Z690 FORMULA
- ROG MAXIMUS Z790 EXTREME
- ROG STRIX Z690-A GAMING WIFI D4 (the DDR4 board only; the DDR5 one is not listed)
- ROG STRIX Z690-E GAMING WIFI
- ROG STRIX Z790-E GAMING WIFI II
- ROG STRIX Z790-H GAMING WIFI
- ROG STRIX Z790-I GAMING WIFI

Kernel 7.3 adds ROG MAXIMUS Z790 HERO and ProArt Z690-CREATOR WIFI.

`asus_ec_sensors` provides semantic sensor labels (VRM, T_Sensor, Water_In/Out,
Chipset) but **no** PWM write path: it is sensor enrichment only.

**`asus_wmi_sensors` is AMD-only.** Its documented polling bugs (PRIME X470-PRO and
similar) concern AM4-era boards; the kernel's list has no Intel board. Do not apply
ASUS WMI advice from the AMD guide to Intel ROG boards.

**BIOS:**
- No BIOS setting makes the headers writable: under `nct6775` they already are, and
  the daemon switches each one to manual itself. *Q-Fan Tuning* is a one-shot
  calibration, not a mode; the mode item is *&lt;header&gt; Q-Fan Control* (Auto
  Detect / DC Mode / PWM Mode, to match the fan) and the curve item *&lt;header&gt; Fan
  Profile*. ASUS BIOS manuals have no "Manual" choice for Q-Fan Tuning.
- ACPI I/O port 0x0290–0x0299 conflicts can stop `nct6775` binding. Since Linux 5.16
  the driver reads supported ASUS boards through an ASUS WMI access path
  (`access_asuswmi`) that sidesteps the port reservation (a WMI sensor-read path, not
  an "ACPI mutex"); otherwise add the kernel parameter `acpi_enforce_resources=lax`
  (how: [Setting a driver option or a kernel parameter](19_Hardware_Compatibility.md#setting-a-driver-option-or-a-kernel-parameter)).

### LGA1851 (Z890 / B860)

ASUS Z890 and B860 boards carry an **NCT6701D** (LibreHardwareMonitor: "Before this
change, only the Nuvoton NCT6701D was exposed on this board", ROG STRIX Z890-E; also a
tested ROG STRIX B860-I). By chip ID mainline `nct6775` binds it as `nct6799`, as it
does on ASUS AM5 800-series boards, where fans and voltages read correctly and most
temperatures do not. No Linux log for an ASUS Z890 exists yet.

There is **no** Linux sensor-enrichment driver for these boards: no Z890 or B860 board
is on the `asus_ec_sensors` list, `asus_wmi_sensors` is AMD-only, and the generic
`asus-wmi` platform driver gives at most one `cpu_fan` reading on ASUS desktops.
Z890 / B860 boards are also not on the ASUS WMI access list, so `nct6775` uses the I/O
ports directly.

## MSI

### LGA1700 (Z690 / Z790)

**Fan chip:** the Nuvoton NCT6687D, the same chip MSI uses on every generation (it
reports `0xd592`), with the **default** EC register map. The in-kernel `nct6683`
driver enumerates the chip and reads sensors, but publishes every `pwmN` read-only on
MSI boards (and names its device `nct6687`, the same as the out-of-tree driver). Fan
control needs the out-of-tree `Fred78290/nct6687d` driver, with `nct6683` blacklisted, then a reboot (a
blacklist does not unload a module already loaded). The manual's
[Driver Setup](../manual/driver-setup.md#step-3--install-the-driver) has the steps.

Per the [Fred78290/nct6687d](https://github.com/Fred78290/nct6687d) source
(`nct6687.c::nct6687_msi_alt_boards[]`), MSI Z690 and Z790 boards use the **default**
register layout: `msi_alt1` is not needed and not auto-enabled. Never force it on
Z690/Z790, or every SYS_FAN reads 0 RPM.

No BIOS setting makes the headers writable. If they are read-only, the in-kernel
`nct6683` is bound: check with `ls -l /sys/class/hwmon/hwmon*/device/driver`.

In 2023 the in-kernel `nct6683` found the NCT6687D on an **MPG Z790 EDGE WIFI**
(MS-7D91) but exposed no sensors, while the out-of-tree `nct6687` worked with its
default map (lm-sensors issue #446, kernel bug 217591). There is no MSI board called
"MAG Z790 EDGE WIFI".

### LGA1851 (Z890)

**Fan chip:** the same NCT6687D (it reports `0xd592`), with a different EC register
layout. Monitoring tools label these boards *NCT6687DR*; no Nuvoton or MSI document
defines that name. Per `nct6687.c::nct6687_msi_alt_boards[]`, these boards need the
alt1 register layout. Current builds enable it automatically for listed boards, but
the list is still filling in for Z890 SKUs, and each entry is a full DMI name, so a
WHITE / PZ edition can be missing while its sibling is listed.

**Symptoms of `msi_alt1` being needed but missing:**
- PWM writes are accepted but fan RPM does not change.
- Fan tachometer readings are stuck at 0 or 65535.
- `sudo dmesg | grep 'active fan config'` shows `default` on a Z890 board.

If your board is not on the list, load the driver with the alt1 map:

```bash
echo 'options nct6687 fan_config=msi_alt1' | sudo tee /etc/modprobe.d/nct6687.conf
sudo modprobe -r nct6687 && sudo modprobe nct6687
```

Several Z890 boards (MAG Z890 TOMAHAWK WIFI, PRO Z890-P WIFI) also needed
`msi_fan_brute_force=1`, with `nct6683` blacklisted, before system-fan writes stuck;
the setup is in the [MSI notes](19_Hardware_Compatibility.md#msi-nct6687d). The GUI's
System State page shows this guidance on MSI boards whose `board_name` contains
`Z890`.

## Gigabyte

### LGA1700 (Z690 / Z790 AORUS)

**Primary chip:** the ITE **IT8689E** on Z690 / Z790 AORUS boards. Mainline `it87`
drives it, fan *control* included, from kernel 7.1 (commit `66b8eaf`). Below 7.1, which
includes Debian 13 (6.12) and Ubuntu 26.04 (7.0), the out-of-tree `frankcrawford/it87`
driver (DKMS) is needed. On 7.1 or later it is optional but still recommended: only it
publishes the board's GIGABYTE layout ID, which board header names need, and only it
handles the extra curve vectors that overrode manual mode before its PR #128.

**Secondary chip:** an **IT87952E** on the Z690 AORUS PRO / MASTER and the Z790 AORUS
MASTER / XTREME / PRO X (on the Z790 AORUS MASTER at `0x0b10`, not `0x0a60`). The
**Z790 AORUS ELITE / ELITE AX has the IT8689E only**. (The AMD X670E AORUS boards pair
their IT8689E with an IT8792E, not an IT87952E.)

If the System State page shows the dual-chip warning, the secondary is most likely
blocked by a latched Super-I/O bridge, the cause measured on AM5 boards. (On Z890 /
B860 boards, rule out a faulty driver build first: see [LGA1851](#lga1851-z890-aorus).)
A driver update does not clear a latch: keep `sensors-detect`, `nct6775` and `w83627ehf` away,
reboot, and if the chip is still missing, remove mains power. Follow
[Hardware Troubleshooting](../manual/hardware-troubleshooting.md#some-of-my-fan-headers-are-missing--only-5-of-8-show-up)
step by step; the [AMD guide](21_AMD_Motherboard_Fan_Control_Guide.md#a-secondary-super-io-that-will-not-enumerate)
explains why it works.

**BIOS:**
- On a current driver build usually none is needed. **Never give the BIOS curve a 0%
  point**: it runs the fans at boot and whenever the daemon is not controlling them.
- *Full Speed* in Smart Fan 6 **Fan Speed Control** is a fail-safe, not a fix: the
  firmware runs that fan at 100% whenever it owns it, but on some boards it also locks
  Linux out of the header (frankcrawford/it87 #115).
- For a 4-pin fan set the header's **FAN Control Mode** to PWM. The Smart Fan 6
  manuals checked have no "FAN Control by" item.

The [Gigabyte notes](19_Hardware_Compatibility.md#gigabyte-ite-chips) cover the IT8689E
fix and its hardware reports, including a Z790 AORUS MASTER with an IT8689E revision 1.

### LGA1851 (Z890 AORUS)

**Primary chip:** the ITE **IT8696E** (as on the AMD X870E AORUS boards). It needs
the out-of-tree `frankcrawford/it87` driver.

**Secondary chip:** an **IT87952E** on the Z890 AORUS MASTER (an owner's kernel log:
IT8696E at `0xa40`, IT87952E at `0xb10`,
[frankcrawford/it87 #139](https://github.com/frankcrawford/it87/issues/139)), and, per
the it87 SIV catalogue alone, on the Z890 AORUS XTREME AI TOP, PRO ICE, ELITE X ICE,
TACHYON ICE and TACHYON DUO X ICE, the Z890 AI TOP, the Z890 AERO D and the W880 AI
TOP (the it87 tracker has no report for those yet). All of them are in the daemon's
dual-chip table, so a missing secondary raises the warning on each. The **Z890 AORUS
ELITE WIFI7** (ICE / PLUS / DUO X) and the **B860I AORUS PRO ICE**
([#138](https://github.com/frankcrawford/it87/issues/138)) have the IT8696E only.

**Driver builds from 2026-09-09 to 2026-10-01 fail on these boards.** On a Z890 AORUS
MASTER `modprobe it87` failed with *Invalid argument* after
`H2RAM set_slot(1,…) failed: -22`, so neither chip registered (#139); on a B860I AORUS
PRO ICE the driver printed *Found IT8696E chip* and registered nothing (#138). The
fork's [PR #140](https://github.com/frankcrawford/it87/pull/140) fixed both on
2026-10-02: rebuild the it87 driver and reboot. If you must stay on such a build,
`options it87 mmio=off` (plus `ignore_resource_conflict=1` if the bind is then refused)
lets the module load, but the IT87952E loses its extra headers (SYS_FAN7/8_PUMP on the
Z890 AORUS MASTER). `mmio=on` is already the default and does not help. This is a
driver fault, not the bridge latch above. On a current build, the remedy and BIOS
rules are as for Z690/Z790.

## ASRock (Z690 / Z790 / Z890 / B860 / H810)

ASRock's Intel boards mix chips, per the block diagrams in ASRock's manuals:

- **Z690 Steel Legend, Z690 Extreme:** NCT6798D class (`nct6798`); the Z690 Extreme's
  physical part is an NCT6796D-E. Mainline `nct6775`, no out-of-tree driver needed.
- **Z790 Steel Legend WiFi:** NCT6796D-E, reported as `nct6798`.
- **Z790 PG Lightning, Z790 Pro RS:** NCT6796D (hwmon `nct6796`).
- **Z790 Taichi:** **NCT6686D (5 headers) + NCT5585D (3 headers)**. The NCT5585D is
  driven by `nct6775` (as `nct6798`); the NCT6686D's headers are read-only under the
  in-kernel `nct6683` and need an out-of-tree driver.
- **Z590 Taichi:** NCT6686D (the in-kernel `nct6683` recognises its customer ID from
  7.0; read-only).
- **Z890 boards** (Steel Legend, Lightning, Pro-A, Pro RS, Z890I Nova, Z890M Riptide,
  Nova, Taichi, Taichi Lite): the fans are on an **NCT6686D**; the Nova, Taichi and
  Taichi Lite add an NCT6796D-E with only MOS_FAN1 wired. PWM needs `nct6687d`, or
  `asrock-nct6683` on the Z890 Nova WiFi. The exception is the **Z890 Taichi OCF**,
  whose second chip is a plain NCT6796D (`nct6796`, mainline `nct6775`) carrying two
  fan headers.
- **B860 Steel Legend WiFi, B860M Steel Legend WiFi, B860 / B860I Lightning WiFi:**
  **NCT6686D only**, as on the Z890 boards.
- **B860 Pro RS, B860 / B860M Pro-A (WiFi), B860M Pro RS, B860M-X:** a plain
  **NCT6796D** (`nct6796`) only. Mainline `nct6775`, no out-of-tree driver needed.
- **H810M-X:** an **NCT5585D** (reported as `nct6798`), mainline `nct6775`.

The plain Z690 Taichi's chips are unverified. The out-of-tree drivers for the NCT6686D
are compared in the [ASRock notes](19_Hardware_Compatibility.md#asrock).

**Worked example: ASRock Z690 Extreme.** The community
[petersulyok/asrock_z690_extreme](https://github.com/petersulyok/asrock_z690_extreme)
config is in the upstream lm-sensors repository (`configs/ASRock/Z690_Extreme.conf`).
The chip enumerates as `nct6798-isa-02a0` although the physical part is an
NCT6796D-E. Ventulus ships verified fallback labels for this board:

| `pwmN` | Label |
|---|---|
| `pwm1` | Chassis fan3 |
| `pwm2` | CPU fan1 |
| `pwm3` | CPU fan2 |
| `pwm4` | Chassis fan1 |
| `pwm5` | Chassis fan2 |
| `pwm6` | Chassis fan4 |
| `pwm7` | Chassis fan5 |

**BIOS:**
- Headers on the NCT67xx chip are always writable under `nct6775`, and the daemon sets
  manual mode itself; no BIOS setting unlocks them. If a fan does not follow, check
  that the header's BIOS fan type matches the fan (DC for 3-pin, PWM for 4-pin).
- Headers on an NCT6686D are read-only under the in-kernel `nct6683` whatever the BIOS
  says (`ls -l` shows `-r--r--r--`); writes are refused. Use an out-of-tree driver
  there.

## CPU temperature on Intel

Intel CPU temperature comes from the mainline `coretemp` driver, which exposes:

- `Package id 0`: the overall package temperature (use this for thermal safety and fan
  curves)
- `Core 0` / `Core 1` / …: per-physical-core temperatures

The daemon classifies `coretemp` sensors as CPU temperatures automatically, and the GUI
shows them as **high-confidence** CPU die temperatures.

On Super-I/O chips that also expose Intel PECI (e.g. an NCT6798D wired through the LPC
bus to the CPU), the kernel exposes labels like `PECI Agent 0` (`nct6775`) or
`PECI 0.0` (`nct6683`). The GUI classifies these as `cpu_peci` at `medium_high`
confidence, with an "Intel CPU temperature reported via the PECI bus" tooltip.

The `intel_pch_thermal` driver registers an hwmon device for the PCH (Platform
Controller Hub) temperature. It is **sensor enrichment only**, not a fan-control path;
the System State page lists it as "loaded (mainline)" when present.

The kernel's `x86_pkg_temp_thermal` driver covers the same physical sensor as
`coretemp` but registers with `.no_hwmon = true`: it appears only as a thermal zone,
never under `/sys/class/hwmon`. The daemon uses `coretemp`.

## Troubleshooting an Intel board

1. **Identify the chip:** `cat /sys/class/hwmon/hwmon*/name` shows what bound. Compare
   with the vendor section above.
2. **Check the CPU vendor:** the daemon's `/diagnostics/hardware` response includes
   `cpu_vendor` (`"Intel"` / `"AMD"`). The GUI uses it to scope platform-specific
   guidance; if it is empty, the Intel-specific board notes do not appear.
3. **Look for the dual-chip warning** on Gigabyte LGA1700/LGA1851 AORUS boards. A
   missing IT87952E is most likely a blocked Super-I/O (see Gigabyte above).
4. **Watch for BIOS reclaim:** the daemon's `pwm_enable` watchdog detects firmware
   switching a header out of manual mode and re-asserts it. The remedy is per vendor:
   on Gigabyte, a current it87 driver build (Full Speed is a fail-safe, not a fix);
   `msi_fan_brute_force=1` on MSI Z890; on ASUS and ASRock no BIOS setting is known to
   stop it. Read-only headers are a different problem: the driver, not the BIOS.
5. **Z890:** if PWM writes are accepted but fans do not change speed, try
   `fan_config=msi_alt1` before assuming the board is unsupported.

## Out of scope

- **Intel Arc / Xe GPU fan control:** Intel Arc desktop GPUs report fan speed (`i915`
  for Arc A-series from Linux 6.12, `xe` for Arc B-series from 6.16), but no mainline
  kernel has a writable fan-control path as of 7.3 (Intel's patches adding one were
  still under review in October 2026). Ventulus monitors them only; see
  [Intel discrete GPU monitoring](19_Hardware_Compatibility.md#intel-discrete-gpu-arc-monitoring).
- **`thermald`:** the Intel thermal daemon manages CPU frequency and turbo state
  through the thermal-zone API, not hwmon. It is independent of motherboard fan
  control.
- **Hybrid P-core / E-core:** `coretemp` exposes both as `Core N` / `Package id 0`. Fan
  control treats them identically; Alder Lake, Raptor Lake and Arrow Lake need no
  special handling.

## References

**Kernel documentation:**
[coretemp](https://docs.kernel.org/hwmon/coretemp.html) ·
[nct6775](https://docs.kernel.org/hwmon/nct6775.html) ·
[nct6683 family](https://docs.kernel.org/hwmon/nct6683.html) ·
[it87](https://docs.kernel.org/hwmon/it87.html) ·
[asus_ec_sensors](https://docs.kernel.org/hwmon/asus_ec_sensors.html) ·
[asus_wmi_sensors (AMD-only)](https://docs.kernel.org/hwmon/asus_wmi_sensors.html)

**Out-of-tree drivers:**
- [Fred78290/nct6687d](https://github.com/Fred78290/nct6687d): MSI NCT6687D (default and msi_alt1 register maps)
- [frankcrawford/it87](https://github.com/frankcrawford/it87): ITE IT8625E+

**Community references:**
- [petersulyok/asrock_z690_extreme](https://github.com/petersulyok/asrock_z690_extreme): ASRock Z690 Extreme lm-sensors config
- [lm-sensors/lm-sensors](https://github.com/lm-sensors/lm-sensors): upstream configs directory
- [LibreHardwareMonitor PR #1621](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/pull/1621): MSI Z890 NCT6687D documentation
- [LibreHardwareMonitor PR #2526](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/pull/2526) and [#2512](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/pull/2512): ASUS ROG STRIX Z890-E (NCT6701D); Gigabyte Z890 AORUS MASTER (IT8696E + IT87952E)
- [lm-sensors issue #446](https://github.com/lm-sensors/lm-sensors/issues/446): MSI MPG Z790 EDGE WIFI (MS-7D91)
