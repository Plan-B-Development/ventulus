# Setup Checklist — Sensors & Fan Control

This page is the **ordered path** from a fresh install to verified, working fan control: install → sensors → readiness → drivers/BIOS → verify → first profile. Do the steps in order. Each one links to a deeper page for the detail. Ventulus is packaged for Arch Linux and its derivatives, Debian 13, Ubuntu 26.04 and Fedora 44 and 45; where a command differs between them, the linked page gives each one.

New to how Linux fan control works? [Understanding Motherboard Fan Control](understanding-fan-control.md) is a short, plain-English primer on the concepts this checklist puts into practice (hwmon, Super I/O chips, drivers, and BIOS settings). It is optional background: you can follow the steps below without it.

**A clean install, or a switch from another program?** If no other fan-control program has run on this machine, follow the steps in order. If one has (`fancontrol`, CoolerControl, fan2go, thinkfan, or a GPU tool such as LACT or CoreCtrl), start with [Migrating from Another Fan Program](migrating.md): it says what to keep, what to stop and how to check that Ventulus has taken over, and links back here for the steps the two share. Keep any motherboard driver you installed for the old program, such as an `it87` or `nct6687d` DKMS package: Ventulus uses the same kernel drivers.

> **Before you start.** Some steps link to pages that install third-party kernel
> modules, change UEFI/BIOS settings or kernel boot parameters, or change how fans
> behave. Done wrong, these can stop the system booting or let it overheat.
> [Driver Setup](driver-setup.md) says what each change risks and how to undo it.
> Where this guide conflicts with your hardware vendor's or distribution's
> documentation, prefer theirs. The manual's [notice](README.md) applies throughout.

## Step 0 — What "working" looks like

You are done when all of these are true:

- The [Dashboard](dashboard.md) shows live CPU (and, if present, GPU / motherboard / drive) temperatures.
- Your fans appear in the dashboard fan table and on [the Overview page](diagnostics.md) with RPM readings.
- The **System State** page reports a non-zero *writable* header count (or an OpenFAN / AMD GPU fan with a write path).
- **Test PWM Control** (and **Test GPU Fan Control** if you have an AMD GPU) reports that control is working.
- A profile is active and the fans respond when temperatures change.

## Step 1 — Install the daemon and GUI

