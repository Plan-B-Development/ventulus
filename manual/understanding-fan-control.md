# Understanding Motherboard Fan Control (hwmon)

This page explains, in plain English, *how* Linux controls motherboard fans and *why* the rest of this manual keeps mentioning things like hwmon, Super I/O chips, drivers, and BIOS settings. It is background reading. You do **not** need it to get fans working. The [Setup Checklist](setup-checklist.md) and the GUI's **System State** and **Hardware** pages do the actual work and tell you what your specific board needs. Read this when you want to understand *why* a step is being asked of you, or when something misbehaves and you want the mental model to troubleshoot it.

None of this applies to an [OpenFAN controller](openfan-controller.md) (a USB device with its own page) or to AMD GPU fans. It is specifically about the fan headers on your motherboard.

## The one-paragraph version

Your motherboard's fan headers are driven by a small dedicated chip (the **Super I/O** chip, or sometimes the board's embedded controller). Linux talks to that chip through a kernel driver, which exposes each fan as a handful of plain-text files under a system called **hwmon**. Ventulus's daemon reads and writes those files for you. Many boards work out of the box. Some newer ones need an extra driver loaded first, and the BIOS fan settings are worth a check, because the firmware still runs the fans at boot. That is the whole story. The sections below just expand each part.

## What is hwmon?

**hwmon** ("hardware monitoring") is the part of the Linux kernel that exposes sensors and fan controls (temperatures, fan speeds, voltages, and PWM outputs) in one uniform place. Every chip that can report a temperature or drive a fan shows up under hwmon once the kernel has a driver for it.

It is Linux's standard fan and sensor panel. Ventulus has no private way to reach your fans: it uses the same hwmon interface as `lm_sensors`, CoolerControl, fancontrol and every other Linux fan tool.

## What is sysfs (in this context)?

**sysfs** is a virtual filesystem (mounted at `/sys`) where the kernel presents hardware as files and folders. These are not files on your disk: reading or writing one of them is really talking to the kernel and the hardware behind it.

hwmon lives inside sysfs, under `/sys/class/hwmon/`. So when this manual says "the daemon writes a PWM value", it means the daemon writes a number into a file such as `/sys/class/hwmon/hwmon3/pwm1`, and the kernel passes it on to the fan chip. Fan control on Linux is mostly reading and writing small text files that the kernel maps onto real hardware, which is why drivers, permissions and *who else writes the file* all matter.

## The fan-control files

For each controllable fan header, the driver exposes a small set of files. You rarely touch these directly (Ventulus does), but recognising them makes every other page clearer:

| File | What it is | Why it matters |
|---|---|---|
| `pwmN` | The speed command for fan *N*, a number from `0` (stopped) to `255` (full speed) | This is the dial Ventulus turns. The GUI shows it as a percentage |
| `pwmN_enable` | The *mode* of the header: typically `2`/`5` = automatic (firmware decides), `1` = manual (software decides) | A header must be in manual mode before a `pwmN` write does anything. This is the file the BIOS most often steals back |
| `fanN_input` | The measured speed of the fan, in RPM | Read-only. This is the real, hardware-measured RPM the dashboard shows, never a value software set |
| `tempN_input` | A measured temperature, in thousandths of a degree Celsius (`45000` = 45 °C) | Read-only. Fan curves use these as their input |

A *writable* fan header is one where the driver lets the daemon set `pwmN` **and** hold `pwmN_enable` in manual mode. A header with a `fanN_input` (so you can see its RPM) but no writable `pwmN` is **read-only**: you can watch it but not control it.

## "AMD board" or "Intel board" is the wrong question

A common assumption is that fan control depends on whether you have an AMD or Intel CPU. It does not. The CPU vendor owns *temperature* sensors (`k10temp` for AMD, `coretemp` for Intel), but your **fans** are driven by a separate **Super I/O** chip soldered to the motherboard. That chip is made by ITE or Nuvoton (NCT), whichever CPU is in the socket. On some boards part of this job is handled by the board's **embedded controller (EC)** instead.

So which driver you need, and whether your fans can be controlled at all, depends on your **motherboard** and its Super I/O chip, not your CPU brand. A Gigabyte AMD board and a Gigabyte Intel board can need the same `it87` driver.

