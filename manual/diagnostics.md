# System Health (Overview, System State, Hardware & Logs)

Four sidebar pages show the health of every part of the system:

- **Overview**: is the daemon healthy, what hardware did it find, and what are the
  sensors and fans doing?
- **System State**: the health report. What on this machine needs a response, and how
  do you fix it?
- **Hardware**: your cooling hardware, the daemon's readiness checklist, and the fan
  tests.
- **Logs**: what the app has been doing, and the alerts.

For help with a specific problem, start from the symptom on
[Hardware Troubleshooting](hardware-troubleshooting.md). The tests themselves are
explained on [Fan Tests and Reports](fan-tests.md).

## Overview page

![Overview page](https://raw.githubusercontent.com/Plan-B-Development/ventulus/main/screenshots/auto/03_overview.png)

The page opens with two cards, **Daemon Health** and **Device Discovery**, followed by
the **Fan Status** and **Sensors** tables. The two tables share whatever height the
window has spare; drag the handle between them to give one more room.

### Daemon Health

| Field | Meaning |
|-------|---------|
| **Daemon version** | Version of the running daemon and its API |
| **Status** | Overall health: "healthy", "warning", or "critical"; **disconnected** while the daemon cannot be reached, with uptime, subsystems and overrides blank until it is back |
| **Uptime** | How long the daemon has been running since it last started |
| **Subsystems** | The subsystems the daemon reports (`openfan`, `hwmon`, `engine` and `controls`), each with its status and age. With no OpenFAN controller the `openfan` line is left out; it reappears if that subsystem reports a fault, so a controller that drops off mid-session still shows |

**Age** is the time in milliseconds since the daemon last polled that subsystem. Under
1000 ms means the data is fresh; a high age means the daemon is having trouble
reaching that hardware.

### Device Discovery

| Field | Meaning |
|-------|---------|
| **OpenFan** | Whether an OpenFAN controller is detected, its channel count, and its write and RPM capability |
| **hwmon** | Whether motherboard fan headers are detected, how many, and whether they are writable |
| **AMD GPU** | Whether an AMD discrete GPU is detected, its model, PCI address, and fan control method (`pmfw`, or `pwm1` on an RX 6000 or older) |
| **Intel GPU** | Whether an Intel Arc discrete GPU is detected, its model and PCI address. Its fan is always `read_only (firmware-managed)`: the `xe`/`i915` drivers expose no fan control |
| **NVIDIA GPU** | Whether an NVIDIA discrete GPU is detected (through `nouveau` or the opt-in NVML backend), its model, driver and PCI address. Its fan is always `read-only`: `nouveau`'s writable `pwm1` (some cards older than Turing) is excluded for safety, and NVML is telemetry only. `nouveau` publishes no sensors on Turing and newer cards, so such a card is detected only through NVML |
| **Liquid cooling** | Whether a liquid cooler (AIO) is detected through hwmon, and whether its pump and fan are writable, monitor-only (a read-only driver such as NZXT Kraken2), or not detected. USB-only coolers without a kernel driver show as not detected |
| **Features** | A summary of write capabilities (OpenFan writes, hwmon writes) |

### Sensors

An 8-column table of every temperature sensor the daemon reports (`#`, Label, Sensor
ID, Source class, Chip, Value, Age, Confidence). A summary line above it answers "is
anything wrong?" at a glance:
`Sensors: N total · X CPU · Y board · R memory · Z GPU · V liquid · W disk · K stale · J low-confidence · U unavailable · M hidden`.

| Column | Meaning |
|--------|---------|
| **#** | Row number |
| **Label** | The label from the kernel driver (for example "Tctl", "edge"). Prefixed `⚠ ` for a sensor with a documented bogus reading (such as the ASUS NCT6776F `CPUTIN`) and `? ` for a low-confidence classification |
| **Sensor ID** | Stable identifier (for example `hwmon:<chip>:<dev_id>:<label>`), the id a profile uses to bind a curve to the sensor |
| **Source class** | Fine-grained classification from the sensor knowledge base (`cpu_die`, `vrm`, `board_thermistor`, `gpu_package`…) |
| **Chip** | The kernel driver or chip providing the reading (`k10temp`, `nct6798`, `amdgpu`, `xe`…) |
| **Value (°C)** | The current temperature. Suffixed `⚠ ALARM` when the live value has reached the sensor's reported critical threshold. The chip's own alarm bits are read only when the daemon starts, so the detail dialog lists them as *(at daemon start)* |
| **Age (ms)** | Time since the daemon last read this sensor |
| **Confidence** | How sure Ventulus is about what the sensor measures: `high`, `medium`, `low` or `unknown`. Lower confidence usually means the chip has known quirks |

The `K stale` count is the quick check for sensors that have stopped updating. The
daemon source, kind, driver type, trend and freshness are in each row's detail dialog
(trend also shows in the hover tooltip).

#### Unavailable sensors

Some sensors exist but cannot be read: the classic case is a Wi-Fi radio's
temperature (an `ath12k` chip), which returns "Network is down" while the radio is
off. These are listed as **unavailable** in a small panel below the table, each with
its label, the read error and how long it has been unavailable, and counted as
`· U unavailable` in the summary line. The panel is hidden when there are none.
Because such a sensor can vanish the moment its device powers down, it is **never
offered as a curve sensor** (a curve already bound to one keeps working). It
reappears in the table by itself once it can be read again.

#### Sensor detail dialog

Double-click a row, press **Enter** on it, or right-click → **Open detail…**. A strip
at the top shows the current value, age, freshness, trend, session range and headroom
to critical, and updates every second while the dialog is open. Below it are the full
classification description and every note, board context, a **Thresholds** section, a
link to the kernel driver's documentation, and the daemon's own classification (class,
confidence and reasoning) beside Ventulus's.

#### Hiding sensors and changing their classification

Right-click a row → **Hide sensor** to remove one you do not care about (a duplicate,
or a chip that always reads garbage). Hidden sensors collapse into a `▸ N hidden
sensors` row at the bottom; click it, or select it and press **Enter**, to expand it again. The hide-list belongs to this
page; **Mirror hidden to dashboard** copies it to the Dashboard's chart selection once.

**Treat as coolant** forces a sensor to count as a liquid-cooling coolant temperature
when the automatic classifier is too cautious; **Reset classification to auto** undoes
it, and **Clear overrides** on the **Settings** page clears every one. The override is
a Ventulus preference only: it groups the sensor under *AIO / Liquid* on the
Dashboard, lets **Configure AIO** use it as the loop's coolant sensor (and seed its
curve for coolant temperatures), and stars it (★) in the curve editor. **It does not
arm the daemon's coolant emergency**, which acts only on sensors the daemon itself
classifies as coolant.

