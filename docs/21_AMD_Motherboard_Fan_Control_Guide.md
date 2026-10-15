# AMD Motherboard Fan Control Guide

How motherboard fan control works on AMD desktop boards under Linux, vendor by vendor:
which chip carries the fans, which driver controls it, and the quirks that get in the
way. To install a driver, follow the manual's [Driver Setup](../manual/driver-setup.md).
The full chip matrix, with sources, is the
[Hardware Compatibility Guide](19_Hardware_Compatibility.md); for a symptom, start at
[Hardware Troubleshooting](../manual/hardware-troubleshooting.md).

## The Super-I/O chip decides, not the chipset

On desktop AMD boards, fan control is done by the motherboard's Super-I/O chip or
embedded controller (EC), not by the AMD chipset. Chipset names (X570, B550, X670,
B650, X870, B850) identify the board's generation, socket and feature tier. They do
**not** decide which Linux driver controls the fans. The Super-I/O, a separate chip
that handles low-speed I/O, reads the fan speeds and writes the PWM duty.

So work out fan control in this order:

1. **Board vendor and model** (from DMI: `board_vendor`, `board_name`)
2. **Super-I/O chip and hwmon driver** (`nct6775`, `nct6683`, `it87`, …)
3. **What actually reads and writes** in `/sys/class/hwmon/`
4. **AMD chipset**, as a grouping hint only

Do not expect all "X670 boards" to behave alike. An ASUS X670E with a Nuvoton NCT6799D
and a Gigabyte X670E with an ITE IT8689E use different drivers and have different
quirks.

## Platform overview

