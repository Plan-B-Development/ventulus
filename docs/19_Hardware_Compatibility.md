# Hardware Compatibility Guide

This is the reference for the hardware Ventulus works with: the Super-I/O chips and
kernel drivers behind motherboard fan headers, the vendor quirks that decide whether a
header can be controlled, and the GPUs and liquid coolers the daemon supports. The app's
in-app guidance links here.

To install a driver step by step, use the manual's [Driver Setup](../manual/driver-setup.md).
To start from a symptom, use [Hardware Troubleshooting](../manual/hardware-troubleshooting.md).
The [AMD](21_AMD_Motherboard_Fan_Control_Guide.md) and
[Intel](23_Intel_Motherboard_Fan_Control_Guide.md) guides go board by board.

## Where to start

| What you see | Where to read |
|---|---|
| *No hwmon chips detected* | Find your board in the [AMD](#amd-platform--typical-chip-mapping) or [Intel](#intel-platform--typical-chip-mapping) table, then follow [Driver Setup](../manual/driver-setup.md) |
| *All PWM headers are read-only* | [Read-only PWM headers](24_Cooling_Hardware_Readiness_Guide.md#read-only-pwm-headers); for your vendor, [MSI](#msi-nct6687d) or [ASRock](#asrock) |
| The BIOS keeps taking a header back | Your vendor under [Manufacturer quirks](#manufacturer-quirks) |
| A board note on the System State page | Your vendor under [Manufacturer quirks](#manufacturer-quirks) |
| A critical *Driver module collision* | [The NCT679x chip-ID collision](#the-nct679x-chip-id-collision) |
| Fewer fan headers than the board has | [Hardware Troubleshooting](../manual/hardware-troubleshooting.md#some-of-my-fan-headers-are-missing--only-5-of-8-show-up) |

## Supported chip families

### Nuvoton

| Chip Series | Kernel Driver | Mainline | Package |
|-------------|--------------|----------|---------|
| NCT679x (NCT6798, NCT6799) | `nct6775` | Yes | linux (built-in) |
| NCT6797D (reports `0xd451`; driver class `0xd450`) | `nct6775` | Yes (via `nct6775-platform.c`) | linux (built-in). **See [the chip-ID collision](#the-nct679x-chip-id-collision)** |
| NCT6795D | `nct6775` | Yes | linux (built-in). Common on the MSI AM4 X470 GAMING PRO and X470 GAMING PRO CARBON |
| NCT6792D | `nct6775` | Yes | linux (built-in). Common on ASRock AM4 ITX |
| NCT6779D | `nct6775` | Yes | linux (built-in). Common on ASRock AM4 300/400-series ATX |
| NCT677x (NCT6775, NCT6776) | `nct6775` | Yes | linux (built-in) |
| NCT6701D (`0xd806`) | `nct6775`, reported as `nct6799` | Yes | linux (built-in). ASUS AM5 800-series and Z890/B860 boards. `sensors-detect` calls it unknown; fans and voltages read correctly, most temperature channels do not ([lm-sensors #544](https://github.com/lm-sensors/lm-sensors/issues/544)) |
| NCT6683 (chip ID 0xc730) | `nct6683` | Yes, **read-only** | linux (built-in) |
| NCT6686D (reports `0xd441`; driver class `0xd440`) | `nct6683` | Yes, **monitoring only** | linux (built-in). The in-kernel driver publishes `pwmN` read-only on every board except Mitac OEM systems, and has no `pwmN_enable`. PWM needs an out-of-tree driver (`asrock-nct6683`, `nct6687d` or `nct6686d`) |
| NCT6687D (reports `0xd592`; drivers match `0xd590`) | `nct6687` (out-of-tree); the in-kernel `nct6683` reads it read-only | **No** for control | out-of-tree `Fred78290/nct6687d`. **Never with `force=1` on an NCT679x board: see [the chip-ID collision](#the-nct679x-chip-id-collision)** |

**Mainline `nct6775` names a register class, not a part.** Its hwmon names cover
several physical chips each (`SIO_ID_MASK 0xFFF8`): `nct6797` is the NCT6797D
(`0xd45x`); `nct6798` is the `0xd428` class, which kernel 7.3 renames
"NCT6798D/NCT5585D" and which also catches the NCT6796D-E and -R; `nct6799` is
the `0xd80x` class ("NCT6796D-S/NCT6799D-R"), which also catches the NCT6701D. So
an ASRock board whose manual says NCT6796D-S reports `nct6799`, and one that says
NCT6796D-E reports `nct6798`.

**The NCT6683 / NCT6686 / NCT6687 family.** The chip IDs below come from the
out-of-tree driver's register definitions
([Fred78290/nct6687d/nct6687.c](https://github.com/Fred78290/nct6687d/blob/main/nct6687.c))
and the mainline `nct6683` driver
([drivers/hwmon/nct6683.c](https://github.com/torvalds/linux/blob/master/drivers/hwmon/nct6683.c)).
**The hwmon name does not tell you which driver bound the chip:** mainline
`nct6683` names its devices after the chip kind (`nct6683`, `nct6686`,
`nct6687`) exactly as the out-of-tree driver does. Check the bound driver with
`ls -l /sys/class/hwmon/hwmon*/device/driver`. If the `pwmN` files are
read-only (`-r--r--r--`), it is the in-kernel `nct6683`.

| Chip      | Chip ID | Driver          | Boards seen                                   |
|-----------|---------|-----------------|-----------------------------------------------|
| NCT6683   | `0xc730` | `nct6683` (mainline, read-only) | older MSI / ASRock; the B550 Taichi's fan EC is an NCT6683D-class part |
| NCT6686D  | `0xd440` (reports `0xd441`) | `nct6683` (mainline; read-only) or out-of-tree `asrock-nct6683` / `nct6687d` / `nct6686d` | most ASRock AM5 Steel Legend boards (not the B850M Steel Legend WiFi), the LiveMixer / Riptide / Lightning boards, the AM5 and Z790/Z890 Taichi boards, most ASRock Z890 boards, the B860 Steel Legend / Lightning boards, and the BC-250 (which the kernel names "AMD BC-250") |
| NCT6687D | `0xd590` (reports `0xd592`) | `Fred78290/nct6687d` (out-of-tree) for control | MSI B550 (MAG B550 TOMAHAWK, B550-A PRO), the X570S MPG refresh, B650/X670 (MAG B650 TOMAHAWK WIFI, MAG X670E TOMAHAWK WIFI, MPG X670E CARBON WIFI), Intel 600/700-series; and, with the alternate "msi_alt1" register map, the B840/B850/B860/X870/X870E/Z890 boards (monitoring tools label those *NCT6687DR*) |

(NCT6797D = `0xd450` and NCT6798D = `0xd428` are separate `nct6775`-driven chips;
the `nct6775-platform.c` constants in the mainline driver source give both.)

#### The NCT679x chip-ID collision

Older builds of the out-of-tree `nct6687` driver declare chip ID `0xd450`, the ID
the mainline driver assigns to the NCT6797D
([`nct6775-platform.c`](https://github.com/torvalds/linux/blob/master/drivers/hwmon/nct6775-platform.c):
`#define SIO_NCT6797_ID 0xd450`). With `nct6687` and `nct6775` both loaded, the
wrong driver can bind the chip and write into the wrong registers. The
[Bazzite report (ublue-os/bazzite #4498)](https://github.com/ublue-os/bazzite/issues/4498)
documents a permanently bricked CPU_FAN header on an MSI MAG X570 TOMAHAWK WIFI from
this race (its chip reads `0xd451`, which masks to `0xd450`).

**Which boards.** The NCT6797D is on MSI AM4 400-series boards (B450M MORTAR per its
upstream lm-sensors config, MAG B450 TOMAHAWK MAX), the X570-A PRO, the original 2019
MPG X570 boards and the MAG X570 TOMAHAWK WIFI. The MSI X470 GAMING PRO and its CARBON
carry an NCT6795D. MSI moved to the NCT6687D with B550, so no AM4 400-series MSI board
needs `nct6687`.

**Why the risk remains.** Upstream removed the `0xd450` claim in
[Fred78290/nct6687d PR #164](https://github.com/Fred78290/nct6687d/pull/164)
(merged 2026-05-19), so a current build no longer claims the chip by default. The
risk stays three ways: a module already loaded, a package not yet updated, and
**`force=1`**. Since [PR #174](https://github.com/Fred78290/nct6687d/pull/174) that
parameter attaches to any chip ID from `0xD000` to `0xDFFF`, NCT6795D, NCT6797D,
NCT6798D and NCT6799D included. Never load `nct6687` with `force=1` on an NCT679x
board. (The in-kernel `nct6683` driver's own `force=1` is different: it reads a board
whose customer ID it does not know, and never makes PWM writable.)

Bazzite #4498 was closed on 2026-09-07 without a distro fix. Since 2026-08-15 Bazzite
ships the Terra `nct6687d` kmod, which autoloads `nct6687` and blacklists `nct6683` on
every machine. On an NCT6797D board that is safe only because a current `nct6687d` no
longer claims `0xd450`.

**What to do.**

1. Identify the chip. `sudo dmesg | grep -i 'found nct'` shows which driver found
   which chip at which address; two drivers reporting a chip at the same address
   means both claimed it.
2. On an NCT6795D, NCT6797D or NCT6798D board, blacklist `nct6687`:

   ```bash
   echo 'blacklist nct6687' | sudo tee /etc/modprobe.d/blacklist-nct6687.conf
   grep -r nct6687 /etc/modules-load.d/
   ```

   Remove any `nct6687` line the second command finds: `blacklist` stops automatic
   loading only, not a load that a file under `/etc/modules-load.d/` or a
   `modprobe nct6687` asks for.
3. Reboot. A blacklist does nothing to a copy already loaded.

The daemon reports the collision in `/diagnostics/hardware` → `module_collisions`, and
the System State page shows it as a critical *Driver module collision* condition.
**The daemon does not stop writing while it is reported.** Until you have rebooted
and it is gone, deactivate the active profile (**Stop** under the GUI sidebar's
profile selector, or the tray's *Stop profile control*) and run no fan tests. That
stops the curve, not every write: the daemon restores each header's original mode
once (100 % if it cannot confirm it), and a thermal emergency still drives writable
headers to 100 %. Only removing the wrong driver stops writes to the chip.

A board with two separate Nuvoton chips needs both drivers, and each binds its own
chip, so the detector stays quiet whenever it finds two distinct Nuvoton chip IDs. It
keys on the chips, not on a list of board names. The ASRock Taichi boards, with an
NCT6686D and an NCT6796D-S, are the usual case (see the
[AMD guide](21_AMD_Motherboard_Fan_Control_Guide.md#taichi-boards-two-nuvoton-chips)).

### ITE

| Chip Series | Kernel Driver | Mainline | Package |
|-------------|--------------|----------|---------|
| Legacy IT87xx: IT8603E, IT8620E, IT8622E, IT8623E, IT8628E, IT8705F, IT8712F, IT8716F, IT8718F, IT8720F, IT8721F, IT8726F, IT8728F, IT8732F, IT8758E, IT8771E, IT8772E, IT8781F, IT8782F, IT8783E/F, IT8786E, IT8790E, IT8792E/IT8795E. Only these: a chip in the same number range that is not named here (IT8686E, IT8688E, IT8696E and the rows below) is not mainline | `it87` | Yes (per the mainline `enum chips`, verified at the **v7.2** release tag, 2026-08-16, and again at 7.3-rc4) | linux (built-in) |
| IT8613E | `it87` | **Not yet**: queued in hwmon-next, so expected in **7.4** | out-of-tree `frankcrawford/it87` until then |
| IT8625E | `it87` | **No**: no mainline submission since October 2024, when changes were requested; not in 7.3-rc4 | out-of-tree `frankcrawford/it87` |
| IT8665E | `it87` | **No** | out-of-tree `frankcrawford/it87`. ASUS AM4 300/400-series boards (PRIME X470-PRO, ROG STRIX B450-F, X470-F/-I: [issue #27](https://github.com/frankcrawford/it87/issues/27)) and X399-era boards. Use a build from 2026-07-22 or later: see [MMIO](#gigabyte-ite-chips) |
| IT8686E | `it87` | **No** | out-of-tree `frankcrawford/it87` |
| IT8688E | `it87` | **No** | out-of-tree `frankcrawford/it87` |
| IT8689E | `it87` | **Yes (control) since 7.1**: six PWM + `FEAT_FANCTL_ONOFF` (commit `66b8eaf`, merged 2026-03-31; 7.1 released 2026-06-14) | needed below 7.1, which includes Debian 13 (6.12) and Ubuntu 26.04 (7.0); on 7.1 or later (Fedora 43 to 45, Arch, CachyOS) it is optional. The out-of-tree `frankcrawford/it87` still adds the board's GIGABYTE layout ID, which board header names need, and the handling for the extra curve vectors that override manual mode on some boards (the fork's PR #128). Ventulus reads the running kernel: it calls the kernel's own driver mainline on 7.1 or later and out-of-tree below |
| IT8696E | `it87` | **No** | out-of-tree `frankcrawford/it87`. Primary on AM5 800-series and Z890 Gigabyte boards |
| IT87952E | `it87` | **Yes since 6.3 for enumeration** (commit `d44cb4cd7456`: v6.2 lacks it, v6.3 has it). Control of the secondary chip on dual-IO Gigabyte boards needs the DKMS MMIO path | out-of-tree `frankcrawford/it87` for control. Secondary chip on dual-IO Gigabyte boards (e.g. X870E AORUS MASTER, Z790 AORUS MASTER) |
| "IT8883" | *(not a distinct sensor chip)* | — | Device-ID `0x8883` at a secondary Super-I/O address is **not a sensor chip**. It is an ITE eSPI→LPC **bridge** latched in configuration mode, answering in place of the chip behind it ([#64](https://github.com/frankcrawford/it87/issues/64); ITE lists the IT8883 as "3VSB and VBAT Supported", so it keeps standby power). `it87` has no entry for `0x8883`, while it *does* support the IT87952E, so while the bridge is latched the secondary is **unreachable, not unsupported**. **It is recoverable** (measured 2026-09-05; see [below](#a-secondary-chip-that-does-not-enumerate)). `0xFFFF` is the same blocked state read without the unlock key ([#70](https://github.com/frankcrawford/it87/issues/70)). Neither value is visible by default: the driver prints `Unsupported chip (DEVID=…)` with `pr_debug` and exits silently on `0xFFFF`. *(Corroborating: on the AAEON Elkhart Lake embedded board of [issue #117](https://github.com/frankcrawford/it87/issues/117), a contributor identifies `0x8883` as an ITE LPC↔eSPI bridge chip, with the maintainer investigating the real sensor chip behind it. Confidence C: a contributor comment, not maintainer-confirmed.)* |

The out-of-tree `it87` driver is maintained by Frank Crawford:
https://github.com/frankcrawford/it87. Its `force_id` parameter is for testing only;
see [Driver Setup](../manual/driver-setup.md#module-parameters-you-may-actually-need).

Recent Gigabyte AORUS boards pair a primary ITE Super-I/O with a secondary that
exposes additional headers (typically SYS_FAN4 / FAN5_PUMP / FAN6_PUMP). **The
secondary is not the same chip everywhere:** AM5 800-series, Z890 and Z690/Z790
boards use an **IT87952E** (hwmon `it87952`) beside an IT8696E or IT8689E, while
AM5 600-series boards such as the X670E AORUS MASTER pair their IT8689E with an
**IT8792E** (hwmon `it8792`), as do the X570 / B550 / X470 generations with their
IT8688E / IT8686E. Some boards with near-identical names have no secondary at
all: the X870E AORUS ELITE WIFI7, X670 AORUS ELITE AX and Z790 AORUS ELITE AX
have one chip. Both kinds of secondary ship in the same `it87` driver, but the
secondary's enumeration depends on a healthy Super-I/O bridge state at boot.

**Driver state, 2026-09.** The frankcrawford/it87 master branch merged the
ISA-bridge **MMIO/H2RAM access path**
([PR #102](https://github.com/frankcrawford/it87/pull/102), 2026-04), switched
**MMIO on by default** ([PR #95](https://github.com/frankcrawford/it87/pull/95),
2026-03; `mmio=off` is the opt-out), and on 2026-08-24 merged
[PR #128](https://github.com/frankcrawford/it87/pull/128), which handles the
firmware logic that kept or retook headers (IT8689E and IT8688E rev 2 extra curve
vectors, the SmartFan enable on the IT879x secondaries). On 2026-10-02
[PR #140](https://github.com/frankcrawford/it87/pull/140) moved the IT8689E, IT8696E
and IT8698E (and the IT8688E revision 2) to the chip's own MMIO window and lets the
IT87952E reach its extra H2RAM headers without the ISA bridge. On the IT8688E,
IT8689E, IT8696E and IT8698E the MMIO path also sidesteps the ACPI I/O-port
conflicts that once forced `acpi_enforce_resources=lax`
([issue #81 discussion](https://github.com/frankcrawford/it87/issues/81)). Boards
with an IT8686E, or an IT8792E / IT87952E second chip, can still need
`ignore_resource_conflict=1` (X399 boards,
[PR #135](https://github.com/frankcrawford/it87/pull/135) and
[PR #141](https://github.com/frankcrawford/it87/pull/141); Z890 AORUS MASTER,
[issue #139](https://github.com/frankcrawford/it87/issues/139)). Master carries a
built-in DMI ACPI-exemption table (`it87_acpi_ignore`) for known-safe boards. The
driver picks up the current upstream snapshot only when you rebuild it (on Arch,
by reinstalling the `-git` AUR package). Since
2026-08-23 the fork builds only on kernel 6.4 or newer, so the 6.1, 5.15 and 5.10
LTS kernels cannot build it ([PR #142](https://github.com/frankcrawford/it87/pull/142),
a draft fix).

**Intel Z890 / B860, builds from 2026-09-09 to 2026-10-01.** On these boards those
builds can fail outright: on a Z890 AORUS MASTER `modprobe it87` failed with
*Invalid argument* after `H2RAM set_slot(1,…) failed: -22`, so neither chip
registered ([#139](https://github.com/frankcrawford/it87/issues/139)); on a B860I
AORUS PRO ICE the driver printed *Found IT8696E chip* and then registered nothing
([#138](https://github.com/frankcrawford/it87/issues/138)). PR #140 fixed both on
2026-10-02, so rebuild the it87 driver. On such a build, `options it87 mmio=off`
(plus `ignore_resource_conflict=1` if the bind is then refused) gets the module to
load, but the IT87952E loses its extra headers (SYS_FAN7/8_PUMP on the Z890 AORUS
MASTER). This is a driver fault, not the bridge latch described below.

#### it87 v2.0 renames Gigabyte chips

Builds from 2026-09-09 on ([PR #132](https://github.com/frankcrawford/it87/pull/132))
name each Gigabyte chip after the board's SIV whenever the driver can read it:
`it8696_a008090a` instead of `it8696`. The daemon strips the suffix where it reads the
chip name, so every header, sensor, fan and voltage id stays the same, the built-in
board labels and the dual-chip check keep matching, and ids saved under the suffixed
spelling are read back canonical. It publishes the sysfs spelling beside the canonical
one as `sysfs_chip_name`, and the GUI matches `/etc/sensors.d` blocks against that,
exactly as `sensors` does, so a block written for the old `it8696-*` name stops
applying. [Driver Setup](../manual/driver-setup.md#it87-v20-renames-your-chips) has
the detail.

#### Board names from the SIV catalogue

The ITE chips publish no fan or temperature labels. When the out-of-tree driver
publishes the board's SIV (`/sys/class/gigabyte/id/gigabyte_siv`; the in-kernel
`it87` does not), the daemon looks it up in a catalogue built from the
frankcrawford/it87 Gigabyte sensor configs and names the channels the driver left
unnamed (DEC-500): fan headers (`CPU_FAN`, `SYS_FAN5_PUMP`), monitor-only fans and
temperatures (`VRM MOS`, `PCIEX16`), as it already named voltage rails (DEC-464).
The key is the CPU platform, the chip and the SIV, never the board name. A header's
catalogue name is role evidence: a `*_PUMP` header is protected as a pump and a
`CPU_FAN` or `CPU_OPT` header gets the 30 % floor, as the same driver label would.
A temperature's name is for display only. Where a second, independent reading of
GIGABYTE's own sensor tables disagrees with a config, the channel is left unnamed
(124 channels on 27 layouts, among them the A0030507 and A0040607 pump and `CPU_OPT`
headers and the IT87952E `temp1` on five layouts). The Hardware page's
Board layout panel shows the layout, whether upstream lists your board for it, and
every name it gave. [Board header names](../manual/hardware-troubleshooting.md#board-header-names-from-the-it87-catalogue)
in the manual covers what the names do and how to correct one.

#### A secondary chip that does not enumerate

On some systems only the primary chip appears (5 of 8 fan headers on an X870E AORUS
MASTER). Profile members on the missing chip, on that board both pump headers, are
kept and marked **header missing** on the Controls page until the chip returns.

The secondary is blocked: an ITE eSPI→LPC bridge is latched in configuration mode and
answers in place of the chip. Anything that sends the Super-I/O unlock key to port
0x2E/0x4E writes the latch. `nct6775` and `w83627ehf` do so before reading the device
ID, even on boards they cannot drive, and `sensors-detect` does too. Cause and cure
were both reproduced on an X870E AORUS MASTER (BIOS F14c, it87 349.c567739) on
2026-09-05. The frankcrawford/it87 issue [#70](https://github.com/frankcrawford/it87/issues/70)
(Gigabyte X870E AORUS PRO, missing SYS_FAN4/5/6) is the same state seen from the other
side; there a clean power cycle did **not** restore the chip either.

The recovery is one ladder whatever ID the chip gives: keep `nct6775`, `w83627ehf` and
`sensors-detect` away from the Super-I/O, reboot, and if the chip is still missing,
remove mains power. `mmio=on` does not help (it is already the default) and
`force_id` is for testing only. The steps are in
[Hardware Troubleshooting](../manual/hardware-troubleshooting.md#some-of-my-fan-headers-are-missing--only-5-of-8-show-up),
and the [AMD guide](21_AMD_Motherboard_Fan_Control_Guide.md#a-secondary-super-io-that-will-not-enumerate)
explains what latches the bridge. When DMI matches a known dual-chip board but only one
ITE chip enumerated, the System State page shows a warning with the remediation.

### Other ASUS sensor-only drivers

The hwmon device names differ from the module names: `asus_ec_sensors` registers as
**`asusec`** and `asus_atk0110` as **`atk0110`**. That matters when reading
`/sys/class/hwmon/*/name` or matching a board note.

| Driver (hwmon name) | Mainline | Function |
|---|---|---|
| `asus_wmi_sensors` (`asus_wmi_sensors`) | Yes | Read-only board sensor enrichment via WMI, on 16 boards listed by exact name: the X370 / X470 / B450 ROG CROSSHAIR VI / VII, ROG STRIX B450 and X470 boards, PRIME X470-PRO, and the X399 boards. The [kernel doc](https://docs.kernel.org/hwmon/asus_wmi_sensors.html) warns that buggy ASUS BIOS WMI can stop fans, pin them at maximum or freeze readings, more likely the more often it is polled. It singles out the **PRIME X470-PRO** as "particularly bad", names no safe polling rate, and advises a soak test. No BIOS version is a known fix: the driver only loads when the BIOS reports WMI method version 2 or later, so that version cannot be the remedy, and the kernel doc queued for 7.4 drops that advice and says only that a more recent BIOS "might help" ([hwmon patch, 2026-10-16](https://patch.msgid.link/20261016163509.249020-1-heyheyco@gmail.com)). Never the PWM write path: on the boards with evidence the fan chip is an ITE IT8665E. |
| `asus_ec_sensors` (`asusec`) | Yes | Read-only EC sensor enrichment on boards listed by exact name: 55 in kernel 7.2, 60 in 7.3; check the [kernel doc](https://docs.kernel.org/hwmon/asus_ec_sensors.html) for the kernel you run. The AM4 400-series entries are the PRIME X470-PRO, ROG STRIX X470-I GAMING (6.19+) and ROG STRIX X470-F GAMING (7.1+). No Z890, B860, B850-A or B850-F board is listed. From 7.3 an unconnected T_Sensor or water-probe socket reads as unavailable instead of a -62/-60/-40 °C placeholder. |
| `asus_atk0110` (`atk0110`) | Yes | Read-only ACPI ATK0110 hwmon on older ASUS boards that publish that ACPI device. If you see this driver loaded but no controllable headers, look for `nct6775` or `it87` as the PWM path. |

### Fintek

| Chip Series | Kernel Driver | Mainline | Package |
|-------------|--------------|----------|---------|
| F71805F, F71806F, F71872F | `f71805f` | Yes | linux (built-in) |
| F71882FG and the rest of the F718xx series, F8000, F81865F/F81866A, F81768D | `f71882fg` | Yes | linux (built-in) |

### Winbond

| Chip Series | Kernel Driver | Mainline | Package |
|-------------|--------------|----------|---------|
| W83627EHF/EHG, W83627DHG, W83627UHG, W83667HG | `w83627ehf` | Yes | linux (built-in) |
| W83627HF, W83627THF, W83637HF, W83687THF, W83697HF | `w83627hf` | Yes | linux (built-in) |

### SMSC

| Chip Series | Kernel Driver | Mainline | Package |
|-------------|--------------|----------|---------|
| LPC47B397-NC, SCH5307-NS, SCH5317 | `smsc47b397` | Yes | linux (built-in) |
| LPC47B27x, LPC47M10x/M112/M13x/M14x/M15x/M192/M997, LPC47M292 | `smsc47m1` | Yes | linux (built-in) |
| LPC47M15x/M192/M292/M997 hardware-monitoring block (I2C; voltages and temperatures only; fan control is `smsc47m1`) | `smsc47m192` | Yes | linux (built-in) |
| DME1737, SCH311x, SCH5027, SCH5127 | `dme1737` | Yes | linux (built-in) |
| SCH5627 | `sch5627` | Yes | linux (built-in) |
| SCH5636 | `sch5636` | Yes | linux (built-in) |

### National Semiconductor

| Chip Series | Kernel Driver | Mainline | Package |
|-------------|--------------|----------|---------|
| PC87360, PC87363, PC87364, PC87365, PC87366 | `pc87360` | Yes | linux (built-in) |
| PC87427 | `pc87427` | Yes | linux (built-in) |

### Memory modules (monitor-only)

Memory temperatures come from a sensor on each module, read over the board's SMBus,
or from a board chip that reports a memory channel. The daemon only reads them; they
are not part of the thermal safety rules.

| Memory | Kernel driver (hwmon name) | Requirement |
|---|---|---|
| DDR5 | `spd5118` | Kernel 6.11 or later. The kernel registers each module from the firmware's memory table, on Intel (`i2c_i801`) and AMD (`i2c_piix4`) SMBus controllers. Current kernels skip it where the firmware locks SPD writes (Intel "SPD Write Disable"). |
| DDR4 / DDR3 | `jc42` (with `ee1004` for the SPD EEPROM) | Only a module that carries a JEDEC thermal sensor has a reading; most consumer DDR4 modules do not. |
| Board channel | `nct6683` family (`DIMM n`), `nct6775` family (`PCH_DIMn_TEMP`, `AgentN DimmN`), `dell_smm` (`SODIMM`) | Whatever the board firmware routes to that channel. |

Why a machine may show none, and what to check: [Hardware Troubleshooting →
Sensors missing](../manual/hardware-troubleshooting.md#sensors-missing-or-fewer-than-expected).
How the GUI names and classifies them: [Sensor Interpretation Guide](20_Sensor_Interpretation_Guide.md#memory-temperatures-spd5118-jc42-and-board-dimm-channels).

## AMD platform → typical chip mapping

The hwmon chips you are likely to find on each AMD platform generation. Use it as a
starting point, not a complete list. Entries are cross-referenced against upstream
lm-sensors `configs/`, the kernel `asus_*` driver lists, the frankcrawford/it87
Gigabyte SIV sensor catalogue, LibreHardwareMonitor board definitions, ASRock manual
block diagrams and exact-board logs (re-checked board by board on 2026-09-24). The
fork's DMI-table *comments* are not used as evidence: several were found attached to
the wrong board.

| Generation | Typical Vendors | Typical Hwmon Chip(s) | Driver Path |
|---|---|---|---|
| **AM4 400-series** (B450 / X470) | ASUS (PRIME X470-PRO, ROG STRIX B450-F, ROG STRIX X470-F / X470-I) | **ITE IT8665E** ([it87 #27](https://github.com/frankcrawford/it87/issues/27): "Chip markings and sensors-detect say that this is IT8665E") + sensor-only `asus_wmi_sensors` / `asus_ec_sensors` | out-of-tree `frankcrawford/it87` for fans; mainline has no IT8665E driver, and the ASUS drivers are sensors only |
| | MSI (B450M MORTAR, MAG B450 TOMAHAWK MAX; X470 GAMING PRO and X470 GAMING PRO CARBON) | NCT6797D (MORTAR, TOMAHAWK MAX) / NCT6795D (X470 GAMING PRO, and its CARBON) | mainline `nct6775`. **Never load `nct6687` here, and never with `force=1`** |
| | Gigabyte (X470 AORUS ULTRA/GAMING 5/7, B450 AORUS PRO/PRO-CF) | IT8686E + IT8792E (dual-chip; the B450 AORUS PRO's IT8792E carries no fan header) | out-of-tree `frankcrawford/it87` |
| | ASRock (B450 Gaming-ITX/ac; B450 Pro4, X470 Taichi) | NCT6792D (ITX) or NCT6779D (ATX / micro-ATX) | mainline `nct6775` |
| **AM4 500-series** (X570 / B550 / A520) | ASUS (TUF GAMING X570-PLUS, ROG STRIX X570/B550, PRIME X570-PRO) | NCT6798D + asus_ec_sensors enrichment | mainline `nct6775` |
| | MSI **NCT6687D camp** (MAG B550 TOMAHAWK, B550-A PRO, MPG B550 GAMING PLUS / EDGE; the 2021 MPG X570S EDGE MAX WIFI and CARBON MAX WIFI) | NCT6687D (reports `0xd592`), default register map | out-of-tree `Fred78290/nct6687d`, with `nct6683` blacklisted |
| | MSI **NCT6797D camp** (X570-A PRO, MPG X570 GAMING PRO CARBON WIFI, MPG X570 GAMING PLUS / EDGE WIFI, MAG X570 TOMAHAWK WIFI, MEG X570 ACE / UNIFY / GODLIKE, MAG X570S TOMAHAWK / TORPEDO MAX) | NCT6797D (reports `0xd451`) | mainline `nct6775`. **Never load `nct6687d` here** ([chip-ID collision](#the-nct679x-chip-id-collision), brick risk; never `force=1`) |
| | Gigabyte AORUS (X570 AORUS MASTER / PRO / PRO WIFI / ULTRA / XTREME, B550 AORUS MASTER / PRO, B550 VISION D) | IT8688E + IT8792E (dual-chip) | out-of-tree `frankcrawford/it87` |
| | Gigabyte AORUS X570S (X570S AERO G, X570S AORUS MASTER) | IT8689E + IT87952E (dual-chip) | out-of-tree `frankcrawford/it87` |
| | Gigabyte AORUS single-chip (B550M AORUS PRO, B550I AORUS PRO AX) | IT8688E only | out-of-tree `frankcrawford/it87` |
| | ASRock (B550 Steel Legend, physically an NCT6796D-E; B550 Extreme4, B550 PG Velocita, X570 Taichi, X570 Steel Legend) | NCT6798D class (`nct6798`) | mainline `nct6775` |
| | ASRock B550 Taichi (and Razer Edition) | fans on an NCT6683D-class EC; the NCT6798D beside it has no fans wired | in-kernel `nct6683` reads them read-only; `asrock-nct6683` (out-of-tree, lists both boards) for PWM |
| **AM5 600-series** (B650 / X670 / A620) | ASUS (ROG STRIX X670E, ROG CROSSHAIR X670E, TUF GAMING X670E-PLUS, PRIME B650-PLUS) | **NCT6799D(-R)**, reported as `nct6799` ([zeule/asus-ec-sensors #45](https://github.com/zeule/asus-ec-sensors/issues/45); [lm-sensors #416](https://github.com/lm-sensors/lm-sensors/issues/416)) + `asus_ec_sensors` on listed boards | mainline `nct6775` for PWM; `asus_ec_sensors` for sensor enrichment |
| | MSI (MAG B650 TOMAHAWK WIFI, MAG X670E TOMAHAWK WIFI, MPG X670E CARBON WIFI, MPG B650 CARBON WIFI, PRO X670-P WIFI) | NCT6687D, **default** register map, never `msi_alt1` | out-of-tree `Fred78290/nct6687d`, with `nct6683` blacklisted |
| | Gigabyte AORUS (X670E AORUS MASTER, X670E AORUS PRO X) | **IT8689E + IT8792E** dual-chip. The secondary is an IT8792E/IT8795E (hwmon `it8792`), not an IT87952E ([#96](https://github.com/frankcrawford/it87/issues/96) dmesg). On the MASTER, SYS_FAN7_PUMP and SYS_FAN8_PUMP sit on an ITE IT5701 behind the IT8792E ([LibreHardwareMonitor PR #2587](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/pull/2587), Windows; no Linux report yet). Before PR #128, Rev 1 accepted PWM writes with no effect while a normal BIOS curve was active | out-of-tree `frankcrawford/it87`. [PR #128](https://github.com/frankcrawford/it87/pull/128) (merged 2026-08-24) is the driver-side fix, with positive IT8689E reports including Rev 1: update, then verify. See [IT8689E boards](#it8689e-boards) |
| | Gigabyte single-chip (X670 AORUS ELITE AX, X670 / B650 GAMING X AX) | IT8689E only (SIV catalogue) | out-of-tree `frankcrawford/it87` |
| | ASRock AM5 Steel Legend / LiveMixer / Lightning ITX (B650 / B650E / X670E Steel Legend, B650 LiveMixer, A620I / B650I Lightning WiFi), and the B650E PG-ITX WiFi | **NCT6686D only** (manual block diagrams) | in-kernel `nct6683` reads it read-only (some need `force=1`); PWM via `asrock-nct6683` (lists A620I / B650I Lightning WiFi, X670E Steel Legend, B650E Steel Legend WiFi) or `nct6687d` (MSI labels: check the pump header). Test before relying on it |
| | ASRock AM5 Pro RS / PG Lightning / HDV (B650 Pro RS, B650M Pro RS, X670E Pro RS, X670E PG Lightning, A620M Pro RS (WiFi), B650M-HDV/M.2) | NCT6796D-S only, reported as `nct6799` (the B650E PG-ITX WiFi is the exception, above) | mainline `nct6775` |
| | ASRock AM5 Taichi (X670E Taichi, B650E Taichi, and their Lite editions) | NCT6686D + NCT6796D-S (+ Fintek eSPI→LPC bridge) | both drivers; see the X870E Taichi Lite row below |
| **AM5 800-series** (B850 / X870 / B840) | ASUS (X870E / X870 / B850) | **NCT6701D** (`0xd806`), reported as `nct6799`. Fans and voltages read correctly, most temperatures do not ([lm-sensors #542](https://github.com/lm-sensors/lm-sensors/issues/542), [#544](https://github.com/lm-sensors/lm-sensors/issues/544)). `asus_ec_sensors` per board: ProArt X870E-CREATOR WIFI 6.17; ROG STRIX B850-I / X870-I / X870E-E 6.18; X870E-H / X870-F 6.19; B850-E 7.2; ROG CROSSHAIR X870E HERO and X870E-E WIFI7 R2 7.3 | mainline `nct6775`. X870 / X870E boards on the kernel's ASUS list reach the chip through the WMI path from kernel 7.1 (a board missing from the list, such as a newer edition, uses the I/O ports); **no B850 board** is on that list, so B850 goes through the I/O ports. Owners of a TUF GAMING B850-PLUS WIFI and a ROG STRIX B850-F report it binding that way ([#542](https://github.com/lm-sensors/lm-sensors/issues/542), [#544](https://github.com/lm-sensors/lm-sensors/issues/544)); an ACPI conflict can still block another board. One ROG STRIX X870E-E owner measured the firmware switching a header straight back from manual to full speed ([zeule #100](https://github.com/zeule/asus-ec-sensors/issues/100)) |
| | MSI **auto-allowlist** (B840 / B850 / B860 / X870 / X870E / Z890 boards; `nct6687.c::nct6687_msi_alt_boards[]` is the source of truth and keeps growing) | NCT6687D with the alternate "msi_alt1" EC map, enabled automatically for listed boards | out-of-tree `Fred78290/nct6687d`; add `msi_fan_brute_force=1` (with `nct6683` blacklisted) if system-fan writes do not stick |
| | MSI boards of those series NOT on the list (e.g. MAG B850 TOMAHAWK WIFI, the PZ / WHITE / UNIFY-X editions) | NCT6687D, alternate map | `nct6687d` + `fan_config=msi_alt1`, plus `msi_fan_brute_force=1` if needed |
| | Gigabyte X870E AORUS **PRO** (incl. ICE / X3D) / **ELITE X3D** ([#89](https://github.com/frankcrawford/it87/issues/89)) / XTREME AI TOP / B850 AI TOP / X870 AORUS ELITE WIFI7 (incl. ICE) | IT8696E + IT87952E (dual-chip) | out-of-tree `frankcrawford/it87`; current builds work out of the box. The ELITE X3D is owner-confirmed with both chips controllable ([#89](https://github.com/frankcrawford/it87/issues/89)) |
| | Gigabyte 2026 boards, per the it87 SIV catalogue alone: X870 / B850 AORUS ELITE X3D (incl. ICE), X870E EAGLE WIFI7, X870E EAGLE X3D WIFI7, X870E AERO X3D WOOD / DARK WOOD, X870 AORUS TACHYON ICE, X870E AORUS XTREME X3D AI TOP, X870 / B850 AORUS STEALTH (incl. ICE) | IT8696E + IT87952E (each SIV has both stanzas; the secondary carries SYS_FAN5/6_PUMP). No owner's log yet. The X870 EAGLE WIFI7 and the B850M AORUS STEALTH (ICE) have the IT8696E only | out-of-tree `frankcrawford/it87`. All are in the daemon's dual-chip table, so a missing secondary raises the warning |
| | Gigabyte X870E AORUS **ELITE WIFI7** | **IT8696E only** (6 fan headers; [PR #131](https://github.com/frankcrawford/it87/pull/131)) | out-of-tree `frankcrawford/it87` |
| | **Gigabyte X870E AORUS MASTER** | IT8696E + IT87952E, the secondary blocked behind an ITE bridge latched in config mode (answers device-ID `0x8883`) | out-of-tree `frankcrawford/it87` drives the **primary only** (5 of 8 headers) while the bridge is latched. **It is recoverable**: keep `nct6775`/`w83627ehf` from loading, reboot, then a full power cut if needed (2026-09-05). `mmio` is already the driver default and `force_id` does not help. Same nominal pairing as the ELITE X3D above, different outcome, which is why this table is per board and not per family. See the "IT8883" row and [#64](https://github.com/frankcrawford/it87/issues/64) |
| | **Gigabyte X870 AORUS STEALTH ICE** | IT8696E + IT87952E, the secondary reachable only once the eSPI→LPC bridge in front of it is out of config mode | out-of-tree `frankcrawford/it87` drives the **primary only** while the bridge is latched; the secondary comes back after suppressing `nct6775`/`w83627ehf`, a reboot and, if needed, a full power cut. In the daemon's dual-chip table: #81's own thread records its reporter driving `pwmN` on the second chip. `mmio=on` (already the default) and `force_id` are not the remedy; #81's opening post tried both. [#81](https://github.com/frankcrawford/it87/issues/81) · [#64](https://github.com/frankcrawford/it87/issues/64) is the bridge thread |
| | ASRock X870 Nova WiFi | **NCT6796D-S** only (manual block diagram), reported as `nct6799` | mainline `nct6775` |
| | ASRock X870E Nova WiFi | NCT6796D-S + NCT5585D (+ Fintek bridge) | mainline `nct6775` (both chips) |
| | ASRock B850 / X870 Steel Legend WiFi, B850 / X870 Riptide WiFi, B850 / X870 LiveMixer WiFi, B850I Lightning WiFi | **NCT6686D only** (manual block diagrams) | in-kernel `nct6683` read-only; out-of-tree driver for PWM |
| | ASRock B850M Steel Legend WiFi, B850 / B850M Pro RS (WiFi), B850 / B850M Pro-A WiFi, B850 / B850M Challenger WiFi, X870 Pro RS (WiFi), X870 Pro-A WiFi, X870 Challenger WiFi | **NCT6796D-S only** (manual block diagrams), reported as `nct6799`. The B850M Steel Legend WiFi is the Steel Legend that is not an NCT6686D | mainline `nct6775` |
| | **ASRock X870E Taichi Lite: dual-Nuvoton** (also X870E Taichi / White / OCF) | NCT6686D @ 0x0a20 + NCT6796D-S @ 0x0290 (reported as `nct6799`) + Fintek F85227N bridge | `nct6687d` (or read-only `nct6683`) + mainline `nct6775` (the collision detector exempts this pairing). On an X870E Taichi an owner measured CHA_FAN1/2, CPU_FAN2 and AIO_PUMP on the `nct6799` chip and CHA_FAN3/4 on the NCT6686D, where `nct6687d` labels one channel "Pump Fan" ([nct6687d #155](https://github.com/Fred78290/nct6687d/issues/155)). The board has **two pump headers**: AIO_PUMP (`nct6799` pwm4) and W_PUMP, which LibreHardwareMonitor's board map puts on the NCT6686D's first channel, the one `nct6687d` labels "CPU Fan" (not yet measured on Linux). Assign the pump role by hand to whichever header carries a pump |
| **TR4 X399** (Threadripper 1000 / 2000) | Gigabyte (X399 AORUS PRO (incl. -CF) / XTREME / GAMING 7, X399 DESIGNARE EX (incl. -CF)) | **IT8686E + IT8792E** (dual-chip; dmesg on the PRO-CF ([it87 PR #135](https://github.com/frankcrawford/it87/pull/135)) and the GAMING 7 ([PR #141](https://github.com/frankcrawford/it87/pull/141)): IT8686E at `0xa40`, IT8792E/IT8795E at `0xa60`; the SIV catalogue lists all four boards with this pair) | out-of-tree `frankcrawford/it87`, with `ignore_resource_conflict=1` (both PRs needed it). Until PR #141 is merged the GAMING 7 shows 3 of its 7 headers |
| **sTRX4 TRX40** (Threadripper 3000) | Gigabyte (TRX40 AORUS XTREME / MASTER / PRO WIFI, TRX40 DESIGNARE) | **IT8688E + IT8792E** (dual-chip; the it87 fork's `GA-TRX40-AORUS-XTREME.conf` names `it8688-isa-0a40` + `it8792-isa-0a60`; the SIV catalogue lists all four boards with this pair) | out-of-tree `frankcrawford/it87` |
| | ASRock TRX40 Creator | NCT6683D-class EC ([asrock-nct6683 #13](https://github.com/branchmispredictor/asrock-nct6683/pull/13)) | in-kernel `nct6683` read-only; `asrock-nct6683` lists it for PWM (owner-tested, with hand-back to the BIOS) |
| **sTR5 TRX50** (Threadripper 7000 / 9000) | Gigabyte (TRX50 AI TOP, TRX50 AERO D) | **IT8689E + IT87952E** (dual-chip; [it87 #73](https://github.com/frankcrawford/it87/issues/73) `sensors` on the AI TOP: `it8689-isa-0a40` + `it87952-isa-0a60`, the secondary appearing intermittently; the AERO D from the SIV catalogue alone) | out-of-tree `frankcrawford/it87` |

The System State page (`/diagnostics/hardware`) reports the modules actually loaded and
the chips detected; compare this generic table with your own system's output.

## Intel platform → typical chip mapping

The same for Intel LGA1700 (12th–14th Gen Core) and LGA1851 (Core Ultra), plus the
older Gigabyte Z390 / Z490 boards the daemon's dual-chip table enrols. Re-checked
board by board on 2026-09-24. As with the AMD table, every entry is cross-referenced
against a verifiable upstream source (kernel lists, lm-sensors `configs/`,
Fred78290/nct6687d source, the it87 SIV catalogue, ASRock manuals).

| Generation | Typical Vendors | Typical Hwmon Chip(s) | Driver Path |
|---|---|---|---|
| **LGA1151 / LGA1200** (Z390 / Z490 / W480) | Gigabyte Z390 AORUS MASTER (incl. G2 EDITION) / PRO (incl. PRO WIFI) / ULTRA (incl. -CF), Z490 AORUS MASTER, and, per the SIV catalogue alone, Z390 AORUS XTREME (incl. WATERFORCE / 5G), Z490 AORUS MASTER WATERFORCE / PRO AX / ULTRA (incl. G2) / XTREME (incl. WATERFORCE), Z490 VISION D and W480 VISION D | **IT8688E + IT8792E** (dual-chip; the SIV catalogue gives each board an `it8688` and an `it8792` stanza). The Z390 boards' SIVs also share a voltage-only `it8686` stanza (it labels no fan or temperature). No Z390 board has been seen binding an IT8686E, and a Z390 AORUS PRO WIFI reports an IT8688E ([it87 PR #143](https://github.com/frankcrawford/it87/pull/143)); the daemon accepts either as the primary | out-of-tree `frankcrawford/it87` |
| **LGA1700 600-series** (Z690 / B660 / H670) | ASUS (ROG MAXIMUS Z690 FORMULA, ROG STRIX Z690-A GAMING WIFI D4 / Z690-E GAMING WIFI, TUF GAMING Z690-PLUS) | NCT6798D (reports `0xd42b`) + `asus_ec_sensors` enrichment on listed ROG boards | mainline `nct6775` for PWM; `asus_ec_sensors` for sensor enrichment |
| | MSI (MAG Z690 TOMAHAWK WIFI, MPG Z690 EDGE WIFI) | NCT6687D, **default** register map (no `msi_alt1`) | out-of-tree `Fred78290/nct6687d`, with `nct6683` blacklisted |
| | Gigabyte Z690 AORUS PRO / MASTER | **IT8689E + IT87952E** (dual-chip) | out-of-tree `frankcrawford/it87` |
| | ASRock (Z690 Steel Legend, **Z690 Extreme**: upstream lm-sensors config) | NCT6798D class (the Z690 Extreme's physical NCT6796D-E reports as `nct6798-isa-02a0`) | mainline `nct6775` |
| | ASRock Z590 Taichi | NCT6686D | in-kernel `nct6683` read-only (customer ID added in 7.0); out-of-tree driver for PWM |
| **LGA1700 700-series** (Z790 / B760 / H770) | ASUS (ROG MAXIMUS Z790 EXTREME, ROG STRIX Z790-E GAMING WIFI II / Z790-H GAMING WIFI / Z790-I GAMING WIFI, from the kernel `asus_ec_sensors` list; 7.3 adds ROG MAXIMUS Z790 HERO) | NCT6798D + `asus_ec_sensors` enrichment | mainline `nct6775` + sensor enrichment |
| | MSI (MAG Z790 TOMAHAWK WIFI, MPG Z790 EDGE WIFI) | NCT6687D, default register map, as on Z690 | out-of-tree `Fred78290/nct6687d`; no `msi_alt1` |
| | Gigabyte Z790 AORUS MASTER / XTREME / PRO X | IT8689E + IT87952E (dual-chip; the MASTER's secondary sits at `0x0b10`) | out-of-tree `frankcrawford/it87` |
| | Gigabyte Z790 AORUS ELITE / ELITE AX | **IT8689E only** (SIV catalogue) | out-of-tree `frankcrawford/it87` |
| | ASRock Z790 Steel Legend WiFi | NCT6796D-E, reported as `nct6798` | mainline `nct6775` |
| | ASRock Z790 Taichi | **NCT6686D (5 headers) + NCT5585D (3 headers)** (manual block diagram) | NCT5585D: mainline `nct6775` (`nct6798`); NCT6686D: in-kernel `nct6683` read-only, out-of-tree driver for PWM |
| **LGA1851 800-series** (Z890 / B860 / H810) | MSI (MAG/MEG/MPG Z890) | NCT6687D (reports `0xd592`) with the alternate "msi_alt1" EC map (monitoring tools label these boards *NCT6687DR*); **requires `fan_config=msi_alt1`**, set automatically for boards in the driver's `nct6687_msi_alt_boards[]` | out-of-tree `Fred78290/nct6687d` (auto-allowlist) or manual `fan_config=msi_alt1`; several also need `msi_fan_brute_force=1` |
| | ASUS (ROG STRIX Z890 / B860) | **NCT6701D**: by chip ID it binds as `nct6799`; no Linux log for an ASUS Z890 exists yet | mainline `nct6775`. Not on the ASUS WMI access list, and no `asus_ec_sensors` or `asus_wmi_sensors` support |
| | Gigabyte Z890 AORUS MASTER ([it87 #139](https://github.com/frankcrawford/it87/issues/139) dmesg: IT8696E at `0xa40`, IT87952E at `0xb10`; the MASTER AI TOP from the SIV catalogue and the unmerged LibreHardwareMonitor PR #2512), and, per the SIV catalogue alone, Z890 AORUS XTREME AI TOP / PRO ICE / ELITE X ICE / TACHYON ICE / TACHYON DUO X ICE, Z890 AI TOP, Z890 AERO D and W880 AI TOP (all in the daemon's dual-chip table) | **IT8696E + IT87952E** | out-of-tree `frankcrawford/it87` from 2026-10-02 or later: builds from 2026-09-09 to 2026-10-01 can fail to load on these boards (see [ITE](#ite)); otherwise the same dual-chip remediation |
| | Gigabyte Z890 AORUS ELITE WIFI7 (incl. ICE / PLUS / DUO X), B860I AORUS PRO ICE | **IT8696E only** (the B860I: [it87 #138](https://github.com/frankcrawford/it87/issues/138) dmesg) | out-of-tree `frankcrawford/it87` (same build window as above) |
| | ASRock Z890 (Steel Legend, Lightning, Pro-A, Pro RS, Z890I Nova, Z890M Riptide, Nova, Taichi, Taichi Lite) | **NCT6686D** carries the fans; the Nova, Taichi and Taichi Lite add an NCT6796D-E (reported as `nct6798`) with only MOS_FAN1 wired. The **Z890 Taichi OCF** pairs its NCT6686D with a plain NCT6796D (`nct6796`) carrying two fan headers (manual block diagrams) | in-kernel `nct6683` reads the NCT6686D read-only (Z890 Pro-A customer ID since 7.2; others may need `force=1`); PWM via `nct6687d`, or `asrock-nct6683` on the Z890 Nova WiFi |
| | ASRock B860 / B860M Steel Legend WiFi, B860 / B860I Lightning WiFi | **NCT6686D only** (manual block diagrams) | as for the Z890 NCT6686D boards |
| | ASRock B860 Pro RS, B860 / B860M Pro-A (WiFi), B860M Pro RS, B860M-X | plain **NCT6796D only** (manual block diagrams), reported as `nct6796` | mainline `nct6775` |
| | ASRock H810M-X | **NCT5585D** (manual block diagram), reported as `nct6798` | mainline `nct6775` |

Notes:

- The daemon's `/diagnostics/hardware` response includes a `cpu_vendor` field
  (`"Intel"` / `"AMD"` / `""`) read from `/proc/cpuinfo`. The GUI uses it to scope
  Intel-specific quirks: the same chip can ship on Intel and AMD boards with different
  quirks, e.g. the msi_alt1 NCT6687D on MSI Z890 and MSI X870E.
- Intel CPU temperature always comes from the mainline `coretemp` driver (per-core +
  `Package id 0`). It is not a fan-control driver.
- `intel_pch_thermal` registers a sensor-only hwmon device for the PCH temperature;
  it is enrichment, not control.

## Manufacturer quirks

### Gigabyte (ITE chips)

Most Gigabyte boards use ITE IT8686E / IT8688E / IT8689E / IT8696E chips, which
require (or, for the IT8689E on kernel 7.1 or later, still benefit from) the out-of-tree `it87` driver.

**BIOS settings.** On a current driver build usually **none** are needed: the
driver takes each header over from Smart Fan. The rules that do apply:

1. **Never give a BIOS fan curve a 0% point.** The curve runs the fans during
   POST, after the daemon hands a header back, when `it87` unloads, across
   suspend, and whenever the daemon is not running. A 0% point stops the fans,
   pump and CPU included, in exactly those windows. No upstream source recommends
   one.
2. For a 4-pin fan, set the header's **FAN Control Mode** (Smart Fan 5/6) to
   **PWM**. *Fan Control Use Temperature Input* only picks the reference sensor.
   None of the Smart Fan 5 or 6 manuals checked (X570, AMD 600, Intel 600/800 BIOS
   manuals) has a "FAN Control by" item.
3. *Full Speed* in **Fan Speed Control** is a fail-safe, not a fix: the firmware
   runs that fan at 100% whenever it owns it, but on some boards it also locks
   Linux out of the header
   ([#115](https://github.com/frankcrawford/it87/issues/115): "A fixed-speed mode
   rejects `pwm_enable=1`"), and before PR #128 one owner saw Full-Speed fans
   drop to 0% as the module loaded
   ([#79](https://github.com/frankcrawford/it87/issues/79)).

The PWM files are **not** read-only on these chips: `pwmN` and `pwmN_enable` are
0644 in both the fork and mainline. A write to `pwmN` while the header is in
automatic mode returns `EBUSY` by design. What goes wrong on some boards is that
the chip's firmware logic keeps or retakes the fan (extra curve vectors on
IT8689E and IT8688E rev 2, and the SmartFan enable on the IT879x secondaries),
which PR #128 (2026-08-24) addresses.

**MMIO.** The out-of-tree `it87` driver needs MMIO (Memory-Mapped I/O) for fan
control on newer Gigabyte boards. Current builds enable it by default
([PR #95](https://github.com/frankcrawford/it87/pull/95), 2026-03); only builds from
before 2026-03 need `options it87 mmio=on`, and updating is the better fix. MMIO
reaches a secondary chip's extra headers and its fan control; it does not decide
whether a chip is found, which happens over the Super-I/O ports (#139 found both
chips with `mmio=off`). On Intel Z890 / B860 boards, builds from 2026-09-09 to
2026-10-01 have a separate fault, described [above](#ite). One
counter-case: the default *broke* PWM writes on **IT8665E** boards (ASUS AM4
300/400-series and X399-era boards such as the ROG Zenith Extreme; values written were
mangled, 180 stored as about 4,
[issue #106](https://github.com/frankcrawford/it87/issues/106), closed).
[PR #120](https://github.com/frankcrawford/it87/pull/120) (merged 2026-07-22) removes
the MMIO path for that chip, so rebuilding the it87 driver fixes the fan with no
parameter. Builds older than the merge need `options it87 mmio=off`.

#### IT8689E boards

On driver builds before PR #128, some Gigabyte IT8689E boards (Rev 1 especially, e.g.
the X670E AORUS MASTER) accepted manual PWM writes with no effect while a normal BIOS
fan curve was active: the chip's extra vector curves overrode manual mode
([issue #96](https://github.com/frankcrawford/it87/issues/96)). The fork's stopgap for
those builds (its README, 2026-03-30 to 2026-08-24, IT8689E boards only) was a BIOS
curve of PWM 40,40,40,40,40,40,100 at temperatures 0,90,90,90,90,90,90, lowering 90 to
the BIOS maximum where it is capped (one owner's BIOS capped at 65,
[#115](https://github.com/frankcrawford/it87/issues/115)). It reliably restored only
the CPU-fan header.

[PR #128](https://github.com/frankcrawford/it87/pull/128), merged on 2026-08-24, fixes
manual mode for IT8688/IT8689/IT8790/IT8792/IT8795/IT87952, adds the H2RAM extra fan
channels found on high-end boards, and switches the Gigabyte path from WMI to SMI.
Three users reported working IT8689E manual PWM on 2026-08-23, against the pre-merge
head:

| Board | Chip | Result |
|---|---|---|
| Gigabyte Z790 AORUS MASTER rev 1.0, BIOS F19a, kernel 7.1.8 | **IT8689E revision 1** + IT87952E rev 1 | SYS_FAN2 (`pwm3`) duty 30/60/120/180/255 → 0/1227/2368/3183/3276 RPM; previously stuck ~2250 RPM. `pwm3_enable=2` restored firmware control cleanly |
| Gigabyte B650 Eagle AX | IT8689E (single) | Control works, **no BIOS-side tweaks needed** |
| Gigabyte B760M H | IT8689E revision 2 | All 3 PWM headers controllable; previously CPU-fan only. No BIOS adjustments |

Those three tested PR head `429d2b40`, which is not the commit that merged: the
branch was amended to `27319db7`, reworking the Intel H2RAM bridge save/restore
path. Since the merge, a B660M GAMING AC DDR4 (IT8689E rev 1, working after a
reboot) and a B550M DS3H R2 (rev 2,
[#115](https://github.com/frankcrawford/it87/issues/115)) have reported working.
None yet covers a dual-chip IT8689E board or a v2.0 build, so update
the it87 driver, then **verify writes take effect** with Test PWM Control before
relying on control. The earlier [PR #114](https://github.com/frankcrawford/it87/pull/114)
was rejected on 2026-08-25 (superseded by #128); it is not a pending fix.

**Never replace the stopgap with a curve that has a 0% point.** Where a header still
cannot be controlled on a current build, use another header, move the fan to an
external controller such as the OpenFAN controller, or let the BIOS curve drive it.

#### Where a header still cannot be controlled

The fork's README carries a September-2024 note about a "new Gigabyte fan control
chip". It names no boards and no series. The causes found since are board-specific:
the secondary chip's SmartFan enable, the IT8689E / IT8688E rev 2 extra vectors, and,
on high-end boards with more than eight headers, an ITE IT57xx embedded controller
that carries two headers and is reachable only on current builds. Two boards are named
so far: on the X670E AORUS MASTER and the X870E AORUS MASTER X3D (and X3D ICE) the
IT57xx is an IT5701 carrying SYS_FAN7_PUMP and SYS_FAN8_PUMP, per LibreHardwareMonitor
([PR #2587](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/pull/2587),
Windows, unmerged, tested by owners of both boards), which agrees with the it87 board configs. No Linux
reading or control of those two headers has been reported yet. Nothing upstream
supports a family-wide list of affected boards, and control is confirmed on the X570
AORUS PRO ([#99](https://github.com/frankcrawford/it87/issues/99)), B550M DS3H R2
(#115) and B650 EAGLE AX (#128).

### MSI (NCT6687D)

MSI boards from B550 / Intel 600-series on use the NCT6687D, which needs the
out-of-tree `nct6687d` driver for fan control. (MSI AM4 300/400-series boards and
the original 2019 X570 boards use an NCT679x chip and the mainline `nct6775`
instead: never `nct6687` there.)

**Read-only headers are a driver problem, not a BIOS one.** The in-kernel
`nct6683` also binds the NCT6687D, names the device `nct6687` too, and publishes
every `pwmN` read-only on MSI boards. `nct6687d` always makes them writable. So
blacklist `nct6683` and check with `ls -l /sys/class/hwmon/hwmon*/device/driver`.
No BIOS setting such as "Smart Fan Mode" changes this.

**X870/B850 7-point write quirk.** Newer MSI boards (B840 / B850 / B860 / X870 /
X870E / Z890, the alt1 register map) often need all 7 BIOS fan-curve points
written, rather than a single PWM value, before a system fan follows. The
`nct6687d` driver's `msi_fan_brute_force=1` module parameter (upstream marks it
**BETA**) does this. It is a separate, current parameter, not an older-driver
alternative to `fan_config`. It affects system fans only; CPU and pump fans use
standard PWM writes. Before entering manual control the driver snapshots all 7
original curve points and restores them when automatic mode is written, when the
module is unloaded, or when the optional fan-control watchdog expires. Current
builds return `EIO` when a write does not stick, on some boards (e.g. PRO B850M-P
WIFI) even for CPU_FAN, until brute force is enabled.

> **`msi_fan_brute_force=1` requires blacklisting `nct6683`.** Upstream
> states this as a prerequisite: with both loaded, the in-kernel `nct6683`
> and `nct6687` can bind the same chip at once, so readings garble and PWM
> writes fail, commonly with `EIO`
> ([#204](https://github.com/Fred78290/nct6687d/issues/204)). Set all three:
> ```sh
> echo "blacklist nct6683" | sudo tee /etc/modprobe.d/nct6683_blacklist.conf
> echo "options nct6687 msi_fan_brute_force=1" | sudo tee /etc/modprobe.d/nct6687_msi.conf
> echo "nct6687" | sudo tee /etc/modules-load.d/nct6687.conf
> ```
> Then reboot. This sequence resolved
> [issue #202](https://github.com/Fred78290/nct6687d/issues/202) (MSI PRO
> B850M-P WIFI, PWM writes returning `EIO`).

> **Do NOT force `fan_config=msi_alt1` on boards outside the alt1 series.**
> The chip is the same NCT6687D (it reports `0xd592`) on every MSI generation;
> only the B840 / B850 / B860 / X870 / X870E / Z890 boards use the alternate
> EC register layout (monitoring tools label them *NCT6687DR*), and on those
> the driver enables it **automatically** for each board named in
> `nct6687_msi_alt_boards[]`. That list grows, and its entries are full
> DMI names, so a PZ / WHITE / MAX edition can be missing while its sibling is
> listed. Earlier MSI series (**B650 / B660 / X670 / Z690 / Z790**) use the
> *default* mapping and are auto-detected correctly.
> Forcing `msi_alt1` there makes the driver read EC offsets `0x154–0x15E`,
> which read zero on those boards, so **every SYS_FAN reports 0 RPM**
> while CPU_FAN keeps working. Confirm the active mapping with `sudo dmesg`:
> ```
> nct6687 …: active fan config=msi_alt1, SYS_FAN reg_rpm=0x015E/0x015C/0x015A
> ```
> That line is always printed and reveals a stale forced setting at a
> glance. Reference: upstream issue #167 (MSI MPG B650 CARBON WIFI, MS-7D74).

**Some alt1 headers are not exposed.** Under `msi_alt1` the driver reads a fixed
set of fan channels; a header outside it, such as the EZ Conn header (JAF_2) on a MAG
X870 TOMAHAWK WIFI, does not appear under Linux
([#107](https://github.com/Fred78290/nct6687d/issues/107), 2026-09-30). A fan on
such a header stays under BIOS control.

**Other module parameters** (added 2026-08): `fan_mask` (default `0xff`) and
`temp_mask` (default `0x7f`) hide unpopulated channels. Masked channels are
not read from the EC and numbering is never renumbered to fill gaps, so
existing `sensors.d` / `fancontrol` configuration keeps referring to the
same hardware.

**On Arch, if your MSI fans disappeared after an August 2026 driver update,** reinstall
the AUR package `nct6687d-dkms-git`. Its `r225.4864fd6-1` release shipped the upstream Kbuild rework,
which moved the module install path and left no module to load
([issue #198](https://github.com/Fred78290/nct6687d/issues/198)); the package's rebuild on
2026-08-22 (pkgrel `-2`) fixed it. On other distributions, rebuild the driver from current
source ([Driver Setup](../manual/driver-setup.md#updating-the-driver)). Kernel 7.2 / GCC 16.2 build failures from the same
window are fixed upstream too (issues #199, #201).

Reference: https://github.com/Fred78290/nct6687d

### ASUS (Nuvoton NCT679x / NCT6701D)

ASUS AM4 500-series and Intel 600/700-series boards use an NCT6798D; AM5
600-series boards an NCT6799D(-R); AM5 800-series and Z890 / B860 boards an
NCT6701D that mainline binds as `nct6799`. ASUS AM4 300/400-series boards are
ITE (IT8665E): see the `it87` notes above.

**ACPI conflicts.** ASUS boards may have ACPI OpRegion conflicts on the I/O ports
the `nct6775` driver uses (commonly 0x0290–0x0299). On many boards no workaround is
needed: `nct6775` reaches the chip through an ASUS WMI method instead of the ports,
for boards on its exact-name lists. As of 7.3 there is no B850, B840, B860 or Z890
board on them. Where the bind still fails, add the kernel parameter
`acpi_enforce_resources=lax` (see [Setting a driver option or a kernel
parameter](#setting-a-driver-option-or-a-kernel-parameter)). `nct6775` has no
driver-local escape (its only module parameters are `force_id` and `fan_debounce`),
so the system-wide parameter is the only option. No vendor's BIOS has an "ACPI
Hardware Monitor" item to disable, despite advice that says so, and the ACPI device
that claims the ports on ASUS boards, `AMW0`, also hosts the WMI access path.

**BIOS.** No setting makes the `nct6775` PWM files writable: they already are,
and the daemon switches each header to manual itself. *Q-Fan Tuning* is a
one-shot calibration; the mode item is *&lt;header&gt; Q-Fan Control* (Auto Detect /
DC Mode / PWM Mode, to match the fan) and the curve item *&lt;header&gt; Fan Profile*.

The daemon's diagnostics endpoint detects these conflicts by parsing
`/proc/ioports` and reports them on the Hardware page.

### ASRock

ASRock boards mix chips. Most AM5 boards carry an NCT6796D-S (mainline `nct6775`,
reported as `nct6799`). Many boards also, or only, carry an NCT6686D (or an
NCT6683D-class EC on the B550 Taichi) that holds some or all of the fan headers. The
in-kernel `nct6683` driver provides **monitoring** (temperatures, RPMs) for that chip,
but publishes the PWM files **read-only** on every board except Mitac OEM systems,
and has no `pwmN_enable`. So writes are refused, not accepted and ignored. Which chip
carries which header is per board: see the per-generation tables above.

**An NCT6686D with no driver bound is pointed at the in-kernel `nct6683`**, by the
daemon's load recommendation and by the GUI's chip guidance alike. That gets you
monitoring without an out-of-tree module; for fan control, pick one of the drivers
below for your board. In-kernel PWM writes on ASRock boards await upstream work: Johan
Dahlin's series
["hwmon: (nct6683) Fan control for ASRock B850 Steel Legend WiFi"](https://ratatoskr.run/lkml/2026/08/17457921/t)
(posted 2026-08-25: write retries, `pwmN_enable`, restore on unload, and write
enable for that one board) drew change requests from the hwmon maintainer
(2026-08-28 and 2026-09-17) and is not merged (checked 2026-10-15). Even once merged
it enables writes per board, not for every NCT6686D. A similar series for MSI's
NCT6687D-R boards (Hamza Mahfooz, 2026-10-04) is not merged either; until one lands,
the in-kernel `nct6683` is read-only on every released kernel.

**Alternative drivers for ASRock NCT668x boards:**

| Driver | Repository | Supported boards |
|---|---|---|
| `asrock-nct6683` | https://github.com/branchmispredictor/asrock-nct6683 | Enables PWM on the boards it lists by exact DMI name: B550 Taichi, B550 Taichi Razer Edition, A620I Lightning WiFi, B650I Lightning WiFi, X570 Creator, X670E Steel Legend, B650E Steel Legend WiFi, TRX40 Creator, Z370M Pro4, Z890 Nova WiFi (the table in its `nct6683.c`, as of 2026-10-07; its README lists fewer). Built from source; there is no Arch (AUR) package |
| `nct6687d` | https://github.com/Fred78290/nct6687d | Several ASRock NCT6686D boards (e.g. B650 LiveMixer, X870E Taichi Lite). Uses MSI's register map and **MSI's fan labels**, so verify which header is which before trusting a "Pump Fan" or "CPU Fan" label. On a B850I Lightning WiFi one developer reports the direct PWM registers have no effect ([PR #217](https://github.com/Fred78290/nct6687d/pull/217), unmerged): test before relying on it. Install steps per distribution: [Driver Setup](../manual/driver-setup.md#step-3--install-the-driver) |
| `nct6686d` | https://github.com/s25g5d4/nct6686d | Tested by its author only on the A620I Lightning WiFi (kernel 6.5); a 2026-03 fix makes it build on 6.11 and later. Built from source; there is no Arch (AUR) package |

Older ASRock boards with NCT677x/NCT679x chips generally work with the
mainline `nct6775` driver.

## AMD GPU fan control

### Requirements

- **RDNA3+ (RX 7000 / RX 9000 series):** Fan control uses the PMFW `fan_curve`
  sysfs interface. It needs the `amdgpu.ppfeaturemask` kernel parameter with
  bit 14 set (e.g. `amdgpu.ppfeaturemask=0xfff7ffff`).
- **RDNA2 and older (RX 6000, RX 5000, Vega, Polaris):** These expose the
  traditional `pwm1_enable=1` + `pwm1` control path. The daemon uses it for
  **Test GPU Fan Control** and **Restore GPU Fan to Automatic** only: no
  profile drives these fans, and their firmware curve stays in charge.
  RX 6000 = RDNA2, RX 5000 = RDNA1; RX 7000 is the first generation where the
  legacy path was removed in favour of PMFW `fan_curve`.
  AMD GPU family map: [AMD `amdgpu.ids` (libdrm)](https://gitlab.freedesktop.org/mesa/drm/-/blob/main/data/amdgpu.ids),
  cross-checked against the kernel
  [`amd_shared.h`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/amd/include/amd_shared.h)
  family constants.

### ppfeaturemask

The `ppfeaturemask` parameter enables AMD GPU power management features.
Bit 14 (`0x4000`) is `PP_OVERDRIVE_MASK` in the kernel header
[`amd_shared.h`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/amd/include/amd_shared.h);
it enables OverDrive, which is what exposes the PMFW fan-curve sysfs tree.

To check the current value:
```bash
cat /sys/module/amdgpu/parameters/ppfeaturemask
```

To enable OverDrive, add this kernel parameter and reboot
(see [Setting a driver option or a kernel parameter](#setting-a-driver-option-or-a-kernel-parameter)):
```
amdgpu.ppfeaturemask=0xfff7ffff
```

That is the kernel's default mask, `0xfff7bfff` in
[`amdgpu_drv.c`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/amd/amdgpu/amdgpu_drv.c)
("OverDrive(bit 14) disabled by default / GFX DCS(bit 19) disabled by default"), with
bit 14 added, and the value AMD's engineers give
([drm/amd #5514](https://gitlab.freedesktop.org/drm/amd/-/issues/5514)). Any mask with
bit 14 set works. The `0xffffffff` that many guides use also sets bit 19, a feature the
kernel leaves off by default; the
[Arch Wiki](https://wiki.archlinux.org/title/AMDGPU#Boot_parameter) warns that setting
all 32 bits "may enable unstable features". On RX 7000 and RX 9000 cards bit 19 is not
used, so a `0xffffffff` you already set does no harm there and need not be changed.

From Linux 6.13, enabling OverDrive taints the kernel and logs
`amdgpu: Overdrive is enabled, please disable it before reporting any bugs unrelated to overdrive.`
([commit b472b8d829c1](https://git.kernel.org/torvalds/c/b472b8d829c1562c5597c1f212957b6b2696d40e)).
That message is expected with any mask that sets bit 14. If you report a kernel bug,
say that the parameter is set.

The daemon's hardware diagnostics endpoint reports the current
ppfeaturemask value and whether bit 14 is set.

### Navi 48 cards (RX 9070 / Radeon AI PRO R9700)

The kernel log's SMU interface-version message (driver `0x2E`, firmware `0x32` or
`0x33`) appears on **every** Navi 48 card, the RX 9070 XT included, and is not a fault:
the firmware is designed to be backward compatible, and kernel 7.0 removed the message
because ["it just leads to user confusion"](https://git.kernel.org/torvalds/c/e471627d56272a791972f25e467348b611c31713).
`pwm1` is read-only on every RDNA4 card by driver design; control goes through the PMFW
`fan_curve`, which works on at least some R9700s. Separately, a few R9700 owners report
the fan not responding under load, one at 109 °C
([ROCm #6101](https://github.com/ROCm/ROCm/issues/6101)). Those reports are per-unit
and unresolved; AMD advised an RMA for the original reporter's card. If an R9700's fan
does not follow a curve, return it to automatic (**Restore GPU Fan to Automatic**),
compare its RPM under load, and consider a warranty claim. No pending kernel change
addresses it.

**RX 9000 fans at idle.** On at least one RX 9070 XT the firmware stops the fan while
the hotspot is below about 50 °C, even with a curve active and zero-RPM idle turned off;
above that the fan follows the curve exactly
([drm/amd #5905](https://gitlab.freedesktop.org/drm/amd/-/issues/5905)). AMD has written a
`fan_zero_rpm_stop_temperature` control for these cards, which its maintainer expects in
Linux 7.4. Some RX 9070 XT owners also see `fan1_input` read 0 RPM while the fan spins
([drm/amd #5514](https://gitlab.freedesktop.org/drm/amd/-/issues/5514), open). A stopped
or 0 RPM fan on an idle RX 9000 card is therefore not a fault by itself: check it again
with the GPU under load.

**Kernel version for RX 9000 fan curves.** Use Linux 6.18.32, 7.0.9, 7.1 or later.
Earlier kernels mishandle a firmware flag on the fan-curve and fan-minimum paths, which
AMD's fix says "leads to disabled thermal monitoring and temperature boundary validation"
([commit 504f0098ebd0](https://git.kernel.org/torvalds/c/504f0098ebd074ac8c0ce3471795d79f68e3d265)).

## Intel discrete GPU (Arc) monitoring

Intel **discrete** GPUs (Arc) are supported for **read-only** monitoring
only: temperatures and fan RPM.

### Drivers

| GPU family | Kernel driver | Hwmon chip name |
|---|---|---|
| Arc B-series "Battlemage" (and later Xe2) | `xe` | `xe` |
| Arc A-series "Alchemist" | `i915` | `i915` |

Both drivers register their hwmon node **only for discrete GPUs** (the
kernel gates it on `IS_DGFX(...)` in
[`drivers/gpu/drm/xe/xe_hwmon.c`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/xe/xe_hwmon.c)
and the equivalent `i915_hwmon.c`). The daemon therefore treats an hwmon
chip named `xe` or `i915` as unambiguously a discrete Intel GPU.
**Integrated** Intel graphics (Xe / UHD) expose no such hwmon node and are
not affected.

### Supported (read-only)

- **Temperature monitoring:** surfaced as sensor source `"intel_gpu"`,
  kind `gpu_temp`. See the [Sensor Interpretation Guide](20_Sensor_Interpretation_Guide.md#xe--i915-intel-discrete-gpu-driver)
  for the per-index meaning of the `xe` / `i915` channels.
- **Fan RPM monitoring:** the `xe` driver exposes `fan1_input`,
  `fan2_input`, `fan3_input` (all read-only RPM); the GUI surfaces one fan
  entity per GPU (`fan1`) as fan ID `intel_gpu:{pci_bdf}`. `i915` fan RPM
  reporting (`fan1_input`) was added in Linux **6.12**.

### Not supported: fan control

There is **no user-controllable fan interface** for Intel GPUs in a mainline
kernel (checked at 7.3-rc7). Neither `xe` nor `i915` exposes a `pwm` attribute or
a fan-write callback. Intel GPU fan speed is managed autonomously by on-card
firmware (fan reads go through a firmware "pcode" mailbox). linux-firmware carries
one fan-control blob, `xe/fan_control_8086_e20b_8086_1100.bin`; the kernel names the
file after the card's PCI subsystem IDs, so it applies to Intel's own Arc B580 board
(subsystem `8086:1100`) only. On a stock kernel userspace cannot override the
firmware. This is a kernel and firmware fact, not a daemon limitation.

Intel has posted kernel patches that add fan control to `xe`
([series 168027](https://patchwork.freedesktop.org/series/168027/), "Add fan control
support"), adding writable `pwm1`–`pwm3` and `pwm1_enable`–`pwm3_enable`. They were
under review, not merged, on 2026-10-15
([Intel on compute-runtime #885](https://github.com/intel/compute-runtime/issues/885)).
Some users run kernels patched with them, and tools such as LACT 0.10.1 drive those
controls. The daemon does not yet treat them as a GPU fan: on such a kernel it lists
the Arc fan as a motherboard header on chip `xe`. Do not add that header to a profile.

Consequently the daemon always reports `fan_control_method` of `"read_only"`
(fan present) or `"none"`. Intel GPU fans are never writable and are never
offered as controllable curve members. The GPU's **temperatures** remain
usable as curve *sensors* to drive other fans.

There is no Intel kernel parameter to enable fan control; `amdgpu.ppfeaturemask` is
AMD-only.

### Model names

A card is named when the PCI ID database
([`pci.ids`](https://pci-ids.ucw.cz/), version 2026.10.14) names its device ID
(vendor `0x8086`):

| Device ID | Name |
|---|---|
| `0xE20B` | Arc B580 |
| `0xE20C` | Arc B570 |
| `0xE211` | Arc Pro B60 |
| `0xE212` | Arc Pro B50 |
| `0xE222` | Arc Pro B65 |
| `0xE223` | Arc Pro B70 |
| `0x56A0` | Arc A770 |
| `0x56A1` | Arc A750 |
| `0x56A2` | Arc A580 |
| `0x56A5` | Arc A380 |
| `0x56A6` | Arc A310 |
| `0x56B0` | Arc Pro A30M |
| `0x56B1` | Arc Pro A40/A50 |
| `0x56B2` | Arc Pro A60M |
| `0x56B3` | Arc Pro A60 |

Every other Intel discrete GPU, including the Battlemage IDs `pci.ids` lists only as
"Intel Graphics", displays as the generic "Intel D-GPU".

### Sources

- [intel-xe-hwmon sysfs ABI](https://www.kernel.org/doc/Documentation/ABI/testing/sysfs-driver-intel-xe-hwmon)
- [intel-i915-hwmon sysfs ABI](https://www.kernel.org/doc/Documentation/ABI/testing/sysfs-driver-intel-i915-hwmon)
- [`drivers/gpu/drm/xe/xe_hwmon.c`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/xe/xe_hwmon.c)
- [`include/drm/intel/pciids.h`](https://github.com/torvalds/linux/blob/master/include/drm/intel/pciids.h)
- [`pci.ids`](https://pci-ids.ucw.cz/v2.2/pci.ids): the model names above
- [linux-firmware `WHENCE`](https://git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git/tree/WHENCE) and [`xe_late_bind_fw.c`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/xe/xe_late_bind_fw.c): the one fan-control blob and its subsystem-ID file name

## NVIDIA discrete GPU monitoring

NVIDIA **discrete** GPUs are supported for **read-only** monitoring only:
temperatures and fan telemetry. The NVML path is **experimental**: built and
tested against a fake library, not yet verified on NVIDIA hardware.

### Drivers

NVIDIA GPUs live in one of two mutually-exclusive driver worlds:

| Driver | Telemetry path | `driver` field | `chip_name` |
|---|---|---|---|
| `nouveau` (open) | Kernel DRM driver with an hwmon node (`temp1`, and on some cards fan RPM) on cards **older than Turing** only; see below | `"nouveau"` | `nouveau` |
| Proprietary NVIDIA | No sysfs hwmon; temperature + the driver's fan **duty %** and RPM via the NVML userspace library (`libnvidia-ml.so.1`) | `"nvidia"` | `nvml` |

**`nouveau` publishes no sensors on Turing and newer cards.** There it runs NVIDIA's own
GPU firmware (GSP), and with GSP its thermal code is not created (`gp100_therm_new`
returns `-ENODEV`; the Ampere, Ada and Blackwell chipset tables have no thermal, voltage
or current-sense unit at all), so the driver registers no hwmon device. GSP is the only
path on Ada and later and the default on Turing and Ampere since Linux 6.18
([commit e0ed674acbac](https://git.kernel.org/torvalds/c/e0ed674acbac5635494fc7b278abc9505eaa8e71)),
see [`nouveau_hwmon.c`](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/nouveau/nouveau_hwmon.c).
With `nouveau`, Ventulus therefore sees a Turing-or-newer card not at all. The opt-in
NVML path below, with the proprietary driver, is the only way to monitor one.

The `driver` field on the capability/diagnostics is always the **kernel module
name** (`"nouveau"`/`"nvidia"`), never the `nvml` library. The proprietary NVML
backend is **opt-in and off by default**. Turning it on takes four steps, and
all of them are needed:

1. Have the NVIDIA userspace package that matches your driver installed; it provides
   `libnvidia-ml.so.1`. If the proprietary driver already works, it is. On Arch that is
   `nvidia-utils` for the current driver (Turing and newer), or
   [`nvidia-580xx-utils`](https://aur.archlinux.org/packages/nvidia-580xx-utils) from the
   AUR for Maxwell, Pascal and Volta cards, which the 590 driver dropped
   ([Arch news, 2025-12-20](https://archlinux.org/news/nvidia-590-driver-drops-pascal-support-main-packages-switch-to-open-kernel-modules/)).
   On Debian, Ubuntu and Fedora it comes with the distribution's (on Fedora, RPM
   Fusion's) NVIDIA driver packages.
2. Set the flag in `/etc/ventulus/daemon.toml` (or with the **NVIDIA telemetry**
   switch under Settings → Daemon Configuration):
   ```toml
   [detection]
   enable_nvidia_telemetry = true
   ```
3. Install the drop-in that lets the daemon reach `/dev/nvidia*`. The package ships
   it as an example only, not installed:
   ```bash
   sudo install -Dm644 \
     /usr/share/doc/ventulusd/nvidia-telemetry.conf.example \
     /etc/systemd/system/ventulusd.service.d/nvidia-telemetry.conf
   ```
4. `sudo systemctl daemon-reload && sudo systemctl restart ventulusd`.

With the flag but no drop-in, NVML cannot open the device nodes: the daemon logs
one line and shows no NVIDIA telemetry.

### Supported (read-only)

- **Temperature monitoring:** sensor source `"nvidia_gpu"`, kind `gpu_temp`
  (chip name `nouveau` or `nvml`).
- **Fan telemetry:** one fan entity per GPU as `nvidia_gpu:{pci_bdf}`. RPM when
  the card exposes it; the NVML path also reports a **fan duty %** (`duty_pct`, which
  may exceed 100: NVML expresses it as a % of the maximum noise tolerance), distinct
  from a commanded PWM (there is none). NVML's duty and RPM are what NVIDIA's header
  calls the **intended** fan speed, not a tachometer reading: "If the fan is physically
  blocked and unable to spin, the output will not match the actual fan speed"
  ([`nvml.h`](https://github.com/NVIDIA/go-nvml/blob/main/gen/nvml/nvml.h), NVIDIA's copy).
  A stalled NVIDIA fan does not show as one.

### Not supported: fan control

There is **no user-controllable fan interface** through this daemon. On some cards
older than Turing `nouveau` *does* expose a writable `pwm1`, but the daemon
deliberately **excludes** it from discovery for safety (the GPU subsystem owns it, as with AMD); the NVML backend is
telemetry-only (no fan-write symbol is bound). The daemon always reports
`fan_control_method` `"read_only"` (fan present) or `"none"`. NVIDIA GPU fans are
never writable and never offered as controllable curve members; the GPU's
**temperatures** remain usable as curve *sensors*. NVML does have a privileged fan-write
path (`nvmlDeviceSetFanSpeed_v2`, Maxwell and newer), which tools such as LACT and
CoolerControl use; Ventulus does not bind it. Fan writes wait until they can be
validated on NVIDIA hardware.

### Model names

`model_name` and `driver_version` are available only from the proprietary NVML
driver; the open `nouveau` leg shows the generic "NVIDIA D-GPU" label.

## Liquid cooling (AIO) over hwmon

The daemon supports **hwmon-attached** liquid coolers. Coolers ride the ordinary hwmon
path: the daemon classifies coolant sensors as `coolant_temp`, flags pump/fan headers
`is_aio`, and reports a dynamic `aio_hwmon` capability. **Pump writability differs per
driver**: the GUI reflects the kernel's per-channel `is_writable` and never fakes
control.

**A coolant sensor is a safety input**: at or above the coolant limit (default 60 °C,
settable 40–70) the daemon forces every fan and pump to 100 %. **Pump floors:** the
daemon never drives a pump below 30 %, and never below 70 % on a motherboard header the
kernel reports in DC (voltage) mode (`pwmN_mode` = 0, published by `nct6775` and a few
older chips), because a voltage-driven pump stalls much higher in its range. The it87
driver publishes no `pwmN_mode`, so a pump on an it87 header keeps 30 %. Where the table
below says 30 %, a pump on a DC-mode header gets 70 %. The full rules are in
[What keeps your machine safe](../manual/understanding-fan-control.md#what-keeps-your-machine-safe).

| Driver (hwmon `name`) | Devices | Coolant temp | Pump/fan control |
|---|---|---|---|
| `nzxt-kraken3` (`x53`, `z53`, `kraken2023`, `kraken2023elite`; `kraken2024elite` from kernel 7.3) | NZXT Kraken X/Z-series, 2023, 2023 Elite, 2024 Elite | yes | **writable**: `pwm1` pump (+ `pwm2` fan on Z/2023/2024). The driver labels channel 1 "Pump speed", which the daemon's pump rule matches on every model. Every model, the 2024 Elite included, is on the daemon's cooler list, so each is flagged as an AIO and its radiator fan gets the 30 % pump/CPU floor that every fan channel on a liquid cooler gets |
| `nzxt-kraken2` (`kraken2`) | older NZXT Kraken | yes | **monitor-only** (no `pwm` exposed). Note `fan1_input` is the fan and `fan2_input` the pump, the reverse of kraken3 |
| `aquacomputer_d5next` (`d5next`, `highflownext`, `leakshield`, `octo`, `quadro`, `aquaero`, …) | Aquacomputer D5 Next pump; Octo / Quadro / Aquaero fan controllers; flow / leak devices | yes on the liquid devices (labelled channel) | **D5 Next: `pwm1` is the pump duty and `pwm2` the fan, both writable** (`d5next_ctrl_fan_offsets[] = { 0x97, 0x42 } /* Pump and fan speed */`, since 6.0). The daemon maps channel 1 of a cooler chip to the pump role, so the pump floor applies. Octo (`pwm1`–`8`), Quadro and Aquaero (`pwm1`–`4`) are writable fan controllers, not flagged AIO; flow / leak devices expose no `pwm` |
| `asus_rog_ryujin` (`rog_ryujin`) | ASUS ROG RYUJIN II / III AIOs | yes (`temp1` labelled "Coolant temp") | **writable**: `pwm1` pump, `pwm2` internal fan, `pwm3` controller fans (RYUJIN II only). Channel 1 is labelled "Pump speed", which the daemon's pump rule matches; not flagged as an AIO. RYUJIN III EXTREME / EVA / WHITE editions added in 7.3 |
| `gigabyte_waterforce` (`waterforce`) | Gigabyte AORUS WATERFORCE X 240 / 280 / 360 | yes | **monitor-only**: fan, pump and coolant readings, all read-only (since 6.8) |
| `arctic_fan_controller` (`arctic_fan`) | ARCTIC Fan Controller (10 channels), kernel 7.2+ | no | **writable, with a driver hazard the daemon works around.** There is no `pwm_enable`, and every command the driver sends carries all ten channels. On 7.2 and 7.3 its duty cache starts at 0 at probe and after resume, so **the first write to one channel would send 0% to the other nine** until each has been written, and reading `pwmN` back returns that cache, not the device. The daemon first sets every channel still holding such a 0 to 100%, unless the daemon itself last set that channel to 0 (a curve at 0%, a zero-RPM fan) for the profile still controlling it, and does so before the write that would send it. A channel a profile switch or deactivation drops is left at its last duty or the exit floor, whichever is higher, and a 0 the old profile chose no longer counts. So a profile that controls only some channels leaves the rest at full speed instead of stopping them. It does this again by itself after a resume. The first report of each batch still sends 0 to the channels not yet reached, briefly, for as long as the batch takes (the driver waits up to 1 s for the device to acknowledge each write). If the device stops answering, the daemon stops at the first write that fails and logs one warning, then sets the remaining channels straight after the next write the device accepts. To keep uncontrolled fans quiet, control all ten channels. A change queued for kernel 7.4 starts the cache at 40% instead, and the daemon leaves that alone |
| `corsair-cpro` (`corsaircpro`), `nzxt-smart2` (`nzxtsmart2`) | Commander Pro / RGB & Fan hubs | no (probes are generic) | writable fans, **not** flagged AIO (fan hubs, not coolers). A Commander Pro `pwmN` read returns an error unless that channel was set to a fixed duty |
| USB-only (much Corsair iCUE/Commander Core, some NZXT) | — | — | **out of scope**: no mainline hwmon driver; the daemon never opens USB-HID |

For a coolant sensor the conservative auto-classifier misses, right-click it in the
Overview page's sensor table → **Treat as coolant**. That changes how the GUI shows it,
not what the daemon treats as a safety input. To confirm that writes take effect, run
Test PWM Control (`POST /hwmon/{id}/verify`).

## ACPI resource conflicts

Some BIOS implementations claim I/O port ranges used by Super I/O chips
via ACPI OpRegions. When this happens, the kernel refuses to let the hwmon
driver bind to those ports, even though the ACPI claim is cosmetic (the
BIOS firmware doesn't actively use the ports at runtime).

Super I/O windows such a claim can overlap:
- `0x0290–0x0299`: Nuvoton NCT6775
- `0x0290–0x029F`: ITE IT87
- `0x04E0–0x04EF`: Nuvoton NCT6775 (secondary)
- `0x0A20–0x0A2F`: ITE IT87 (alternate), or the Nuvoton NCT668x EC on MSI and ASRock
  boards (`nct6683`, `nct6687`, `nct6686`)
- `0x0A40–0x0A4F`: ITE IT87 (secondary dual-chip)
- `0x0A60–0x0A6F`: ITE IT87 (secondary dual-chip)
- `0x0B10–0x0B1F`: ITE IT87952E (secondary on the Z790 AORUS MASTER)

Ventulus cannot detect a conflict for you. The kernel never lists an ACPI OpRegion in
`/proc/ioports`; it reports the conflict only in the kernel log, which the daemon's
sandbox cannot read. Check the log yourself:

```bash
sudo dmesg | grep -i "conflicts with OpRegion"
```

A hit reads `ACPI Warning: SystemIO range 0x…-0x… conflicts with OpRegion …`, usually
followed by `ACPI: OSL: Resource conflict; ACPI support missing from driver?`.

**Fix options:**
1. **Preferred (driver-local, it87 only):** the driver option
   `options it87 ignore_resource_conflict=1`, set in `/etc/modprobe.d/it87.conf`. See
   [Setting a driver option or a kernel parameter](#setting-a-driver-option-or-a-kernel-parameter).
   The kernel doc warns that it "is inherently risky since it means that both ACPI and
   this driver may access the chip at the same time", which can cause race conditions
   and, at worst, unexpected reboots. It exists because a system-wide
   `acpi_enforce_resources=lax` "can result in boot failures on some systems".
2. **System-wide fallback:** the kernel parameter `acpi_enforce_resources=lax` (same
   section). It can stop some systems booting, so use it only when the first option is
   not available. It is the only kernel-side remedy for `nct6775` and `nct6687`, which
   have no driver-local option.
3. **nct6775 on ASUS boards (kernel ≥ 5.16):** the driver can read the chip through an
   ASUS WMI access path (`access_asuswmi`) that sidesteps the ACPI Super-I/O port
   reservation on supported ASUS boards, so no parameter is needed there. This is a
   WMI sensor-read path, not a general "ACPI mutex" lock; the separately proposed
   ACPI-mutex patch was never merged upstream. The mechanism is in
   [`drivers/hwmon/nct6775-platform.c`](https://github.com/torvalds/linux/blob/master/drivers/hwmon/nct6775-platform.c):
   see `enum sensor_access` (`access_direct` / `access_asuswmi`) and the
   `asus_wmi_boards[]` allowlist of supported boards. The user-facing
   [nct6775 hwmon doc](https://docs.kernel.org/hwmon/nct6775.html) covers the
   driver's sensor schema but not this access path.

## Setting a driver option or a kernel parameter

This page names options in two forms. Each needs a file, and each needs the module
reloaded or the machine rebooted before it does anything.

**A driver option**, written `options it87 mmio=off`, `options nct6683 force=1`,
`options it87 ignore_resource_conflict=1`:

1. Put the line in a file named after the module, for example
   `echo 'options it87 ignore_resource_conflict=1' | sudo tee /etc/modprobe.d/it87.conf`.
   The option is read each time the module loads, so it lasts across reboots.
2. Apply it: reboot, or reload the module now with
   `sudo modprobe -r it87 && sudo modprobe it87`. If you added the module to your
   initramfs, also run `sudo mkinitcpio -P`, or the copy loaded at boot keeps the old
   settings.
3. Restart the daemon so it adopts the driver's fan headers:
   `sudo systemctl restart ventulusd`. The same applies to any PWM driver
   you load, reload or update while the daemon is running: until the restart, its
   headers can be seen but not controlled.

Typing the option on the command line (`sudo modprobe it87 ignore_resource_conflict=1`)
works for this boot only. The daemon package asks for `it87` and `nct6775` at every boot
through `/etc/modules-load.d/ventulus.conf`, and without the file above that load
has no option, so the problem returns on the next boot. Likewise, installing or
updating a DKMS driver does not replace the copy already loaded: reload it or reboot.

**A kernel parameter**, written `amdgpu.ppfeaturemask=0xfff7ffff` or
`acpi_enforce_resources=lax`, goes on the kernel command line through your
bootloader's configuration, then takes effect at the next boot. The manual's Driver
Setup page has the steps for GRUB, systemd-boot, rEFInd and Limine
([Driver Setup § AMD GPU prerequisite](../manual/driver-setup.md#amd-gpu-fan-control-prerequisite-rdna3)).
After rebooting, `cat /proc/cmdline` shows whether it took.

## Kernel module loading

The daemon package ships a module load file, `/etc/modules-load.d/ventulus.conf`,
which loads `nct6775`, `it87`, `w83627ehf` and `drivetemp` at boot. The daemon reads
`/proc/modules` to tell which modules are loaded, and the GUI's Hardware page shows
its answer.

On a Gigabyte board the package's **Super-I/O guard** keeps `nct6775` and
`w83627ehf` from loading, although that file lists them: Gigabyte boards use ITE chips,
which those drivers cannot bind, and their probe can latch the bridge in front of a
second chip. `sudo journalctl -b -t ventulus-superio-guard` logs each module it
declines. How it decides, and how to turn it off, is in the daemon's
[User Guide](https://github.com/Plan-B-Development/ventulusd/blob/main/docs/USER_GUIDE.md#hardware-sensor-modules).

## Thermal safety

The daemon's safety rules do not depend on the board or driver: a CPU at its trip
point (105 °C, or higher where the CPU reports a higher ceiling) or coolant at its limit
forces every writable fan and pump to 100 %, and a CPU with no fresh reading holds the
active profile's fans at 40 % or more. Every forced duty is a floor over the profile's
output, so it can only raise a fan. GPU fans are outside these rules: the GPU firmware
protects itself. The hardware diagnostics response reports the current state.

[What keeps your machine safe](../manual/understanding-fan-control.md#what-keeps-your-machine-safe)
explains the rules; the daemon's
[User Guide § Safety](https://github.com/Plan-B-Development/ventulusd/blob/main/docs/USER_GUIDE.md#safety)
gives the exact thresholds.

## Known kernel-version regressions

The daemon ships a curated catalogue (`hwmon/kernel_warnings.rs`) that matches the
running kernel against published amdgpu regressions and reports matches in
`GET /capabilities` (`devices.amd_gpu.kernel_warnings`). Every AMD GPU in the machine
is checked, an integrated one beside a discrete card included, and the message names
the affected cards. The GUI raises a popup when a high- or critical-severity warning
fires, until you choose **Don't show again**, and lists every match on the System
State page.

Currently catalogued:

| `id` | Affected kernels | Affected hardware | Severity | Symptom |
|---|---|---|---|---|
| `rdna_mes_hang_drm_amd_4765` | 6.18.0–6.18.6, and 6.17.9–6.17.13 | RDNA3, RDNA3.5 and RDNA4 GPUs: RX 7000 / RX 9000, Radeon Pro W7000 and AI PRO, and the RDNA3 / RDNA3.5 integrated GPUs (780M, 890M, 8060S …) | Critical | A change that entered 6.18 made evicting a process on a MES GPU suspend the whole MES scheduler. That also stops the kernel's own queues, so a compute job running alongside a 3D workload can time out and hang the GPU ([drm/amd #4765](https://gitlab.freedesktop.org/drm/amd/-/issues/4765)). The change was backported into 6.17.9, but the fix never was, and 6.17 is end-of-life. **Fixed in 6.18.7 and 6.19.0** by `3fd20580b96a` ([ChangeLog-6.18.7](https://cdn.kernel.org/pub/linux/kernel/v6.x/ChangeLog-6.18.7)). The 6.12 and 6.6 longterm kernels never had it. Every GC 11.x / 12.x GPU runs MES, hence the hardware scope. The match is on the version number, so a distribution kernel that backported the fix may still be flagged, and one carrying the bug under a `.0` patch level cannot be detected. |

**What to do:** update to the **latest 6.18 longterm** point release or a current
stable **7.x** kernel. **Do not** move to 6.15, 6.16 or 6.17. None of them was ever a
longterm kernel (the kernel.org longterm lines are 6.18, 6.12, 6.6, 6.1, 5.15 and
5.10), all three are end-of-life, and 6.17.9 onward carries this hang.

If your kernel and hardware misbehave and the daemon says nothing, file an issue with
your `uname -a`, the GPU's PCI ID and a short description of the failure.

## Sources

Primary sources for the externally verifiable claims in this document. The AMD and
Intel board tables are also cross-referenced against the upstream lm-sensors
`configs/` directory and the driver DMI tables cited inline above.

**Kernel drivers & docs**
- [nct6775 `nct6775-platform.c`](https://github.com/torvalds/linux/blob/master/drivers/hwmon/nct6775-platform.c): `SIO_NCT6797_ID 0xd450`, `SIO_NCT6798_ID 0xd428`; [nct6775 hwmon doc](https://docs.kernel.org/hwmon/nct6775.html)
- [it87 hwmon doc](https://docs.kernel.org/hwmon/it87.html)
- [asus_wmi_sensors hwmon doc](https://docs.kernel.org/hwmon/asus_wmi_sensors.html): buggy-BIOS fan-stop warning + supported-board list
- [asus_ec_sensors hwmon doc](https://docs.kernel.org/hwmon/asus_ec_sensors.html): EC allowlist
- [amdgpu `PP_OVERDRIVE_MASK` (`amd_shared.h`)](https://github.com/torvalds/linux/blob/master/drivers/gpu/drm/amd/include/amd_shared.h): bit 14 = `0x4000`

**Out-of-tree drivers**
- [Fred78290/nct6687d](https://github.com/Fred78290/nct6687d): MSI NCT6686D / NCT6687D, `fan_config=msi_alt1` and `msi_fan_brute_force` parameters (no tagged releases; DKMS off `main`, `MODULE_VERSION` 1.0.0); [PR #164](https://github.com/Fred78290/nct6687d/pull/164) removed the `0xd450` collision (merged 2026-05-19)
- [frankcrawford/it87](https://github.com/frankcrawford/it87): IT8625E+ support, `force_id` / `ignore_resource_conflict` / `mmio` parameters; [PR #95](https://github.com/frankcrawford/it87/pull/95) (MMIO default on, 2026-03), [PR #102](https://github.com/frankcrawford/it87/pull/102) (ISA-bridge MMIO/H2RAM merge, 2026-04); issues [#64](https://github.com/frankcrawford/it87/issues/64) (secondary-chip fan control, closed 2025-12), [#70](https://github.com/frankcrawford/it87/issues/70), [#81](https://github.com/frankcrawford/it87/issues/81), [#89](https://github.com/frankcrawford/it87/issues/89) (X870E AORUS ELITE X3D dual-chip report, closed 2026-01-13), [#92](https://github.com/frankcrawford/it87/issues/92) (B650 GAMING X AX V2 ACPI bind failure, closed 2026-02-23), [#94](https://github.com/frankcrawford/it87/issues/94) (DKMS module-path quirk on CachyOS-LTS/Tumbleweed), [#96](https://github.com/frankcrawford/it87/issues/96) (IT8689E Rev 1 temps-to-90 partial stopgap; #96 itself has no post-merge report), [#99](https://github.com/frankcrawford/it87/issues/99) (IT8792 suspend/resume, still open), [#103](https://github.com/frankcrawford/it87/issues/103) (X870E AORUS MASTER community label mapping), [#106](https://github.com/frankcrawford/it87/issues/106) (IT8665E MMIO-default regression, closed, fixed by PR #120), [#108](https://github.com/frankcrawford/it87/issues/108) (`-Werror=unused-function` build failure); PRs [#114](https://github.com/frankcrawford/it87/pull/114) (IT8689E/IT8696E manual PWM: rejected 2026-08-25, superseded by #128, never merged), [#128](https://github.com/frankcrawford/it87/pull/128) (fix control issues for many Gigabyte boards: IT8688/8689/8790/8792/8795/87952 manual mode, H2RAM extra fan channels, Gigabyte WMI→SMI; merged 2026-08-24. Its author reports it untested on IT8689 silicon, but the PR thread carries three IT8689E hardware confirmations dated 2026-08-23, including **Rev 1** on a Z790 AORUS MASTER, all against pre-merge head `429d2b40`, which differs from the merged `27319db7` by 267 lines in the Intel H2RAM bridge path), [#129](https://github.com/frankcrawford/it87/pull/129) (follow-up fixes to #128, merged 2026-08-24), [#125](https://github.com/frankcrawford/it87/pull/125) (write the updated tachometer-enable mask, merged 2026-08-25), [#126](https://github.com/frankcrawford/it87/pull/126) (ISA-bridge MMIO hardening, open), [#110](https://github.com/frankcrawford/it87/pull/110) (force_pwm, open), [#120](https://github.com/frankcrawford/it87/pull/120) (remove MMIO for IT8665E, fixes #106, merged 2026-07-22), [#119](https://github.com/frankcrawford/it87/pull/119) (GA-X570S-AERO-G sensors config, merged 2026-07-22), [#132](https://github.com/frankcrawford/it87/pull/132) (v2.0, 2026-09-09: names Gigabyte chips after the board's SIV)

**Mainline it87 chip support (cross-checked against the kernel source)**
- [torvalds/linux `drivers/hwmon/it87.c`](https://github.com/torvalds/linux/blob/master/drivers/hwmon/it87.c): `enum chips`, re-read at the **v7.2** release tag *and* at `master` on 2026-08-26 (kernel 7.2 released 2026-08-16); the two are identical. It includes `it8622`, `it8689`, `it87952` and excludes `it8613`, `it8625`, `it8665`, `it8686`, `it8688`, `it8696`, `it8698`. The only in-tree `it87.c` change since the IT8689E commit is `7f8581c70` "Clamp negative values to zero in set_fan()"
- IT87952E mainline since kernel **6.3**: commit [`d44cb4cd7456`](https://github.com/torvalds/linux/commit/d44cb4cd7456) (2023; v6.2 lacks it, v6.3 has it)
- IT8689E mainline from kernel **7.1** for **fan control** (six PWM channels, `FEAT_SIX_PWM` + `FEAT_FANCTL_ONOFF`), not sensors only: commit [`66b8eaf`](https://github.com/torvalds/linux/commit/66b8eaf) (authored 2026-03-22, merged 2026-03-31), released in 7.1 on 2026-06-14
- IT8613E is queued in hwmon-next, so it is expected in **7.4** ([LWN: it87 IT8613E v4 series](https://lwn.net/Articles/1054427/)). IT8625E has had no mainline submission since the October 2024 v2 round, where changes were requested ([lore thread](https://lore.kernel.org/lkml/b6c2731b-8fac-4e7a-ab0c-2f36e8a64a69@roeck-us.net/T/)). Neither is in 7.3-rc4 (re-checked 2026-09-24)

**GPU device IDs & kernel regressions**
- AMD `amdgpu.ids` (libdrm) and `pci.ids` (hwdata): Navi 48 `0x7550` (RX 9070 XT rev `0xC0` / RX 9070 rev `0xC3`) and `0x7551` (Radeon AI PRO R9700)
- [drm/amd #4765](https://gitlab.freedesktop.org/drm/amd/-/issues/4765): a bisected hang, reported on RDNA4, in the MES eviction path that every RDNA3 / RDNA4 GPU runs. Introduced by `079ae5118e1f` in 6.18 and backported to 6.17.9 ([ChangeLog-6.17.9](https://cdn.kernel.org/pub/linux/kernel/v6.x/ChangeLog-6.17.9)); fixed by `3fd20580b96a` in 6.18.7 ([ChangeLog-6.18.7](https://cdn.kernel.org/pub/linux/kernel/v6.x/ChangeLog-6.18.7)) and 6.19.0, never on 6.17.y
- [kernel.org releases](https://www.kernel.org/category/releases.html): the longterm lines (6.18, 6.12, 6.6, 6.1, 5.15, 5.10); 6.15–6.17 were never longterm
- [Kernel commit e471627d5627](https://git.kernel.org/torvalds/c/e471627d56272a791972f25e467348b611c31713) (v7.0): "drm/amdgpu/pm: drop SMU driver if version not matched messages — It just leads to user confusion"
- [ROCm Issue #6101](https://github.com/ROCm/ROCm/issues/6101): per-unit R9700 fan faults; an AMD engineer there confirms the PMFW path works and calls the interface mismatch harmless. Closed 2026-07-09 as `completed`, with post-closure reports through 2026-08-28. Its 6.18.20 / 6.19.10 rows are an unbootable-kernel report on out-of-tree `amdgpu-dkms`, not evidence of hangs under load.
- [ROCm Issue #6155](https://github.com/ROCm/ROCm/issues/6155): RDNA4 / 1002:7551 MES firmware version clarification. Closed 2026-05-12 as `completed`.
- [Bazzite (ublue-os/bazzite) #4498](https://github.com/ublue-os/bazzite/issues/4498): nct6687 / nct6775 `0xd450` collision brick report; closed 2026-09-07 without a distro fix. Since 2026-08-15 Bazzite ships the Terra `nct6687d` kmod ([`1f234a7e81`](https://github.com/ublue-os/bazzite/commit/1f234a7e81)), which autoloads `nct6687` and blacklists `nct6683`