**Set as preferred CPU sensor** and **Set as preferred motherboard sensor** set the
same preference as the **Settings** page's *Preferred Sensors* card. It is advisory:
thermal safety always uses the hottest CPU sensor.

Hover any row for its source class, description and known driver quirks. For more,
see the [Sensor Interpretation Guide](../docs/20_Sensor_Interpretation_Guide.md) and
the [AMD Sensor Interpretation Deep Dive](../docs/22_AMD_Sensor_Interpretation_Deep_Dive.md).

### Fan Status

A live view of every fan output the daemon reports:

| Column | Meaning |
|--------|---------|
| **ID** | Display name: your name for it if you set one, otherwise the hardware label or fan id |
| **Source** | `openfan`, `hwmon`, `amd_gpu`, `intel_gpu` or `nvidia_gpu` |
| **Control method** | How the fan can be controlled: `openfan`, `hwmon` (PWM-only or full read/write), `amd_gpu` (firmware curve; or *verify only (legacy pwm1)* on an RX 6000 or older, which can be tested and reset but not driven by a profile), `read_only`, or `unknown` |
| **RPM** | Hardware-measured speed (a dash if unavailable). A writable header reading 0 RPM is marked `(no fan detected)` |
| **PWM (%)** | Last commanded speed (a dash if none) |
| **Freshness** | "fresh" (under 2 s), "stale" (2–10 s, yellow) or "invalid" (over 10 s, red) |

Hover any cell for what the value means and, for a read-only fan, why it cannot be
driven.

## System State page