| AMD Platform | Typical Boards | Common Linux Driver Path | Notes |
|---|---|---|---|
| **AM4 400-series** (B450, X470) | ASUS PRIME X470-PRO, ROG STRIX B450/X470 -E/-F/-I; MSI B450/X470; Gigabyte AORUS B450/X470; ASRock B450/X470 | `nct6775` (mainline) on the MSI and ASRock boards (NCT6779D / NCT6792D / NCT6795D / NCT6797D); `it87-dkms-git` on Gigabyte (IT8686E + IT8792E) **and on ASUS**, whose AM4 300/400-series boards carry an ITE IT8665E; `asus_wmi_sensors` / `asus_ec_sensors` for extra ASUS sensors (read-only) | The hazards are the NCT6797D-vs-`nct6687` [chip-ID collision](19_Hardware_Compatibility.md#the-nct679x-chip-id-collision) on MSI and the [ASUS WMI firmware bug](#sensor-drivers-are-not-the-control-path) |
| **AM4 500-series** (X570, B550, A520) | ASUS X570/B550, MSI B550/X570, Gigabyte X570/B550, ASRock X570/B550 | `nct6775` (ASUS, ASRock, MSI's original X570 boards); `nct6687d-dkms-git` on MSI B550 and X570S boards; `it87-dkms-git` on Gigabyte; `nct6683` (read-only) for the B550 Taichi's EC | All four Super-I/O families ship in this generation, and each vendor uses a different one |
| **AM5 600-series** (X670E, X670, B650E, B650, A620) | ASUS X670/B650, MSI B650/X670, ASRock A620/B650/X670, Gigabyte X670/B650 | `nct6775` (ASUS NCT6799D, ASRock NCT6796D-S); `nct6687d-dkms-git` (MSI); `it87-dkms-git` (Gigabyte); ASRock NCT6686D boards need `asrock-nct6683` or `nct6687d` for PWM; plus ASUS EC helpers | Out-of-tree drivers become near-mandatory; monitoring often works before control does |
| **AM5 800-series** (X870E, X870, B850, B840) | ASUS X870/B850, MSI X870/B850, Gigabyte X870/B850, ASRock X870/B850 | `nct6775` (ASUS NCT6701D, reported as `nct6799`); `nct6687d-dkms-git` with the msi_alt1 map (MSI); `it87-dkms-git` (Gigabyte); ASRock mixes NCT6796D-S and NCT6686D | The hardest generation on Linux: expect model-specific exceptions |

## ASUS

ASUS is one of the easier vendors on Linux: most boards use a mainline driver, and the
kernel documentation lists many boards by name.

### Which chip carries the fans

- **AM4 300/400-series: an ITE IT8665E, not a Nuvoton part.** "Chip markings and
  sensors-detect say that this is IT8665E" on a PRIME X470-PRO
  ([frankcrawford/it87 #27](https://github.com/frankcrawford/it87/issues/27)), and the
  same on the ROG STRIX X470-F / X470-I and B450-F; a B450-I owner's `sensors-detect`
  found chip ID `0x8665` too
  ([lm-sensors #195](https://github.com/lm-sensors/lm-sensors/issues/195)). Mainline has no IT8665E driver, so
  fan control needs the out-of-tree `it87-dkms-git`. Use a build from 2026-07-22 or
  later: older builds mangled IT8665E writes under the MMIO default
  ([issue #106](https://github.com/frankcrawford/it87/issues/106)).
- **AM4 500-series** (TUF GAMING X570-PLUS, ROG STRIX X570 / B550, PRIME X570-PRO): an
  **NCT6798D**, driven by mainline `nct6775`.
- **AM5 600-series** (ROG STRIX X670E, ROG CROSSHAIR X670E, TUF GAMING X670E-PLUS,
  PRIME B650-PLUS): an **NCT6799D(-R)**, which `nct6775` reports as `nct6799`
  ([zeule/asus-ec-sensors #45](https://github.com/zeule/asus-ec-sensors/issues/45);
  [lm-sensors #416](https://github.com/lm-sensors/lm-sensors/issues/416): "this
  board (ASUS TUF GAMING X670E-PLUS WIFI) has indeed a Nuvoton NCT6799D-R chip").
- **AM5 800-series** (and Intel Z890 / B860): an **NCT6701D**, chip ID `0xd806`.
  `sensors-detect` calls it an unknown chip; mainline `nct6775` binds it as `nct6799`
  ("NCT6796D-S/NCT6799D-R or compatible"). Fans and voltages read correctly, but most
  temperature channels are not meaningful
  ([lm-sensors #542](https://github.com/lm-sensors/lm-sensors/issues/542),
  [#544](https://github.com/lm-sensors/lm-sensors/issues/544)), so drive curves from
  `k10temp` Tctl or another sensor you can verify. X870 / X870E boards on the kernel's
  ASUS list reach the chip through the WMI path from kernel 7.1 (a board missing from
  the list, such as a newer edition, uses the I/O ports); **no B850 board is on that
  list**, so B850 boards use the I/O ports directly. Owners of a TUF GAMING B850-PLUS
  WIFI and a ROG STRIX B850-F report it binding that way (#542, #544); an ACPI conflict
  can still block another board. One ROG
  STRIX X870E-E owner measured the firmware switching a header straight back from
  manual to full speed
  ([zeule/asus-ec-sensors #100](https://github.com/zeule/asus-ec-sensors/issues/100),
  before 7.1); whether the WMI path changes that is unverified. Run Test PWM Control.

No ASUS board is known to use the out-of-tree `nct6687d`: ASUS owners who tried it
report "No such device" ([nct6687d #104](https://github.com/Fred78290/nct6687d/issues/104)).

### Sensor drivers are not the control path

ASUS boards often expose two driver paths:

1. **Sensor enrichment.** `asus_ec_sensors` (hwmon name `asusec`) and
   `asus_wmi_sensors` add temperature readings such as VRM, T_Sensor, water in/out and
   chipset, from the ASUS embedded controller or WMI interface. They are read-only.
2. **PWM control.** The Super-I/O chip: `nct6775` on AM4 500-series and every AM5
   board, the out-of-tree `it87` on AM4 300/400-series boards.

If your board exposes both `asusec` and `nct6799`/`nct6798` in
`/sys/class/hwmon/*/name`, the Nuvoton device controls the fans and `asusec` supplies
the extra sensors. Never try to write PWM through the EC or WMI interface.

**`asus_ec_sensors` lists boards by exact DMI name**, and the list grows with every
kernel: 55 boards in 7.2, 60 in the 7.3 release candidates. A board added in a recent
kernel is **not** in the 6.12 / 6.18 LTS kernels. The AMD boards on the list as of
the 7.3 release candidates, with the kernel that added the newer ones:

- PRIME X470-PRO, PRIME X570-PRO, PRIME X670E-PRO WIFI
- ProArt B550-CREATOR, ProArt X570-CREATOR WIFI, ProArt X670E-CREATOR WIFI,
  ProArt X870E-CREATOR WIFI (6.17)
- Pro WS X570-ACE; Pro WS TRX50-SAGE WIFI (and A); Pro WS WRX90E-SAGE SE
- ROG CROSSHAIR VIII DARK HERO / HERO (and WI-FI) / FORMULA / IMPACT
- ROG CROSSHAIR X670E EXTREME / HERO / GENE; ROG CROSSHAIR X870E HERO (7.3)
- ROG STRIX B550-E / B550-I; ROG STRIX B650E-E / B650E-I
- ROG STRIX B850-I GAMING WIFI (6.18); ROG STRIX B850-E GAMING WIFI (7.2)
- ROG STRIX X470-I GAMING (6.19); ROG STRIX X470-F GAMING (7.1)
- ROG STRIX X570-E (and WIFI II) / X570-F / X570-I
- ROG STRIX X670E-E / X670E-I
- ROG STRIX X870-I / X870E-E (6.18); X870-F / X870E-H (6.19); X870E-E GAMING
  WIFI7 R2 (7.3)
- ROG ZENITH II EXTREME (and ALPHA)
- TUF GAMING X670E-PLUS (and WIFI)

No B850-A, B850-F, B840 or other B850 STRIX board is listed. From 7.3 an unconnected
T_Sensor or water-probe socket reads as unavailable rather than as a -62/-60/-40 °C
placeholder. Reference: https://docs.kernel.org/hwmon/asus_ec_sensors.html

**`asus_wmi_sensors` comes with a firmware warning.** It covers 16 older boards (the
X370 / X470 / B450 ROG CROSSHAIR VI / VII, ROG STRIX B450 and X470 boards, PRIME
X470-PRO, and the X399 boards). The kernel documentation warns that some ASUS BIOSes
implement WMI badly: fans stop, fans stick at maximum, or readings freeze, more likely
the more often it is polled, with the PRIME X470-PRO "particularly bad". It names no
safe polling rate. Update to a BIOS whose WMI method version is 2 or later (the driver
refuses older versions), and soak-test while polling before you leave the machine
unattended. The [AMD Sensor Interpretation Deep Dive](22_AMD_Sensor_Interpretation_Deep_Dive.md#asus-wmi-sensors-am4-and-x399-boards)
has the board list and what the readings mean.

### ACPI conflicts and BIOS settings

ASUS boards with Nuvoton chips may have ACPI OpRegion conflicts on I/O ports
0x0290–0x0299, which the daemon's diagnostics detect. From Linux 5.16 `nct6775` reads
supported ASUS boards through an ASUS WMI access path (`access_asuswmi`) that sidesteps
the conflict; otherwise the only kernel-side remedy is `acpi_enforce_resources=lax`.
The [Hardware Compatibility Guide](19_Hardware_Compatibility.md#acpi-resource-conflicts)
has both, and the [ASUS notes](19_Hardware_Compatibility.md#asus-nuvoton-nct679x--nct6701d)
cover the Q-Fan BIOS items: no BIOS setting makes the headers writable, because under
`nct6775` they already are.

## MSI

### Two chip families: NCT6797D or NCT6687D

MSI's AMD boards split into two camps that need different drivers, and loading the
wrong one can do lasting harm:

- **NCT679x, mainline `nct6775`:** the AM4 400-series boards (B450M MORTAR and MAG
  B450 TOMAHAWK MAX carry an NCT6797D; the X470 GAMING PRO and its CARBON an NCT6795D),
  and the AM4 500-series **X570-A PRO, the original 2019 MPG X570 GAMING PRO CARBON
  WIFI / GAMING PLUS / GAMING EDGE WIFI, MAG X570 TOMAHAWK WIFI, MEG X570 ACE / UNIFY /
  GODLIKE, and MAG X570S TOMAHAWK / TORPEDO MAX** (an NCT6797D, which reports
  `0xd451`). The in-kernel `nct6775` supports them out of the box. **Do not install
  `nct6687d` here, and never load it with `force=1`**: see
  [the chip-ID collision](19_Hardware_Compatibility.md#the-nct679x-chip-id-collision),
  which has bricked a CPU fan header.
- **NCT6687D, out-of-tree `nct6687d`:** **MAG B550 TOMAHAWK, B550-A PRO, MPG B550
  GAMING PLUS / GAMING EDGE, and the 2021 MPG X570S EDGE MAX WIFI / CARBON MAX WIFI**,
  and every AM5 board. The chip reports `0xd592` (both drivers match it as `0xd590`).

To tell which camp your board is in:

```bash
sudo dmesg | grep -i 'found nct'
ls -l /sys/class/hwmon/hwmon*/device/driver
```

`nct6775: Found NCT6797D …` is the mainline camp. `Found NCT6687D` from either
`nct6683` or `nct6687` is the out-of-tree camp. The hwmon **name** alone cannot tell
the two NCT6687D drivers apart, because the in-kernel `nct6683` also names the device
`nct6687`.

**Read-only headers mean the wrong driver.** On an NCT6687D board the in-kernel
`nct6683` may load and show sensors, but it publishes every `pwmN` read-only (it
enables writes only on Mitac OEM systems). Install `nct6687d-dkms-git` and blacklist
`nct6683`: with both loaded they can bind the same chip at once, which garbles readings
and makes writes fail ([nct6687d #204](https://github.com/Fred78290/nct6687d/issues/204),
B550-A PRO). No BIOS setting is involved. The commands are in
[Driver Setup](../manual/driver-setup.md#step-3--install-the-driver). One confirmed
success: the MPG B550I GAMING EDGE (MAX) WIFI works with `nct6687d`'s default register
map ([nct6687d #3](https://github.com/Fred78290/nct6687d/issues/3)).

### AM5 600-series: the default register map

The AM5 600-series boards (MAG B650 TOMAHAWK WIFI, MAG X670E TOMAHAWK WIFI, MPG X670E
CARBON WIFI, MPG B650 CARBON WIFI, PRO X670-P WIFI) use the NCT6687D's **default**
register map. Use `nct6687d-dkms-git`, blacklist `nct6683`, and **never** force
`fan_config=msi_alt1` here: it makes every SYS_FAN read 0 RPM
([nct6687d #167](https://github.com/Fred78290/nct6687d/issues/167)). The chip-ID
collision does not apply to these boards: their chip reports `0xd592`, and the brick
scenario needs `nct6687` claiming an NCT679x.

### AM5 800-series: msi_alt1 and brute force

The B840 / B850 / B860 / X870 / X870E / Z890 boards use the same NCT6687D with a
different EC register layout, "msi_alt1" (monitoring tools label these boards
*NCT6687DR*). The driver selects it **automatically** for each board on its list,
`nct6687.c::nct6687_msi_alt_boards[]` in Fred78290/nct6687d. The list keeps growing,
and each entry is a full DMI board name with its MS-number, so a PZ / WHITE / MAX
edition can be missing while its sibling is listed. Check the source rather than any
point-in-time count.

If your board is in those series, is not on the list, and its system fans do not
respond to PWM writes, set the map yourself:

```bash
sudo modprobe -r nct6687
sudo modprobe nct6687 fan_config=msi_alt1
# persist:
sudo tee /etc/modprobe.d/nct6687.conf <<<'options nct6687 fan_config=msi_alt1'
```

On these boards the EC's own curve can keep driving the system fans after a single PWM
write. `msi_fan_brute_force=1` (upstream marks it BETA) writes the duty into all 7
BIOS curve points instead, saving and restoring the originals. It is a separate,
current parameter, not a legacy alternative to `fan_config`, and it **requires
`nct6683` to be blacklisted**. Several boards needed it before system-fan writes stuck:
PRO X870E-P WIFI, MAG X870E TOMAHAWK WIFI, PRO Z890-P WIFI, MAG Z890 TOMAHAWK WIFI, and
PRO B850M-P WIFI, where current builds returned `EIO` even for CPU_FAN until it was on
([nct6687d #107](https://github.com/Fred78290/nct6687d/issues/107),
[#148](https://github.com/Fred78290/nct6687d/issues/148),
[#185](https://github.com/Fred78290/nct6687d/issues/185),
[#202](https://github.com/Fred78290/nct6687d/issues/202)). The three-file setup and
the warning about forcing `msi_alt1` on other series are in the
[MSI notes](19_Hardware_Compatibility.md#msi-nct6687d).

### Known limitations

- On the msi_alt1 boards, **CPU_FAN** and **PUMP_FAN** have often worked before
  **SYS_FAN** did. That is not guaranteed on current builds: on a PRO B850M-P WIFI even
  CPU_FAN returned `EIO` until brute force was enabled
  ([nct6687d #202](https://github.com/Fred78290/nct6687d/issues/202)).
- **3-pin DC fans** need the header's fan type set to DC in the BIOS. No report since
  brute force arrived isolates a DC-specific failure.

## ASRock

ASRock boards mix chips, and which chip carries which header is per board. The block
diagram in the board's manual names them, and `cat /sys/class/hwmon/hwmon*/name` shows
what bound.

### AM4: mainline drivers

AM4 ASRock boards use the NCT6779D (300/400-series ATX and micro-ATX: B450 Pro4, B450
Steel Legend, X470 Taichi), NCT6792D (the ITX boards: B450 / X470 / B550M
Gaming-ITX/ac) or NCT6793D (the HDV R4.0 boards). The AM4 500-series ATX boards report
an NCT6798D-class chip (B550 Steel Legend, physically an NCT6796D-E; B550 Extreme4,
B550 PG Velocita, X570 Taichi, X570 Steel Legend). All are covered by mainline
`nct6775`, whose PWM files are always writable; the daemon switches a header to manual
itself. If a fan does not follow, check that the header's BIOS fan type matches the fan
(DC for 3-pin, PWM for 4-pin).

These boards need none of the out-of-tree drivers the AM5 generation brings. Do not
install `nct6686d` or `nct6687d` "to be safe": see
[the chip-ID collision](19_Hardware_Compatibility.md#the-nct679x-chip-id-collision).

The exception is the **B550 Taichi and B550 Taichi Razer Edition**: their fans are on
an NCT6683D-class EC (hwmon `nct6683`), and the NCT6798D beside it has no fans wired.
The in-kernel `nct6683` reads that EC but publishes PWM read-only;
`branchmispredictor/asrock-nct6683` lists both boards and makes it writable.

### AM5: NCT6686D or NCT6796D-S, by family

ASRock's AM5 boards split by family, per the block diagrams in ASRock's manuals:

- **Steel Legend / LiveMixer / Riptide / Lightning ITX** (B650 / B650E / X670E Steel
  Legend, B650 LiveMixer, A620I / B650I Lightning WiFi, the B650E PG-ITX WiFi; and the
  B850 / X870 Steel Legend WiFi, B850 / X870 Riptide WiFi, B850 / X870 LiveMixer WiFi
  and B850I Lightning WiFi): **NCT6686D only**. The exception is the **B850M Steel
  Legend WiFi**, which has an NCT6796D-S like the Pro RS family below. The in-kernel
  `nct6683` reads the NCT6686D (some boards need `force=1`) but publishes PWM
  **read-only**, so writes are refused. PWM needs an out-of-tree driver:
  `asrock-nct6683` lists A620I / B650I Lightning WiFi, X670E Steel Legend and B650E
  Steel Legend WiFi by exact name; `nct6687d` works on the B650 LiveMixer
  ([#103](https://github.com/Fred78290/nct6687d/issues/103)) and others, with MSI's
  register map and fan labels; `nct6686d` is tested by its author only on the A620I
  Lightning WiFi.
- **Pro RS / Pro-A / Challenger / PG Lightning / HDV** (B650 / B650M Pro RS, X670E Pro
  RS, X670E PG Lightning, A620M Pro RS, B650M-HDV/M.2; B850 / B850M / X870 Pro RS,
  Pro-A WiFi and Challenger WiFi; the B850M Steel Legend WiFi) and the **X870 Nova
  WiFi**: **NCT6796D-S only**, reported as `nct6799`. Mainline `nct6775`, nothing else
  needed; do not load `nct6687d` here. (Fred78290/nct6687d issue #153 matches the
  two-chip X870E Nova, NCT6796D-S + NCT5585D, not the X870 Nova.)
- **Taichi** (X670E Taichi, B650E Taichi, X870E Taichi and their Lite editions): both
  chips, below.

Test PWM writes on a non-critical chassis fan header first. ASRock boards need the
driver chosen per model, not by a single rule.

### Taichi boards: two Nuvoton chips

The **ASRock X870E Taichi Lite** carries two Super-I/O chips: an **NCT6686D** at I/O
`0x0a20` (bound by `nct6687d`, or read-only by the in-kernel `nct6683`) and an
**NCT6796D-S** at I/O `0x0290`, which mainline `nct6775` reports as
"NCT6796D-S/NCT6799D-R" (hwmon `nct6799`), behind a Fintek F85227N eSPI→LPC bridge.
Both drivers must be loaded to control every fan. The same pair is on the X670E /
X870E Taichi and the B650E Taichi (Lite).

**Pump label hazard.** On an X870E Taichi an owner measured CHA_FAN1/2, CPU_FAN2 and
AIO_PUMP on the `nct6799` chip and CHA_FAN3/4 on the NCT6686D
([nct6687d #155](https://github.com/Fred78290/nct6687d/issues/155)). `nct6687d` names
the NCT6686D's channels with MSI's labels, so its "Pump Fan" is a chassis header there,
while the real pump header is unlabelled. Assign the pump role to the real pump header
(**Set role…** on its Hardware-page card, or the fan wizard) so the pump floor covers
it. The GUI marks `nct6687d`'s MSI labels *unverified* on any non-MSI board and asks
for the real pump.

The X870E Taichi family has **two pump headers**. AIO_PUMP is on the `nct6799` chip
(`pwm4`, measured in #155). W_PUMP is, per LibreHardwareMonitor's board map, the
NCT6686D's first channel, which `nct6687d` labels "CPU Fan"; nobody has measured it on
Linux yet. That label gives a pump on W_PUMP the CPU floor but not the pump
protections, so assign the pump role to it as well. Ventulus deliberately does not
rename this header for the board until a Linux measurement confirms it.

The collision detector does not raise the critical banner here, although both
`nct6687` and `nct6775` are loaded, because it finds two distinct Nuvoton chip IDs
(it keys on the chips, not on the board name). If a collision banner does appear, one
of the two chips is missing; check that both enumerated:

```bash
cat /sys/class/hwmon/hwmon*/name
```

If only one `nct6…` name is visible, follow the
[collision remediation](19_Hardware_Compatibility.md#the-nct679x-chip-id-collision)
before touching modules. References: Fred78290/nct6687d issue #155, Level1Techs ASRock
Taichi X870E thread.

### Drivers for the NCT6686D

The [Hardware Compatibility Guide](19_Hardware_Compatibility.md#asrock) compares the
three out-of-tree drivers (`asrock-nct6683`, `nct6687d`, `nct6686d`) and the boards
each supports. Two things to know first:

- **Monitoring works without them.** The in-kernel `nct6683` shows temperatures, fan
  speeds and voltages. Some boards need the driver option `options nct6683 force=1`,
  in `/etc/modprobe.d/nct6683.conf`, because the driver binds only known customer IDs
  (how: [Setting a driver option or a kernel parameter](19_Hardware_Compatibility.md#setting-a-driver-option-or-a-kernel-parameter)).
  It never makes PWM writable, so sensor readings do not mean the fans can be
  controlled.
- **`sensors-detect` does not know the chip.** It reports "Found unknown chip with ID
  0xd441" for the NCT6686D on boards such as the X670E Steel Legend, Z890I Nova, Z890
  Lightning and X870E Taichi, although `nct6683` with `force=1` reads it
  ([lm-sensors #499](https://github.com/lm-sensors/lm-sensors/issues/499)).

### Troubleshooting an ASRock board

1. Check which chips your board has (the manual's block diagram) and which bound
   (`cat /sys/class/hwmon/hwmon*/name`).
2. Headers on the NCT67xx chip (`nct6798` / `nct6799` / `nct6792` / `nct6779`) are
   writable under `nct6775`. Test one on a non-critical chassis fan.
3. Headers on the NCT6686D / NCT6683D are read-only under the in-kernel `nct6683`
   (`ls -l` shows `-r--r--r--`). Try the alternative driver that lists your board.
4. Report what you find: ASRock driver support is changing quickly.

## Gigabyte

Gigabyte is the vendor where ITE chip quirks matter most and where the gap between
"sensors visible" and "fans controllable" is widest.

### Which chips

Gigabyte AMD boards use ITE chips, most of which the mainline `it87` driver does not
support, so they need the out-of-tree `it87-dkms-git`
([frankcrawford/it87](https://github.com/frankcrawford/it87)). Many AORUS boards pair
a primary chip with a secondary that carries extra headers:

| Generation | Dual-chip boards | Single-chip boards |
|---|---|---|
| AM4 400-series | X470 AORUS ULTRA GAMING, X470 AORUS GAMING 5/7 WIFI, B450 AORUS PRO / PRO WIFI / PRO-CF: **IT8686E** at `0x0a40` + **IT8792E** at `0x0a60`. On the B450 AORUS PRO the IT8792E carries no fan header, so a missing secondary costs temperatures and voltages, not fans | |
| AM4 500-series | X570 AORUS MASTER / PRO / PRO WIFI / ULTRA / XTREME, B550 AORUS MASTER / PRO, B550 VISION D: **IT8688E + IT8792E**. The X570S refresh (X570S AERO G, X570S AORUS MASTER): **IT8689E + IT87952E** | B550M AORUS PRO, B550I AORUS PRO AX: IT8688E only |
| AM5 600-series | X670E AORUS MASTER, X670E AORUS PRO X: **IT8689E + IT8792E** (hwmon `it8792`, not `it87952`; [#96](https://github.com/frankcrawford/it87/issues/96) dmesg: "Found IT8792E/IT8795E chip at 0xa60, revision 3") | X670 AORUS ELITE AX, X670 / B650 GAMING X AX: IT8689E only (it87 SIV catalogue) |
| AM5 800-series | X870E AORUS PRO / ELITE X3D / MASTER / XTREME AI TOP, B850 AI TOP, X870 AORUS ELITE WIFI7, X870 AORUS STEALTH ICE: **IT8696E + IT87952E**. Per the it87 SIV catalogue alone, the same pair on the 2026 boards: X870 / B850 AORUS ELITE X3D, X870E EAGLE (X3D) WIFI7, X870E AERO X3D (DARK) WOOD, X870 AORUS TACHYON ICE, X870E AORUS XTREME X3D AI TOP, X870 / B850 AORUS STEALTH | X870E AORUS ELITE WIFI7, X870 EAGLE WIFI7, B850M AORUS STEALTH (ICE): IT8696E only |

The Threadripper boards (X399, TRX40, TRX50) are in the
[Hardware Compatibility Guide](19_Hardware_Compatibility.md#amd-platform--typical-chip-mapping).

### Driver, BIOS and the IT8689E

On a current `it87-dkms-git` build usually **no BIOS change is needed**: the driver
takes each header over from Smart Fan. Never give the BIOS curve a 0% point, because
it runs the fans whenever the daemon is not in control. For a 4-pin fan set **FAN
Control Mode** to PWM, and treat *Full Speed* as a fail-safe, not a fix. The
[Gigabyte notes](19_Hardware_Compatibility.md#gigabyte-ite-chips) explain each rule,
why the headers are not read-only, and the MMIO default.

On builds older than 2026-08-24, IT8689E boards (Rev 1 especially, e.g. the X670E
AORUS MASTER) accepted PWM writes with no effect while a normal BIOS curve was active,
although Windows tools could control the fans. The fork's PR #128 fixes this, with
positive IT8689E reports including Rev 1, but none since the merge on a dual-chip
IT8689E board.
So update `it87-dkms-git`, then verify with Test PWM Control. If a header still cannot
be controlled on a current build, use a different header, move the fan to an external
controller such as the OpenFAN controller, or let the BIOS curve drive that header,
keeping the curve free of 0% points. The fix's status and the old BIOS stopgap are in
[IT8689E boards](19_Hardware_Compatibility.md#it8689e-boards).

### IT8792E control after suspend

X570-generation boards can lose **IT8792E fan control after suspend and resume**
([frankcrawford/it87 #99](https://github.com/frankcrawford/it87/issues/99)). The
reporter found it working after rebuilding from master in September 2026, and the
author of PR #128 credits that patch's sleep changes, but the issue is still open. The
daemon puts every header it controls back into manual mode by itself after a resume;
if headers stay stuck, a reboot is the reliable reset.

### A secondary Super-I/O that will not enumerate

On some dual-chip boards only the primary chip appears: one hwmon device instead of
two, costing 3 of 8 fan headers and 3 of 9 temperatures on an X870E AORUS MASTER. The
cause is an ITE eSPI-to-LPC **bridge** latched in configuration mode, answering in place
of the chip behind it. It answers `0x8883` to a read with the Super-I/O unlock key, and
`0xFFFF` to one without it ([#70](https://github.com/frankcrawford/it87/issues/70)).
The driver prints the failing ID only at debug level (`pr_debug`), and a `0xFFFF` read
makes it give up without printing anything, so there is no log line to choose a remedy
from. It is recoverable, by one ladder whatever the ID: the steps are in
[Hardware Troubleshooting](../manual/hardware-troubleshooting.md#some-of-my-fan-headers-are-missing--only-5-of-8-show-up).
This section explains why that ladder works.

#### What latches it, measured

`nct6775` and `w83627ehf` share one `superio_enter()`:

```c
static inline int superio_enter(int ioreg) {
        if (!request_muxed_region(ioreg, 2, DRVNAME)) return -EBUSY;
        outb(0x87, ioreg);      /* unconditional */
        outb(0x87, ioreg);
        return 0;
}
```

Both call it and *then* read `SIO_REG_DEVID`, on both 0x2E and 0x4E. That
unconditional write is what puts the bridge into config mode. `it87` does the
opposite: `superio_enter(sioaddr, /*noentry=*/true)` reads the DEVID with no unlock
and unlocks only if that returns `0xffff`. That is why `it87` is safe and the other two
are not. `sensors-detect` writes the unlock key too.

Measured on an X870E AORUS MASTER, 2026-09-05, within a single boot:

| Step | Result |
| --- | --- |
| Control: reload `it87` alone | `it87952` stays bound; a reload writes nothing |
| Load `nct6775`, reload `it87` | `it87952` gone (with dynamic debug on: `Unsupported chip (DEVID=0x8883)`) |

`nct6775` **fails to load** on this board (`could not insert 'nct6775': No such
device`) and does the damage anyway, because the port write happens before the
`-ENODEV`. `w83627ehf` was not tested on its own; it is implicated by having
byte-identical unlock behaviour in the same function, not by measurement.

The latch survived a warm reboot *and* a soft power-off on that board, because the
bridge keeps standby power (ITE lists the IT8883 as "3VSB and VBAT Supported"). Only
removing mains power cleared it. That is the step people skip, and skipping it produces
a false negative. The daemon package's Super-I/O guard keeps both modules off every
Gigabyte board; it cannot stop `sensors-detect`, which probes the ports itself.

#### Why the usual advice cannot work

| Advice | Why it fails |
| --- | --- |
| "load with `mmio=on`" | `mmio` already defaults to true in `it87.c`, and the test host does not set it (its only it87 option is `ignore_resource_conflict=1`), so this names a state already in effect. |
| "update to a current build" | The failure reproduces at upstream HEAD. It is not a driver bug. |
| "read the DEVID in `dmesg` and pick a fix" | The ID is printed only with dynamic debug on, `0xFFFF` never, and the same ladder clears both readings. |
| "per issue #81" | #81's *opening post* forced the ID and set `mmio=on` and still lost three fans and a pump. Its later comments record the reporter getting the second chip working, the opposite of what the opening post shows. |

The driver has **no** case, constant or comment for `0x8883`, while
`IT87952E_DEVID 0x8695` **is** defined and handled, so while the bridge is latched the
secondary is **unreachable, not unsupported**.

**Bounded by pairing, not by family.** Other boards with the same IT8696E + IT87952E
pairing work out of the box: the X870E AORUS ELITE X3D is owner-confirmed with both
chips controllable ([#89](https://github.com/frankcrawford/it87/issues/89)). Do not
generalise this to "X870E" or to "dual-ITE". The GUI's chip guidance tells a user who
searches for "IT8883" what they are looking at and how to clear it.

### X870E AORUS MASTER, worked example

The board carries an **IT8696E rev 0** (primary) and an **IT87952E** (secondary). PWM
control on the primary works. It is a different case from the X670E AORUS MASTER,
which has an IT8689E rev 1 and the manual-control limitation above.

**Physical layout: 8 PWM headers.** Five are on the IT8696E (CPU_FAN, SYS_FAN1,
SYS_FAN2, SYS_FAN3, CPU_OPT) and three on the IT87952E: SYS_FAN5_PUMP, SYS_FAN6_PUMP,
SYS_FAN4 in that pwm order, per two owners' configs in frankcrawford/it87
[issue #103](https://github.com/frankcrawford/it87/issues/103) and the it87 project's
Gigabyte sensor catalogue (SIV `A008090A`, which this board reports). An annotation in
it87 PR #100 orders them SYS_FAN4 / FAN5_PUMP / FAN6_PUMP instead, read with three
identical fans. A test on 2026-09-28 settled it on the reference host: with FAN5_PUMP
and FAN6_PUMP empty, the one fan, on SYS_FAN4, reads on pwm3, where PR #100 puts
FAN6_PUMP, so the GUI's labels are verified. The pwm1/pwm2 order rests on the agreeing
sources; both are PUMP labels, so the floor is the same either way. No upstream
`lm_sensors` config exists for this board (the upstream `configs/` tree is unchanged
since 2023); the GUI ships a fallback label table aligned with the #103 mapping.

**The secondary can be masked by a latched bridge, and it is recoverable (measured
2026-09-05).** On BIOS **F14c** with `it87-dkms-git` **349.c567739** (upstream HEAD),
the kernel finds `IT8696E chip at 0xa40 [MMIO at 0xfe100000]` and then gets device-ID
`0x8883` from the secondary address (visible only with it87 dynamic debug on). One
`it87` hwmon device enumerates and exactly **five** `pwm` files exist, the primary's.
Suppressing `nct6775` and `w83627ehf` and then cutting mains power restored the
secondary as `it87952-isa-0a60`: 3 fans, 3 PWMs, 3 thermistor temps, 8 of 8 headers.

An earlier report, on `it87-dkms-git` 332.20f2f2f+ and BIOS **F13a** (2026-03), saw
both chips. Both observations are recorded because they differ in board firmware *and*
driver revision, and nobody has bisected which change matters. Treat the 8-header
figure as the board's **physical** layout, not as what Linux reaches on every boot.

it87 v2.0 builds name this board's chips `it8696_a008090a` / `it87952_a008090a`; the
daemon strips the suffix, so no header id changes.

BIOS Smart Fan 6 reclaims `pwm_enable` on CPU_FAN at about 1 Hz; the daemon's
`pwm_enable` watchdog handles this on its own. Setting a header to *Full Speed* in the
BIOS is a fail-safe, not a fix: on some boards it locks Linux out of the header.

### What to expect on a Gigabyte board

1. Full control works (a current driver; usually no BIOS change needed).
2. RPM reads work but PWM writes have no effect (on IT8689E boards: a driver build
   older than PR #128).
3. Only some headers are controllable (a blocked secondary chip, or headers on an
   IT57xx EC that only current builds reach).
4. The firmware keeps retaking a header (the daemon's watchdog re-asserts manual mode;
   update the driver).

Test PWM Control (`POST /hwmon/{header_id}/verify`) tells you which applies to each
header; [Fan Tests and Reports](../manual/fan-tests.md#test-pwm-control) explains the
results.

## Sources

**Kernel documentation:**
[nct6775](https://docs.kernel.org/hwmon/nct6775.html) ·
[nct6683](https://docs.kernel.org/hwmon/nct6683.html) ·
[it87](https://docs.kernel.org/hwmon/it87.html) ·
[asus_ec_sensors](https://docs.kernel.org/hwmon/asus_ec_sensors.html) ·
[asus_wmi_sensors](https://docs.kernel.org/hwmon/asus_wmi_sensors.html) ·
[k10temp](https://docs.kernel.org/hwmon/k10temp.html)

**Out-of-tree drivers:**
- [frankcrawford/it87](https://github.com/frankcrawford/it87) (AUR `it87-dkms-git`).
  The PRs and issues cited here: #27 (the PRIME X470-PRO is an IT8665E), #64 (secondary
  chip, closed 2025-12), #70, #79 and #115 (BIOS Full Speed), #81, #89 (X870E AORUS
  ELITE X3D, closed 2026-01-13), #96 (IT8689E Rev 1), #99 (IT8792 suspend/resume,
  open), #103 (X870E AORUS MASTER labels), #106 (IT8665E MMIO regression, closed, fixed
  by #120), PR #128 (Gigabyte control fixes, merged 2026-08-24), PR #132 (v2.0, chip
  rename, 2026-09-09). The [Hardware Compatibility Guide](19_Hardware_Compatibility.md#sources)
  lists them with dates.
- [Fred78290/nct6687d](https://github.com/Fred78290/nct6687d) (AUR `nct6687d-dkms-git`)
- [branchmispredictor/asrock-nct6683](https://github.com/branchmispredictor/asrock-nct6683)
- [s25g5d4/nct6686d](https://github.com/s25g5d4/nct6686d)