Add the signed repository for your distribution (pacman, APT or DNF), install
`ventulus` (it pulls in `ventulusd`), and make sure the daemon is enabled and
running. [Getting Started](getting-started.md#installation) has the commands for
each distribution, and the other ways to install. From then on both packages
upgrade with the rest of your system (`sudo pacman -Syu`, `sudo apt upgrade` or
`sudo dnf upgrade`).

Then reboot, or load the sensor drivers and restart the daemon as
[After installing](getting-started.md#after-installing) shows. Until you do, your
motherboard's fans and temperatures can be missing from Step 2 on.

## Step 2 — Verify sensors first

Fan control depends on temperatures: the readiness checks, fan curves, and the daemon's thermal safety all need a working CPU sensor before any fan work matters. (Sensors-before-fans is the same order the [Arch Wiki fan-speed-control flow](https://wiki.archlinux.org/title/Fan_speed_control) uses.)

Launch the GUI and check:

- **Temperatures visible** on the Dashboard and on the **Overview** page? Continue to Step 3.
- **Missing or fewer than expected** (no CPU temperature, no motherboard temperatures, no drive temperatures)? → [Sensors missing or fewer than expected](hardware-troubleshooting.md#sensors-missing-or-fewer-than-expected), then come back here.

## Step 3 — Read the health report

Open the **System State** page (the daemon's hardware snapshot is fetched in the background at startup; **Rescan Hardware**, in the global footer, re-runs it) and read the **System Health Overview**: how many PWM headers were found and how many are writable, and a card for each issue. [What each section of the page means](diagnostics.md#system-state-page). The **Hardware** page's **Hardware Readiness Checklist** gives the daemon's own go/no-go answer beside it.

Everything Ventulus found is on these pages:

| To see | Look at |
|---|---|
| Temperatures | The Dashboard, and **Overview ▸ Sensors** |
| Fan speeds (RPM) | **Overview ▸ Fan Status** |
| Fan headers, and which ones Ventulus can write | **Hardware ▸ Cooling Hardware**; the counts are in the System Health Overview |
| Your board, its fan chip and the chip's driver | The System Health Overview and **Hardware Registry** on System State, and **Super-I/O Architecture** on the Hardware page |
| Liquid coolers and GPUs | **Overview ▸ Device Discovery** |
| The daemon's own health | **Overview ▸ Daemon Health** |

## Step 4 — Read your result

Find the row that matches what the two pages say. You need a driver only where a row says so: with the first result there is nothing to install.

| What you see | What it means | What to do |
|---|---|---|
| **SYSTEM READY** on System State (*No active conditions — fan control is available*) and **HARDWARE READY** on the Hardware page | Your kernel already exposes fan headers Ventulus can write, so no extra driver is needed. *PWM control not yet verified* is expected at this point: Step 6 is that check | Step 5 |
| *Motherboard Super-I/O chip detected without its driver loaded* on the Hardware page, and that chip's card under **Super-I/O Architecture** names a driver that is part of the kernel | Linux has the driver for your chip, but it is not loaded | If you have not rebooted since installing, [do that first](getting-started.md#after-installing). Otherwise the card's **How to enable** gives the command, and [Driver Setup](driver-setup.md) the detail |
| The same item, but the driver is not in the mainline kernel: the **Hardware Registry** row says **"not loaded — install …"** | Your chip needs an out-of-tree driver, built with DKMS (most 2022+ Gigabyte and MSI boards, some ASRock) | [Driver Setup](driver-setup.md). If your kernel accepts only signed modules, the item says so: see [Secure Boot](driver-setup.md#secure-boot-and-dkms-modules) |
| *Motherboard Super-I/O chip detected but its driver did not bind* | The driver is loaded but did not attach to the chip. There are several causes, and on some boards nothing can be done | The chip's card under **Super-I/O Architecture** says which applies to your board |
| Fan speeds show, but the Hardware page says *Some PWM headers are read-only*, or System State says *All PWM headers are read-only*, and none of the rows above applies | Monitoring works, control does not: the loaded driver reads the chip but cannot drive it, or the header cannot be controlled at all | ["All my hwmon headers show as read-only"](hardware-troubleshooting.md#all-my-hwmon-headers-show-as-read-only) |
| *BIOS/EC reclaiming fan control* or *Fan duty is not holding* on System State, or a fan test reports *BIOS/EC reverted pwm_enable* | Something else keeps setting the fan: the board's firmware, or another fan program. Ventulus cannot tell which | Step 5 first, then [The BIOS keeps taking fan control back](hardware-troubleshooting.md#the-bios-keeps-taking-fan-control-back) |
| *No motherboard PWM fan controls detected*, and **Super-I/O Architecture** says *No motherboard Super-I/O chip was detected* | Ventulus found no fan chip and cannot name one for your board. That alone does not mean a driver is missing: many laptops and some boards have no such chip, and the section names only a chip it can see or knows from its board table | Do not install a driver on a guess, and do not run `sensors-detect` to find out ([why](hardware-troubleshooting.md#about-sensors-detect)). Check that you have rebooted since installing, then work through [Sensors missing or fewer than expected](hardware-troubleshooting.md#sensors-missing-or-fewer-than-expected). If that finds nothing, export a support bundle from the footer to ask for help |

Some hardware has its own path, whatever the rows above say:

| You have | Meaning | Go to |
|---|---|---|
| AMD RDNA3+ dGPU (RX 7000 / 9000) and the **Safety & GPU Limits** card flags `ppfeaturemask` | GPU fan-curve writes need a one-time kernel parameter | [Driver Setup § AMD GPU prerequisite](driver-setup.md#amd-gpu-fan-control-prerequisite-rdna3) |
| OpenFAN controller | **Nothing to do**: the daemon auto-detects it on `/dev/ttyACM*` / `/dev/ttyUSB*`, and the service ships with serial access | [OpenFAN Controller](openfan-controller.md) → Step 5 |
| Intel Arc dGPU | Monitor-only **by design** (firmware-managed fan; the kernel exposes no write interface) | [Why](hardware-troubleshooting.md#intel-arc-gpus-are-monitor-only) |
| NVIDIA dGPU | Monitor-only (the NVML path is telemetry-only and off by default; `nouveau` gives no sensors on Turing and newer, and its writable `pwm1` on some older cards is excluded for safety) | [Why](hardware-troubleshooting.md#nvidia-gpus-are-monitor-only) |

### What Ventulus cannot tell you

- **Whether another fan program is running.** Ventulus sees only the effect, a fan that keeps being set to another speed, and cannot tell that apart from the BIOS. Step 5 is the check.
- **A permission problem.** The daemon runs as root and can write every fan header the kernel makes writable, so you never need to change file permissions or run Ventulus as root. A header the kernel publishes read-only is a driver limit (the read-only row above), not a permission problem. What can stop the daemon is its own sandbox: a systemd drop-in that narrows it, or an OpenFAN controller on a port other than `/dev/ttyACM*` or `/dev/ttyUSB*` (see [OpenFAN Controller](openfan-controller.md)). A write the kernel refuses is reported only in the daemon's journal: the **Journal** tab in the **Logs** page's inspector, or `journalctl -u ventulusd`.
- **Whether a writable header really drives its fan.** A board can accept a write and override it a moment later. Step 6 tests that.
- **Which fan is on which header.** The [Fan Wizard](fan-wizard.md) and [Discover Control Path](fan-tests.md#discover-control-path) find out.

## Step 5 — Stop competing fan-control software

Only one program should drive a fan header. `pwm` / `pwm_enable` are single sysfs values, so the **last writer wins**: two controllers overwrite each other and the fans oscillate. The readiness report's *BIOS interference* counter cannot tell an embedded controller apart from another program: competing software shows up as the same "reverted / reclaimed" pattern. Other projects document the same conflict: CoolerControl [warns against running LACT and CoolerControl on the same AMD GPU](https://docs.coolercontrol.org/devices/gpus#conflicts-with-lact) ("erratic fan behavior, with each application's settings being overwritten by the other"), and fan2go [logs third-party PWM changes](https://github.com/markusressel/fan2go) as another program "competing with fan2go".

Check for the usual suspects, including ones that start at boot but are not running right now, and disable each one that is enabled or running:

```bash
# Installed fan-control services, and whether each starts at boot
systemctl list-unit-files --type=service --no-pager | grep -iE 'fancontrol|coolercontrol|fan2go|thinkfan'
# Which of them is running now
systemctl list-units --type=service --no-pager | grep -iE 'fancontrol|coolercontrol|fan2go|thinkfan'
# fancontrol started by hand rather than as a service: this file exists while it runs
ls /run/fancontrol.pid

# For each hit, e.g.:
sudo systemctl disable --now fancontrol.service      # lm_sensors' fancontrol
sudo systemctl disable --now coolercontrold.service  # CoolerControl
sudo systemctl disable --now fan2go.service          # fan2go
sudo systemctl disable --now thinkfan.service        # thinkfan
```

Do this before you run your first fan test or apply your first profile. The daemon gives each header back exactly as it found it when it first took it, so a header another program still holds at that moment is later given back to that program's setting rather than to the BIOS. If you have already run a test or a profile, reboot once the other program is disabled.

Switching for good? [Migrating from Another Fan Program](migrating.md) covers the whole switch: which drivers and settings to keep, how to check that nothing still holds a header, and what you can clean up afterwards.

Also worth knowing:

- **LACT / CoreCtrl** (GPU tools): pick one owner for each GPU fan. A GPU that no Ventulus profile has driven is left alone, even when the daemon stops or restarts, so one of these tools can own it. Once a profile has driven a GPU, the daemon puts it back on its firmware curve when the profile stops naming it (deactivated, or switched to a profile without it) or when the daemon stops. **Restore GPU Fan to Automatic** hands it back at once, and the daemon then leaves it alone until a profile is next activated or the daemon restarts.
- **`pwmconfig`** (lm_sensors' interactive setup for `fancontrol`) is not needed with Ventulus: [Discover Control Path](fan-tests.md#discover-control-path) finds which fan each header drives without stopping any, and **Test Control** checks that the header responds. [`pwmconfig`](https://github.com/lm-sensors/lm-sensors/blob/master/prog/pwm/pwmconfig) stops each fan in turn for about 5 seconds, refuses to start while `fancontrol` is running, writes a `fancontrol` configuration (`/etc/fancontrol` unless you choose another path), and leaves every header it tested at full speed. If you run it anyway, stop `ventulusd` first, and reboot before you start it again so that the BIOS has the headers back: otherwise the daemon finds them at full speed and gives them back that way.

## Step 6 — Verify control end-to-end

1. On the **Hardware** page, under **Cooling Hardware**, press **Test Control** on a **non-critical chassis fan** header (not CPU or pump). *"PWM control is working correctly"* is the finish line; every other verdict comes with a tailored next step (see [the result table](fan-tests.md#test-pwm-control)). To test several headers in one run, use **PWM Test Report…** under **Hardware Diagnostics** on the same page.
2. If you have an AMD GPU with a write path, run **Test GPU Fan Control** from **Advanced actions** on the **System State** page (see [its result table](fan-tests.md#test-gpu-fan-control)).

When a header passes:

- The result reads *PWM control is working correctly*, and its **Test:** line shows the RPM changing with the duty and the fan mode staying *Manual*.
- The fan goes back to the speed it had before the test.
- On the Hardware page, *PWM control not yet verified* counts one header fewer, and it goes away once every writable header has passed.
- No *BIOS/EC reclaiming fan control* card appears on System State. If one does, the firmware is taking the header back: see [The BIOS keeps taking fan control back](hardware-troubleshooting.md#the-bios-keeps-taking-fan-control-back).

## Step 7 — Create your first profile

1. Run the [Fan Wizard](fan-wizard.md) to identify and label each fan. It changes one fan at a time so you can match headers to physical fans. Ordinary fans are stopped briefly; a pump has its speed shifted instead, never stopped.
2. On [Controls](controls.md), create fan roles and assign curves. Concepts: [Profiles and Curves](profiles-and-curves.md).
3. Click **Save** on the Controls page. Nothing you edit reaches the daemon until you do.
4. Pick the profile in the selector (page header or sidebar) and click **Apply**. The daemon then runs it, and keeps running it after you close the GUI and after a reboot, until you apply another or press **Stop** in the sidebar ([why](profiles-and-curves.md#the-daemon-drives-the-fans)). Until you apply a profile, no curve controls any fan.
5. Check that it took: the status banner names the profile, and on **Overview ▸ Fan Status** the **PWM (%)** of each fan in it changes as temperatures change, with the RPM following.

## When to redo what

After any change (a driver loaded or updated, a BIOS setting, a kernel parameter), check the result rather than trusting it: a package that installed cleanly does not prove that fan control works. After loading or updating a fan driver, restart the daemon (`sudo systemctl restart ventulusd`), because new fan headers appear only then. Then go through Steps 3, 4 and 6 again.

| After this event | What can break | What to redo |
|---|---|---|
| **Kernel update** | The DKMS module silently fails to rebuild when the installed headers don't match the new kernel, so motherboard fans/sensors vanish | [Driver Setup § Step 2](driver-setup.md#step-2--prerequisites-dkms--kernel-headers) and [Staying current](driver-setup.md#staying-current) |
| **BIOS update or settings reset** | Firmware usually restores its fan-curve defaults. Check the BIOS curve has no 0% point, and re-run Test PWM Control in case the firmware now takes headers back | [Driver Setup § Step 5 (BIOS)](driver-setup.md#step-5--bios-settings-the-half-people-skip), then re-run the readiness check |
| **Fan regression with a driver installed months ago** | An out-of-tree driver picks up upstream fixes only when you rebuild it | [Staying current](driver-setup.md#staying-current) |
| **Bootloader change / kernel command-line edit** | `amdgpu.ppfeaturemask` falls off the command line, so GPU fan writes stop working | [AMD GPU prerequisite](driver-setup.md#amd-gpu-fan-control-prerequisite-rdna3); check with `cat /proc/cmdline` |

## Where to go next

- Something failed along the way → [Hardware Troubleshooting](hardware-troubleshooting.md)
- Driver depth (DKMS, module parameters, Secure Boot, rollback) → [Driver Setup](driver-setup.md)
- How profiles, fan roles, and curves fit together → [Profiles and Curves](profiles-and-curves.md)

---

Previous: [Getting Started](getting-started.md) | Next: [Dashboard](dashboard.md) | Back to [Table of Contents](README.md)