![System State page](https://raw.githubusercontent.com/Plan-B-Development/ventulus/main/screenshots/auto/04_system_state.png)

The health report. It renders the daemon's hardware diagnostics, which Ventulus
fetches in the background at startup so the page has its answer ready. **Refresh**
on the page, or **Rescan Hardware** in the footer, takes a new snapshot; until you do,
a problem you have just fixed is still reported.

| Section | What it tells you |
|---------|-------------------|
| **System Health Overview** | A pill reading **SYSTEM READY**, or **N ACTION REQUIRED** in amber (red when one is critical), and a summary line: how many PWM headers were found and how many are writable, then your board's vendor, model and BIOS version as the firmware reports them (for example `Gigabyte Technology Co., Ltd. — X870E AORUS MASTER — BIOS F14c`) |
| **Conditions** | One card for each problem the daemon has observed on this machine, with its fix |
| **Board notes for this hardware** (collapsed) | Documented quirks for your board and chip, with what this machine says about each |
| **Hardware Registry** | Each detected Super-I/O or sensor chip: status, chip, driver, driver status, whether the driver is in the mainline kernel, and its PWM header count. Hover a row for the chip's known issues |
| **Interference Monitor** | Per-header reclaim counts, any duty the daemon had to correct, and other fan-control software on this machine |
| **Safety & GPU Limits** | The **CPU Thermal State** row, a row per AMD discrete GPU, kernel advisories, and the firmware's fan speed range |
| **Advanced actions** (collapsed) | Fan and GPU tests, and **Restore GPU Fan to Automatic** |

**Refresh** and **Open Full Report ↗** sit on the System Health Overview header. *Open
Full Report* opens the whole report, *System Health — Full Report*, in its own
resizable window with every link clickable. It always contains every condition and
note, including ones you dismissed, so it is the complete record for support. Its
thermal state is the live one the **Safety & GPU Limits** card shows, and it follows
that card while the window is open.

### Conditions

One card per problem the daemon has actually observed, each with a severity badge, a
one-line fix, and a link to the relevant documentation:

- a Super-I/O chip that did not appear (the dual-chip warning; see
  ["Some of my fan headers are missing"](hardware-troubleshooting.md#some-of-my-fan-headers-are-missing--only-5-of-8-show-up));
- a *Driver module collision* or *Conflicting driver modules loaded*;
- *BIOS/EC reclaiming fan control*;
- every PWM header read-only, or no hwmon chips at all;
- a GPU with fan control disabled or unavailable;
- **Fan duty is not holding**: something other than Ventulus keeps changing that
  fan's speed, usually the board's own fan control or another fan program. The daemon
  puts the duty back each time; after three corrections in a row that do not hold, it
  stops fighting and this card appears, naming the fan. Corrections that did hold are
  not a warning; they show as a count in the Interference Monitor.
- **Fan speed cannot be set**: the daemon's last writes to that fan, a motherboard
  header or an OpenFAN fan, all failed, so it may not be at the speed Ventulus chose
  and a thermal emergency cannot speed it up either. The daemon's journal names the
  error ([A fan's speed shows, but the fan cannot be controlled](hardware-troubleshooting.md#a-fans-speed-shows-but-the-fan-cannot-be-controlled)).
  The card clears once a write lands.
- **Header was already in manual mode**: something had set that header to manual mode
  before Ventulus first took it, usually another fan program. Ventulus gives every
  header back as it found it, so when it stops it leaves this one in manual mode at
  the speed it had, not to the BIOS. Stop and disable the other program, then reboot
  ([Migrating § Check that nothing still holds a header](migrating.md#check-that-nothing-still-holds-a-header)).
  Restarting the daemon does not clear it, because the stop puts the header back in
  manual mode. If the card is back after the reboot with nothing else running, your
  board starts that header in manual mode itself, and nothing needs doing.

A healthy system shows a single *No active conditions — fan control is available*
line, and the pill reads **SYSTEM READY**. Conditions clear themselves: fix the cause,
refresh, and the card is gone.

**CRITICAL means a risk of damaging hardware.** Today only one condition is critical:
the out-of-tree `nct6687` driver claiming an NCT6797D or NCT6798D chip, which has
bricked a CPU_FAN header in the wild. Everything else, including losing fan control
entirely, reads **ACTION REQUIRED**.

### Board notes for this hardware

A collapsed section below the conditions holds the documented quirks for your board
and chip: BIOS settings to change, drivers to install, known issues. They match on
which motherboard you own rather than on anything your machine is doing, so they are
reference material, not alarms, and they never clear by themselves. Currently
surfaced quirks include Smart Fan 6 BIOS notes for Gigabyte AM5 800-series AORUS
boards (IT8696E), and the usual driver paths and ASUS WMI sensor helpers for NCT6798 /
NCT6799 on ASUS. The vendor workarounds are in
[Hardware Compatibility § Manufacturer quirks](../docs/19_Hardware_Compatibility.md#manufacturer-quirks),
and the [AMD](../docs/21_AMD_Motherboard_Fan_Control_Guide.md) and
[Intel](../docs/23_Intel_Motherboard_Fan_Control_Guide.md) guides go board by board.

Each note is its own row, most severe first, with a badge that pairs an icon, a word
and a colour: **CRITICAL** (red), **HIGH** (orange), **MEDIUM** or **LOW** (amber),
**INFO** (blue). **Details** opens the full explanation and a link to the Hardware
Compatibility Guide; CRITICAL and HIGH notes, and anything confirmed on your machine,
start open. Each note also says what this machine says about it:

| Evidence | Meaning |
| --- | --- |
| *observed on this system* | Confirmed here. The note is raised as a condition, or explains one that is already there |
| *not present on this system* | Measured and refuted: the collision or missing chip it describes is not here |
| *not yet verified on this system* | Neither confirmed nor refuted. Most of these describe the BIOS quietly ignoring PWM writes, which only a write to a header can settle: use **Test fan control** in this section. It runs the same test as **Verify All Writable** under Advanced actions and shows its progress and result below the button. Like that button, it is unavailable while another test or a PWM Test Report is running. The evidence is the daemon's own per-header test results, so a test run from the **Hardware** page, the PWM Test Report or a validation session counts too, and a header whose latest result failed keeps the note *observed* until that header passes. A header with no tachometer reports *no tach*, and a test whose read-back failed reports *no readback*; neither settles anything or overwrites a result you already have |
| *reference for this hardware* | Nothing on this machine could confirm or refute it (for example, a note about a sensor driver that is never the fan-control path) |

### Acknowledge and Dismiss

Every warning on this page (conditions, board notes, the Interference Monitor, the
CPU thermal row, the GPU advisories and the GPU rows on Safety & GPU Limits) can be
quietened:

- **Acknowledge** greys the item and marks it *Acknowledged* for this session. It
  stays in place and in order, so you can still read it.
- **Dismiss** hides it until you restore it from **Settings → Prompts & Dismissals**,
  where you can also turn the buttons off altogether.

Neither can silence a real problem. The **N ACTION REQUIRED** count keeps counting
quietened conditions, and a line under the list says how many are hidden, so the page
never claims your system is ready while fan control is broken. A silence is recorded
against what the machine said at the time: it comes back if the problem is later
confirmed or gets worse (dismiss a driver collision for one pair of modules, and a second
pair speaks again; BIOS-reclaim warnings come back if contention climbs into the HIGH
band). It does *not* come back when things improve: dismiss a note, run **Test fan
control**, and a clean result leaves it dismissed.

Quietening the cards on the right **demotes rather than deletes**: the reclaim gauge
keeps its count and the thermal row keeps its state and your CPU's emergency limit;
they stop being coloured as alarms. Dismissing a GPU row does not dismiss the matching
condition card, which carries the fix. A reading that is not warning you, such as
**Zero-RPM: available**, has no buttons, and neither does the Hardware Registry. A real
thermal emergency still reaches you through the banner, the footer and the status
ribbon, which nothing here can silence, and the daemon protects the hardware whatever
any of them shows.

### Hardware Registry, Interference Monitor, and Safety & GPU Limits

The **Hardware Registry** takes about three quarters of the page's second row; drag
the divider on its right to resize it. The *Driver Status* column shortens long text
to keep every column on screen; hover it for the full wording.

The **Interference Monitor** carries the BIOS-reclaim gauge and names the contended
header. Once an hour has passed with no reclaim, the warning stands down and the card
reads **Past Interference**, keeping the count as a record. What the counts mean, and
what to do about them, is in
[The BIOS keeps taking fan control back](hardware-troubleshooting.md#the-bios-keeps-taking-fan-control-back).

Below the gauge, the card names any other fan-control program it finds: the
services of fancontrol, CoolerControl, fan2go, thinkfan and LACT that are running or
start at boot, a `fancontrol` started by hand, and a `fancontrol` that was killed
without putting its fans back. It reads them each time you open the page or press
**Refresh**, and **Migrating Guide** opens
[Migrating from Another Fan Program](migrating.md) when it finds one. A program
running now also turns a **No Interference Detected** heading into **No BIOS/EC
Reclaim Detected**, since it is interference too. CoreCtrl and your own scripts are
not on the list.

**Safety & GPU Limits** carries:

- the **CPU Thermal State**: live, from the same once-a-second poll that drives the
  banner and the footer (**Unknown — disconnected** while the daemon cannot be
  reached), with the emergency limit your CPU actually uses, or during a coolant
  emergency the coolant limit that tripped it;
- a row per AMD discrete GPU: fan control method, overdrive, the
  `amdgpu.ppfeaturemask` state firmware fan curves need, and the `amdgpu` binding.
  **Fan Control: read_only** is the normal state of an RX 7000/9000 card booted without
  `amdgpu.ppfeaturemask`. These are settings you may have chosen on purpose, so they
  can be quietened; change the setting and the row speaks again;
- kernel advisories (see
  ["A popup said my kernel has a known regression"](hardware-troubleshooting.md#a-popup-said-my-kernel-has-a-known-regression--should-i-worry));
- the firmware's fan speed range.

### Advanced actions

Collapsed by default: **Test PWM Control**, **Verify All Writable**, **Characterise
PWM Response**, and, when a writable AMD GPU is present, **Test GPU Fan Control** and
**Restore GPU Fan to Automatic**. Each is explained on
[Fan Tests and Reports](fan-tests.md). They are unavailable while one of them, or a
PWM Test Report, is running, because the daemon runs one test at a time.

**Restore GPU Fan to Automatic** hands the GPU fan back to the card's own curve, to
undo a static GPU speed without restarting the daemon. It is disabled, with the reason
in its tooltip, while the active profile drives that GPU: remove the GPU from its fan
role or deactivate the profile first. Afterwards the daemon leaves the fan alone, even
if a profile names it, until a profile is next activated or the daemon restarts. A
curve you then set in LACT or CoreCtrl stays, across daemon restarts too.

**Rescan Hardware**, in the footer, asks the daemon to look again for hwmon sensors
and PWM headers: use it right after loading a sensor driver. New sensors appear within
a couple of seconds. New fan *headers* need a daemon restart
(`sudo systemctl restart ventulusd`). An OpenFAN controller is the exception: the same
button asks the daemon to look for one and adopts it at once, and the result names the
port it was found on.

## Hardware page

![Hardware page](https://raw.githubusercontent.com/Plan-B-Development/ventulus/main/screenshots/auto/05_hardware.png)

Where you see, understand and test your cooling hardware. It has six sections: the
**Hardware Readiness Checklist**, **Recommended Actions**, **Cooling Hardware** (your
coolers and every PWM header), **Hardware Diagnostics** (the tests), the **Super-I/O
Architecture** report, and **Voltages**. **Re-scan**, at the top, asks the daemon for
a fresh hardware scan and reads the voltages again. The checklist and the Super-I/O
report come from one daemon request over one shared scan, so they never disagree.

Every readiness check is explained in full (what it means, why it fails, how to clear
it) in the [Cooling Hardware Readiness Guide](../docs/24_Cooling_Hardware_Readiness_Guide.md);
the page's *Learn how* links point there.

What the page *shows* is read-only. The tests under **Hardware Diagnostics** do
exercise your hardware, always inside the daemon, which keeps the pump floor and
thermal protection in force throughout. No action on this page can stop a pump or
drive a fan below its floor, with one exception you opt into: **Calibrate OpenFan
Channel…** walks the channel you pick down to 0 %, only after you confirm it powers no
pump, and never on a channel set to **Pump**.

### Hardware Readiness Checklist

The daemon's own assessment of your cooling hardware: *what is ready, what needs
attention, and what should I do next?* It fills in the first time you open the page,
or on **Re-scan**.

It answers a different question from the System State page, and neither gives a
verdict for the whole machine. This checklist asks *is this machine's hardware and
driver stack set up for fan control?*, from CPU-sensor presence, how confident the
daemon is in the default CPU sensor, whether PWM controls are present, read-only or
not yet verified, monitor-only fan tachometers, quarantined sensors, and any preferred
sensor that has gone missing. System State asks *what on this machine needs a response
right now?* A machine can be **HARDWARE READY** here and still have something on System
State that wants attention; the two are looking at different things, which is why the
verdicts use different words.

- **Verdict pill**: **HARDWARE READY** or **HARDWARE NEEDS ATTENTION**, at the end of
  the section's heading. It covers this checklist only.
- **Item checklist**: one card per item, most severe first, each with a severity chip
  (**CRITICAL** / **WARN** / **OK**), a one-line summary and, under **Details**, the
  technical detail, the recommended next step, and flags (*affects safety*, *blocks fan
  control*, *blocks monitoring*, *reboot may be required*). Warning and critical items
  open their detail by themselves.
- A healthy system shows *✓ All hardware-readiness checks passed.*

### Recommended Actions

The checklist items' next steps, gathered into one list from most to least urgent. A
**PWM control test** action scrolls to this page's **Hardware Diagnostics** section.
GPU-fan verification and **Verify All Writable** are on System State, reachable from
the **Advanced (System State)** button in that section.

### Cooling Hardware

*What cooling hardware do I have, and what is it doing right now?*

**Cooling devices.** A pump and its radiator fans grouped by **Configure AIO…** on the
Controls page appear here as one assembly: pump, radiator fans, control sensor, pump
strategy, coolant readings and an overall status, with live RPM and PWM beside each
member. Its buttons jump to the headers, characterise the pump, start a validation
session, edit the configuration, or **Forget Device**, which removes only the
*grouping*: your headers, their roles and the pump floor are unaffected, and no fan
changes speed.

**PWM headers.** Every header gets a card with its name, role, live RPM and, kept
apart on purpose, the PWM the daemon **requested** and the PWM the hardware **reports
back**. Those two numbers are what tell a failed write from a BIOS reclaim from a
device doing its own control. **Details** adds the engineering view: chip and channel,
the kernel label, the capability audit (PWM write, readback, `pwm_enable`, supported
control modes, PWM/DC mode, base frequency, tach pulses, alarm state, reclaim count),
and the safety block: role, where the role came from, the safety floor, and whether
stopping the fan is prohibited.

A few things read **Unknown** on most boards, and that is normal: the supported
control modes are known only for `it87` and `nct6775` chips, and many boards expose no
PWM frequency or tach-pulse count. A driver that stays silent is not a driver saying
no, so the page says *Unknown* rather than *Unsupported*.

#### Setting a header's role

**Set role…** beside each card's role says what the header drives:

- **Pump**: never stopped, and held at or above the pump floor.
- **CPU fan**: held at or above the CPU-fan floor in the active profile, as a header
  whose own label names the CPU fan is. It is not a pump, so fan identification still
  stops it.
- **Chassis fan** or **Radiator fan**: no floor. This is what makes the PWM Test
  Report's stall/restart probe available on the header.
- **No fan**: nothing is plugged in, so the card is dimmed and reads *No fan* instead
  of warning about a missing RPM. It adds no floor.
- **Not set** removes your assignment.

Only your assignment changes. A role that comes from the hardware label stays
underneath it, so **Not set** returns the header to that role, and a header the daemon
protects as a pump (from its label, or because the active profile names it a pump)
stays protected whatever you choose. Removing a pump you assigned asks first and names
the protection being removed, unless the header's own label or cooler channel keeps it
protected anyway, in which case nothing is lost and nothing is asked. The message afterwards appears on the card and reports
the daemon's answer, not what was asked for. The button is disabled on a read-only
header, and stays available while a PWM Test Report runs, because the daemon checks
roles again at every step.

#### OpenFAN channels

An OpenFAN channel has no hardware label, so the daemon cannot tell that a pump is
plugged into one until you say so. *OpenFan Channels*, under the PWM headers, lists
every channel the controller reports, and any channel you gave a role while it is
unplugged, each with **Set role…**. **Pump** keeps the channel at or above the pump
floor in every profile, makes fan identification change its speed instead of stopping
it, and keeps **Calibrate OpenFan Channel…** off it. **CPU fan** keeps it at or above
the CPU-fan floor in the active profile, but identification still stops it. The other
roles change only the name shown.

#### Labels from the nct6687d driver on a non-MSI board

The out-of-tree nct6687d driver gives MSI's fan names (`CPU Fan`, `Pump Fan`,
`System Fan #1`…) to every board it runs on. On another vendor's board (an ASRock
Taichi is the known case) its "Pump Fan" can be a case-fan header, while the real pump
sits on a header with no name and no pump protection. Such a header's card says
**Label unverified**, and a note above the PWM headers asks you to use **Set role…** on
the header your pump is on. The note goes once you assign a pump, or when you choose
**Labels are correct**, which is remembered for this machine (restore it under
**Settings ▸ Prompts & Dismissals**).

### Hardware Diagnostics

The tests, each disabled with the reason in its tooltip when your hardware cannot run
it. Each is explained on [Fan Tests and Reports](fan-tests.md):

- **PWM Test Report…**: the whole-machine assessment. While it runs, every other test
  here and on System State is unavailable.
- **Calibrate OpenFan Channel…**: where an OpenFAN fan stops, where it starts again,
  and the minimum that keeps it running.
- **Update OpenFAN Firmware…**: installs a firmware file onto the controller; see
  [OpenFAN Controller](openfan-controller.md#updating-the-openfan-firmware).
- **Test Control**, **Characterise** and **Discover Control Path** on each header
  card, and **Characterise Pump** on a cooling-device card.
- **Startup / Lifecycle Recording**, **AIO Validation** and **Thermal Observation**:
  the recording sessions.

### Super-I/O Architecture

*Which motherboard sensor and fan chip do I have, and is its driver loaded?* Most
desktop boards route their fan headers and temperature sensors through a Super-I/O
chip (ITE, Nuvoton/Winbond, SMSC…); if its driver is not loaded, the daemon cannot see
those fans. The section shows one card per detected chip: vendor, a confidence level,
how it was detected (the board table, the kernel log, an already-bound driver, or the
opt-in port probe), and whether its driver is bound. For a chip whose driver is not
loaded, **How to enable** gives the driver name and a command to load it. When the
driver is not part of the kernel, it also gives the commands that build and install it
on the distribution the GUI runs on (Arch, Debian and Ubuntu, Fedora, or upstream's
generic steps elsewhere), the commands that update it later, and how to sign it when
Secure Boot is on. If the driver is already loaded but found no chip, the update
commands come first.

- The report is **passive and read-only**: the daemon combines signals it already has
  (the board table, bound hwmon chips, `/proc/modules`, the kernel log). It never
  loads a module or changes your system.
- **Detection is not control.** A card means a chip is present and a driver exists,
  not that fan control works. Loading the driver, and a fan test, confirm that.
- On a non-x86 machine the section says detection is unavailable.

#### Probe ports (advanced)

Passive detection cannot see a chip whose driver never loaded and that never appeared
in the kernel log. For that, an **opt-in active probe** reads the Super-I/O
configuration ports directly. **Probe ports (advanced)** runs it, but it is **off by
default** and disabled (with the reason in its tooltip) unless the daemon's operator
has turned it on, because it needs a root-equivalent capability (`CAP_SYS_RAWIO`). To
turn it on:

1. Set `allow_port_probe = true` **under the `[detection]` table** in
   `/etc/ventulus/daemon.toml`.
2. Install the drop-in the daemon package ships as an example:
   ```bash
   sudo install -Dm644 /usr/share/doc/ventulusd/superio-port-probe.conf.example \
     /etc/systemd/system/ventulusd.service.d/superio-port-probe.conf
   ```
3. Reload and restart: `sudo systemctl daemon-reload && sudo systemctl restart ventulusd`.

**The probe is not read-only.** Where no chip answers a plain read, the daemon writes a
vendor unlock and exit sequence to the port. On some boards that can hide a chip until
the machine is unplugged from mains power, which is why the drop-in's comments and the
button's confirmation both spell it out. It never writes a configuration value.

**It refuses to run while any Super-I/O driver it recognises is bound**, for the whole
probe, not just that driver's port. With `it87` loaded on a dual-chip Gigabyte board it
therefore never runs. It also refuses when `/proc/ioports` cannot be read, skips a port
that a driver or the firmware has reserved, and turns away a second run within 10
seconds. Each refusal appears as a note in the section.

### Board layout

Shown on Gigabyte boards whose driver publishes the board's firmware layout (the
SIV). It gives the layout code and CPU platform, whether the it87 project lists your
board model for that layout, how many fan headers, fans and temperatures the board
catalogue named, the catalogue's source and commit, and a table of every name with
the chip channel it belongs to. "Not mapped for this board" means the layout does not
map the channel, not that nothing is connected. See
[Board header names](hardware-troubleshooting.md#board-header-names-from-the-it87-catalogue)
for what the names do.

### Voltages

A read-only table of the analogue inputs your Super-I/O chip exposes, typically ten
per chip. The **Identification** column says who named each row:

- **Named by the driver**: the kernel driver labels a few of the chip's own internal
  inputs (`3VSB`, `Vbat`, `+3.3V`) and has already scaled them. Read these at face
  value.
- **Named by the board catalogue**: on Gigabyte boards, the daemon recognises the board
  from its firmware ID and names the other inputs from the it87 driver project's
  per-board sensor configurations, including each rail's divider. The reading shown is
  the rail voltage (the pin reading times the divider); hover the row for the pin
  reading and the divider. On an X870E AORUS MASTER, for example, `in2` reads about
  2 V at the pin and is shown as `+12V` at about 12 V.
- **Not mapped for this board**: the catalogue does not map this input for your board.
  It may be unconnected or unused, so the reading is the raw pin voltage and not a known
  rail.
- **Named by the board catalogue — reading out of range**: a `+12V`, `+5V` or `+3.3V`
  rail the catalogue named reads more than 10 % from its nominal voltage. The
  catalogue's divider may not fit your board, or the input is not that rail. Hover
  the row for the pin reading. It is shown, not alarmed on.
- **Unnamed channel**: nobody named it, which is normal on a board the catalogue does
  not cover.

**Do not read an unnamed channel as a rail voltage.** A board feeds each rail through a
resistor divider before it reaches the chip, and the driver cannot know the ratio. The
number is a real measurement *at the chip's pin*, not the rail's voltage: a +12V rail
commonly reads around 2 V there. An `lm_sensors` configuration under `/etc/sensors.d/`
applies the dividers for the `sensors` command only; the kernel driver never reads it,
so it changes nothing in this table.

The table leaves out two things that mislead on real hardware: **voltage alarm bits**
(on the reference board two channels raise their alarm while reading inside their own
limits) and **per-channel min/max**, which are usually driver defaults rather than
limits anyone set for your board.

Voltages are information only: they are never offered as a curve sensor, and nothing
in fan control reads them. They are not polled every second, because rails move by
millivolts: Ventulus reads them when it connects, on **Re-scan**, and when you refresh
or rescan on System State. The table says when its readings were taken ("Read at
14:03."), and if a Re-scan cannot read them it keeps the previous readings and says
why.

## Logs page

![Logs page](https://raw.githubusercontent.com/Plan-B-Development/ventulus/main/screenshots/auto/08_logs.png)

A live, filterable list of the app's events: daemon connect and disconnect, profile
activations and overrides, alerts starting and recovering, theme changes and the like.
It keeps up to 200 entries, discarding the oldest first.

The page works as *find it, then understand it*: a compact alert bar and an activity
strip across the top, the event list on the left, and an inspector on the right that
explains whichever event you select and also holds the diagnostic probes.

**Newest entries are at the top.** Repeated identical events collapse into one row with
a `×N` badge; the inspector says how many times it happened and when it started.

Three things look alike but answer different questions:

| Surface | Question it answers | Persistence |
|---------|---------------------|-------------|
| **Event Log** (this page) | *What has the app been doing this session?* | In memory only, capped at 200 |
| **Alerts** (this page) | *What is wrong right now, and what was wrong a moment ago?* | An alert stops being active when its condition resolves, but stays listed as **recovered** until you acknowledge it, so one that cleared before you looked can still be read. **Acknowledge all** records that you have seen them; it does not claim anything is fixed, and never suppresses the same problem happening again |
| **System Journal** (inspector tab) | *What happened on the daemon side, across restarts?* | Kept by systemd |

### Activity strip

A row of columns above the list showing how many events arrived over time, coloured by
severity, so a burst of errors is visible without reading a line. Click a column to
narrow the list to that slice of time; click it again, press <kbd>Esc</kbd>, or use
**Clear time filter** to go back. It works from the keyboard too: <kbd>←</kbd>/<kbd>→</kbd>
to move, <kbd>Space</kbd> to apply.

The column heights count *events*, while the severity chips beside the search box count
*rows*. They differ whenever repeats have collapsed, which is what the `×N` badge shows.

### Alert bar

One line above the table. With nothing wrong it reads `✓ No active alerts`; if
something recently cleared without you seeing it, it adds
`Recent alert: … recovered at 09:21:06`.

When something *is* wrong it gives the counts and the most serious alert
(`✖ 1 critical   ⚠ 2 warnings`) and offers **View alerts**, which opens the **Alert
Centre**: every active alert with when it was first and last detected, where it came
from, a suggested next step where one can be given reliably, and **Acknowledge** /
**Show related logs**, plus a short list of what recently recovered.

**Acknowledging is not fixing.** It records that you have seen the alert. The footer's
health summary keeps reporting the condition while it lasts, and the same problem
happening again later always raises a fresh alert.

### Filters

| Control | Behaviour |
|---------|-----------|
| **All** | Turns every severity back on |
| **INFO / WARN / ERR chips** | Independent severity filters, each showing how many rows it holds. Turn all three off and the list is empty, which is a real state rather than a reset. The counts stay put when you turn a chip off, so you can see what turning it back on would bring |
| **Source dropdown** | One source at a time: `gui`, `polling`, `profile`, `kernel` and so on. New sources appear the first time they fire |
| **Search** | Case-insensitive match against the message text and source |
| **Follow** | Follows new entries as they arrive at the top. Scroll away and it pauses (the button turns off), showing `N new events ↑`; click either, or scroll back to the top, to resume. A pause you made with the button stays until you turn it back on. You are never pulled back while reading older rows |

Keyboard shortcuts while the list has focus: <kbd>↑</kbd>/<kbd>↓</kbd> to move,
<kbd>/</kbd> to jump to the search box, <kbd>f</kbd> to toggle Follow, <kbd>Esc</kbd> to
clear the selection.

### Inspector

The pane on the right. Selecting a row fills its first two tabs; the last two are
session tools that do not depend on the selection. Close it with **✕** to give the
list the full width; selecting an event brings it back.

| Tab | What it shows |
|-----|---------------|
| **Details** | Severity, the exact time, source and the full message. Where the event carried structured data (an alert's component, an exception type, a rescan's header count) it is listed as named fields; where it did not, nothing is shown. A repeated event also says how many times and since when. Below that, **related events** and one-click actions |
| **Raw** | The stored event record in full, selectable and copyable, as it was recorded |
| **Diagnostics** | Three on-demand probes, **Daemon Status**, **Controller (OpenFan)** and **GPU State**, each with its own **Refresh** |
| **Journal** | Recent entries from the `ventulusd.service` systemd journal, with **Fetch** / **Refresh** |

Diagnostics and Journal are fetched the first time you open their tab, so simply
visiting Logs never reads the system journal. Clearing the event log never wipes a
probe you just fetched.

#### Related events

An event that names a **component** (an alert about a particular fan or sensor, say)
lists other events about that component. Otherwise it falls back to other events from
the same source, and says so, because "same source" is a weaker claim than "related".
**Filter to these** narrows the list to that group. To jump to one, press **Enter** on
it or double-click it; on desktops that open items with a single click (KDE Plasma's
default), one click does it.

#### Actions

| Button | Action |
|--------|--------|
| **Copy event + context** | Copy the full record plus its related events |
| **Open Hardware / Open Controls** | Shown for events from a source with an obvious next place to look, and takes you there |
| **Clear Logs** (toolbar) | Empty the event log (the inspector's probes are kept) |
| **Copy** (toolbar) | Copy the rows currently visible, after filters, search and time window |

## Export Support Bundle

The footer's **Export Support Bundle** button, available on every page, builds one JSON
file and shows it to you whole before anything is written. **Save…** saves it
(`ventulus_support_bundle.json` by default), **Copy** puts the same text on the
clipboard, and **Close** discards it. It contains:

- the GUI version, your distribution's name and release (from `/etc/os-release`), your
  kernel release, the fan- and GPU-driver boot parameters (not the rest of the command
  line, which names your disks), and the loaded kernel modules;
- the fan drivers DKMS has built and for which kernels, from `dkms status`. Other DKMS
  modules (a graphics or network driver, say) are counted, not named;
- the app's event log, with any OpenFAN board serial number replaced by *(redacted)*;
- the daemon's version, capabilities and subsystem status, its thermal state and any
  emergency, pump stall or cooling advisory, its readiness summary, the sensors it
  cannot read and the controls it is not driving (by id: a control's name is your own
  text, so it stays out), and each fan's RPM and last reported duty, with, for each
  motherboard header, its control mode (`pwm_enable`), whether the daemon found it in
  manual mode, and whether its writes are failing (sensor readings are counted, not
  listed);
- each motherboard fan header the daemon found: its chip, the driver's label, whether
  it can be written, and its role;
- your settings, apart from window and chart layout, the export folder, and anything
  you typed as free text (your hardware and cooler notes, the Logs search box). It
  **keeps** machine-specific settings such as sensor classifications and the profile
  and theme folder overrides, because those are often the cause of a problem;
- the active profile's name, your profiles' names and ids (not their curves), and your
  theme names;
- your board, BIOS version and detected fan-control chips, and whether Secure Boot is on
  and the kernel loads only signed drivers, once the app has read them from the daemon;
- which of the fancontrol, CoolerControl, fan2go, thinkfan and LACT services are
  installed, whether each is running and starts at boot, and whether `fancontrol`'s PID
  file is there;
- the last 100 lines of the daemon's journal, with any OpenFAN board serial number
  replaced by *(redacted)*, and any `amdgpu` kernel messages from this boot (with the
  boot command line cut the same way).

The bundle is built in the background, so the window stays responsive while the journal
is read; after **Save…**, a banner says where the file was saved, or why it could not
be.

Read it before sharing: it names your hardware and may name your folders.

---

Previous: [Settings](settings.md) | Next: [Fan Tests and Reports](fan-tests.md)