The vendor-by-vendor specifics live in their own reference pages, so this page does not repeat them:

- [AMD Motherboard Fan Control Guide](../docs/21_AMD_Motherboard_Fan_Control_Guide.md): Gigabyte, ASUS, MSI, ASRock notes
- [Intel Motherboard Fan Control Guide](../docs/23_Intel_Motherboard_Fan_Control_Guide.md): Intel LGA1700 / 1851 boards
- [Hardware Compatibility](../docs/19_Hardware_Compatibility.md): the full chip → driver matrix

## Why some boards are read-only until a driver is loaded

Super I/O chips sit on an old-style bus with no automatic "plug-and-play" announcement, so the kernel cannot always load the right driver by itself. If no driver is bound to your chip, hwmon simply does not show your motherboard fans, or shows their RPM but no writable `pwmN`.

Mainline Linux already includes drivers for many chips (for example `nct6775` covers a lot of ASUS boards). Newer boards (most 2022-and-later Gigabyte and MSI, some ASRock) use chips whose driver is **out-of-tree**: not shipped with the kernel, installed separately from its upstream project (on Arch, from the AUR) and rebuilt for your kernel by **DKMS**.

So "my motherboard fans don't show up" usually means the driver for your Super I/O chip is not loaded yet, not that your board is unsupported. The **Hardware** page identifies your chip and names the package to install. Installing a driver changes how your system loads modules, and some steps change how it boots: [Driver Setup](driver-setup.md) has each step, what it risks, and how to undo it.

## The pieces, and which one is Ventulus

Guides and forum answers mix up several kinds of software. Only some of them are needed, and only one should decide your fan speeds:

| Piece | Examples | What it does | Does Ventulus need it? |
|---|---|---|---|
| Kernel driver, part of the kernel | `nct6775`, `it87` (older ITE chips, the IT87952E from Linux 6.3 and the IT8689E from 7.1), `k10temp`, `coretemp`, `nzxt-kraken3` | Exposes a chip's sensors and fan controls under hwmon. It comes with the kernel and updates with it | Yes, for the chips it covers. There is nothing to install |
| Out-of-tree driver, built with DKMS | [`frankcrawford/it87`](https://github.com/frankcrawford/it87), [`nct6687d`](https://github.com/Fred78290/nct6687d) | The same job, for chips the kernel's own driver cannot drive. DKMS rebuilds it for every new kernel | Only where your chip needs one, and it needs looking after: see [Driver Setup § Staying current](driver-setup.md#staying-current) |
| Monitoring utility | `lm_sensors` (`sensors`, `sensors-detect`) | Prints what hwmon exposes; `sensors-detect` probes the hardware for chips | No. `sensors` is handy for cross-checking |
| Fan-control program | Ventulus, `fancontrol`, CoolerControl, fan2go, thinkfan, LACT, CoreCtrl | Decides each fan's speed and writes it to the kernel's fan controls | One per fan. Ventulus is one of these, so another must not drive the fans Ventulus drives |
| Tool that talks to a USB device directly | `liquidctl` on a cooler with no kernel driver | Reaches the device without hwmon | No. Ventulus reaches a cooler only through a kernel driver, so a cooler with none is invisible to it |

Ventulus itself is three parts: the daemon, `ventulusd`, which reads the sensors and writes the fans through hwmon; the app, `ventulus`; and on KDE Plasma the tray icon, `ventulus-tray`. The app and the tray only ask the daemon.

## Why the BIOS can fight Linux (Smart Fan / Q-Fan)

Motherboard firmware has its own fan controller. Gigabyte calls it Smart Fan, ASUS calls it Q-Fan, and others have similar names. When it is enabled, the firmware periodically rewrites the fan registers, flipping `pwmN_enable` back from manual to automatic. The result is the classic symptom: *Linux says the fan is at 50%, but it keeps running at full speed.*

Usually no BIOS change is needed: a current driver takes each header over, and the daemon puts a header back into manual mode whenever the firmware takes it. Where a board keeps taking a header back, the remedy is per vendor (a driver update on Gigabyte, a driver option on some MSI boards) and is in the [Driver Setup BIOS step](driver-setup.md#step-5--bios-settings-the-half-people-skip) and the vendor guides above. Setting a header to *Full Speed* in BIOS is a fail-safe, not a fix: the fan runs at 100% whenever the firmware owns it, and on some boards Linux can then not control it at all.

On some boards a correctly installed driver still loses to the BIOS. [Test PWM Control](fan-tests.md#test-pwm-control) catches exactly this: it reports when the BIOS took control back during the test.

## Why only one tool should control a header at a time

`pwmN` and `pwmN_enable` are single values, and the **last writer wins**. If two programs both drive the same header (say Ventulus and a leftover `fancontrol` service), they overwrite each other every second and the fan oscillates.

So pick one fan controller per header. Before letting Ventulus manage your fans, stop other fan software (fancontrol, CoolerControl, fan2go, and GPU tools like LACT / CoreCtrl for GPU fans). The [Setup Checklist](setup-checklist.md#step-5--stop-competing-fan-control-software) lists the usual suspects and how to disable them, and [Migrating from Another Fan Program](migrating.md) covers a full switch, including which of the old program's drivers to keep.

## Why DKMS, Secure Boot, kernel headers, and boot parameters can matter

These come up only on some systems, and the [Driver Setup](driver-setup.md) page walks through each with commands. In brief:

- **DKMS** rebuilds an out-of-tree driver every time your kernel updates, so the driver keeps working after upgrades.
- **Kernel headers** matching your *running* kernel are what DKMS builds against. A mismatch is the most common reason a driver "installs" but never loads.
- **Secure Boot**, when enabled, makes the Debian, Ubuntu and Fedora kernels refuse unsigned out-of-tree modules (Arch and CachyOS kernels refuse them only when you have set that up yourself): the driver builds but is rejected at load time. The fix is to enroll the key DKMS signs the driver with; turning Secure Boot off is the last resort.
- **Boot parameters** (the kernel command line) are needed in one specific case: AMD **GPU** fan control on RDNA3+ cards needs `amdgpu.ppfeaturemask=0xfff7ffff` (any mask with bit `0x4000` set works). Motherboard fan control needs no boot parameter.

Most boards need none of these. When one *is* needed, the **System State** page says so, and Driver Setup has the steps, including how to undo them.

## How Ventulus removes the guesswork

You do not have to discover any of the above by hand. By design, the daemon, `ventulusd`, owns all hardware access: it reads your hwmon chips, evaluates fan curves, and is the **only** component that writes PWM. The GUI, `ventulus`, is a client. It shows you what the daemon sees and lets you author profiles and run tests. The GUI never writes to a fan directly.

Four GUI features turn the concepts above into concrete answers:

- **The System State page** names your board and Super I/O chips, says which driver each chip needs and whether it is loaded, counts writable headers, and flags BIOS interference. Start here.
- **The Hardware page's Hardware Readiness Checklist** is the daemon's own go/no-go answer to "is this machine set up for fan control?", with the next step for anything that is not ready.
- **Test Control**, on each header's card on the **Hardware** page, writes a known value to that header, waits a few seconds, and reports what actually happened: control works, the BIOS reverted it, or the value was ignored. This is how you confirm a header is genuinely controllable instead of guessing.
- **Rescan Hardware**, in the footer, re-checks the hardware after you load a driver or change a BIOS setting.

[System Health](diagnostics.md) explains each part of these pages, and [Fan Tests and Reports](fan-tests.md) each test.

## What keeps your machine safe

The daemon looks after cooling safety by itself, whether or not the app is open and
whatever your profile asks for. None of it can be turned off; the only setting is the
coolant limit. Every forced speed is a **minimum over your profile**: a fan your curve
already runs faster keeps its speed, so these rules can raise a fan but never lower one.

- **CPU emergency.** If the hottest CPU sensor reaches the emergency limit, every
  OpenFAN channel and every writable motherboard fan header goes to 100 %, including
  fans no profile controls. The limit is at least 105 °C. Where the kernel reports the
  CPU's own design ceiling, the daemon raises the limit to that ceiling plus 5 °C,
  capped at 115 °C, because a modern CPU is *meant* to sit at its ceiling under load.
  **System State** shows the limit this machine uses. The emergency holds until a
  *current* CPU reading is 80 °C or below; a sensor that stops updating or disappears
  keeps it on. One reading at the limit is enough to start it, and the daemon never
  decides afterwards that the reading was wrong, so a faulty sensor stuck high keeps
  the fans at 100 % (see
  [Hardware Troubleshooting](hardware-troubleshooting.md#fans-run-at-full-speed-regardless-of-profile)).
- **Coolant emergency.** If a coolant sensor the daemon recognises (an AIO or
  custom-loop coolant temperature) reaches the coolant limit, the same happens until a
  current coolant reading is 5 °C below the limit. The limit is 60 °C unless you change
  it in **Settings** (40–70 °C). A machine with no coolant sensor is unaffected, and a
  sensor you only *treat as coolant* in the app does not arm it.
- **Missing CPU sensor.** If there has been no current CPU reading for 5 seconds and no
  emergency is under way, the fans your active profile controls are held at 40 % or
  more. Fans no profile controls are left to the motherboard's own curve, which reads
  its own sensor. If the last reading before the sensor went quiet was 80 °C or more,
  your curves simply keep running on it.
- **Frozen sensors.** Any other sensor that drives a curve and stops updating stops
  driving it: the fans it controls hold their speed rather than follow a temperature
  that is no longer real. They are never dropped.
- **Pumps.** No curve, override or test drives a pump below 30 %, or 70 % on a
  motherboard header the kernel reports in DC (voltage) mode, and fan identification
  shifts a pump's speed instead of stopping it. A CPU fan in a profile is held at 30 %
  or more too. The daemon knows a header drives a pump from its label, from the role
  you give it, or from the active profile naming it a pump; on a board that publishes
  no fan labels, give it the role yourself (**Set role… ▸ Pump** on the **Hardware**
  page). A pump in your profile that has been spinning and then reads 0 RPM for 10
  seconds is driven to full speed for 30 seconds to restart it, and stays at full
  speed if it still does not turn.
- **A CPU at its ceiling.** A modern CPU slows itself down at its own ceiling, which is
  below the emergency limit, so a stopped pump usually shows up as a hot, slow CPU
  rather than as an emergency. If the CPU sits at its ceiling for a minute while no fan
  or pump runs at 50 % or more, you get a warning. It forces nothing.
- **GPU fans are left to the GPU.** There is no GPU emergency: AMD's firmware protects
  the card by slowing it at its own temperature limit. A GPU fan in your profile keeps
  following its curve throughout.
- **When the daemon stops,** it gives every motherboard header back to exactly what it
  was doing before (usually the BIOS's own fan control), and every GPU fan it drove
  back to the card. The hand-back runs again after the daemon has exited, even after a
  crash. OpenFAN fans and headers with no automatic mode have nothing to go back to, so
  a clean stop leaves them at their last speed or the **exit minimum** (50 % unless you
  change it in **Settings**), whichever is higher; after a crash they keep their last
  speed until the daemon is back.

Whenever one of these is acting, the footer's thermal chip, a banner on the Dashboard
and an alert say so. The daemon's
[User Guide](https://github.com/Plan-B-Development/ventulusd/blob/main/docs/USER_GUIDE.md#safety)
has the full operator-level detail.

## Where to go next

- [Setup Checklist](setup-checklist.md): the ordered path that puts all of this into practice
- [Driver Setup](driver-setup.md): copy-paste driver install, Secure Boot, BIOS, and rollback
- [Hardware Troubleshooting](hardware-troubleshooting.md): from a symptom to its fix
- [Fan Tests and Reports](fan-tests.md): every fan test and what its results mean
- [Hardware Compatibility](../docs/19_Hardware_Compatibility.md): full chip and driver matrix
- [Sensor Interpretation Guide](../docs/20_Sensor_Interpretation_Guide.md): what each temperature sensor means
- [AMD](../docs/21_AMD_Motherboard_Fan_Control_Guide.md) / [Intel](../docs/23_Intel_Motherboard_Fan_Control_Guide.md) fan-control guides: vendor-by-vendor depth

---

Previous: [Driver Setup](driver-setup.md) | Next: [OpenFAN Controller](openfan-controller.md) | Back to [Table of Contents](README.md)
