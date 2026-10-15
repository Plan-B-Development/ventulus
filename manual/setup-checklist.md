# Setup Checklist — Sensors & Fan Control

This page is the **ordered path** from a fresh install to verified, working fan control: install → sensors → readiness → drivers/BIOS → verify → first profile. Do the steps in order. Each one links to a deeper page for the detail. Commands target **Arch Linux and CachyOS** (the platforms Ventulus is packaged for); the concepts carry to other distributions but the commands will differ.

New to how Linux fan control works? [Understanding Motherboard Fan Control](understanding-fan-control.md) is a short, plain-English primer on the concepts this checklist puts into practice (hwmon, Super I/O chips, drivers, and BIOS settings). It is optional background: you can follow the steps below without it.

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

Add the signed `[ventulus]` pacman repository, install `ventulus` (it pulls in
`ventulusd`), and enable the daemon. [Getting Started](getting-started.md#installation)
has the commands, a signed script that does it all in one step, and the other ways
to install. From then on both packages upgrade with your normal `sudo pacman -Syu`.

## Step 2 — Verify sensors first

Fan control depends on temperatures: the readiness checks, fan curves, and the daemon's thermal safety all need a working CPU sensor before any fan work matters. (Sensors-before-fans is the same order the [Arch Wiki fan-speed-control flow](https://wiki.archlinux.org/title/Fan_speed_control) uses.)

Launch the GUI and check:

- **Temperatures visible** on the Dashboard and on the **Overview** page? Continue to Step 3.
- **Missing or fewer than expected** (no CPU temperature, no motherboard temperatures, no drive temperatures)? → [Sensors missing or fewer than expected](hardware-troubleshooting.md#sensors-missing-or-fewer-than-expected), then come back here.

## Step 3 — Read the health report

Open the **System State** page (the daemon's hardware snapshot is fetched in the background at startup; **Rescan Hardware**, in the global footer, re-runs it) and read the **System Health Overview**: how many PWM headers were found and how many are writable, and a card for each issue. [What each section of the page means](diagnostics.md#system-state-page). The **Hardware** page's **Hardware Readiness Checklist** gives the daemon's own go/no-go answer beside it.

## Step 4 — Branch: what your hardware needs

| The health report says / you have | Meaning | Go to |
|---|---|---|
| Writable headers > 0, no issues | The mainline driver already works | Step 5 |
| A **Hardware Registry** row says **"not loaded — install …"** | Your board needs an out-of-tree DKMS driver (most 2022+ Gigabyte / MSI, some ASRock) | [Driver Setup](driver-setup.md) |
| **BIOS interference**, or Test PWM Control says control was reverted | Firmware Smart Fan keeps reclaiming the headers | [Driver Setup § Step 5 (BIOS)](driver-setup.md#step-5--bios-settings-the-half-people-skip); vendor depth: [AMD boards](../docs/21_AMD_Motherboard_Fan_Control_Guide.md) / [Intel boards](../docs/23_Intel_Motherboard_Fan_Control_Guide.md) |
| AMD RDNA3+ dGPU (RX 7000 / 9000) and the **Safety & GPU Limits** card flags `ppfeaturemask` | GPU fan-curve writes need a one-time kernel parameter | [Driver Setup § AMD GPU prerequisite](driver-setup.md#amd-gpu-fan-control-prerequisite-rdna3) |
| OpenFAN controller | **Nothing to do**: the daemon auto-detects it on `/dev/ttyACM*` / `/dev/ttyUSB*`, and the service ships with serial access | [OpenFAN Controller](openfan-controller.md) → Step 5 |
| Intel Arc dGPU | Monitor-only **by design** (firmware-managed fan; the kernel exposes no write interface) | [Why](hardware-troubleshooting.md#intel-arc-gpus-are-monitor-only) |
| NVIDIA dGPU | Monitor-only (the NVML path is telemetry-only and off by default; `nouveau` gives no sensors on Turing and newer, and its writable `pwm1` on some older cards is excluded for safety) | [Why](hardware-troubleshooting.md#nvidia-gpus-are-monitor-only) |

## Step 5 — Stop competing fan-control software

Only one program should drive a fan header. `pwm` / `pwm_enable` are single sysfs values, so the **last writer wins**: two controllers overwrite each other and the fans oscillate. The readiness report's *BIOS interference* counter cannot tell an embedded controller apart from another program: competing software shows up as the same "reverted / reclaimed" pattern. Other projects document the same conflict: CoolerControl [warns against running LACT and CoolerControl on the same AMD GPU](https://docs.coolercontrol.org/hardware-support.html) ("erratic fan behavior, with each application's settings being overwritten by the other"), and fan2go [logs third-party PWM changes](https://github.com/markusressel/fan2go) as another program "competing with fan2go".

Check for the usual suspects and disable any that are active:

```bash
systemctl list-units --type=service | grep -iE 'fancontrol|coolercontrol|fan2go'

# For each hit, e.g.:
sudo systemctl disable --now fancontrol.service      # lm_sensors' fancontrol
sudo systemctl disable --now coolercontrold.service  # CoolerControl
sudo systemctl disable --now fan2go.service          # fan2go
```

Also worth knowing:

- **LACT / CoreCtrl** (GPU tools): pick one owner for each GPU fan. A GPU that no Ventulus profile has driven is left alone, even when the daemon stops or restarts, so one of these tools can own it. Once a profile has driven a GPU, the daemon puts it back on its firmware curve when the profile stops naming it (deactivated, or switched to a profile without it) or when the daemon stops. **Restore GPU Fan to Automatic** hands it back at once, and the daemon then leaves it alone until a profile is next activated or the daemon restarts.
- **`pwmconfig`** (lm_sensors' interactive prober) stops fans while it tests. Fine as a one-off diagnostic, but only run it while `ventulusd` is stopped.

## Step 6 — Verify control end-to-end

1. On the **Hardware** page, under **Cooling Hardware**, press **Test Control** on a **non-critical chassis fan** header (not CPU or pump). *"PWM control is working correctly"* is the finish line; every other verdict comes with a tailored next step (see [the result table](fan-tests.md#test-pwm-control)). To test several headers in one run, use **PWM Test Report…** under **Hardware Diagnostics** on the same page.
2. If you have an AMD GPU with a write path, run **Test GPU Fan Control** from **Advanced actions** on the **System State** page (see [its result table](fan-tests.md#test-gpu-fan-control)).

## Step 7 — Create your first profile

1. Run the [Fan Wizard](fan-wizard.md) to identify and label each fan. It changes one fan at a time so you can match headers to physical fans. Ordinary fans are stopped briefly; a pump has its speed shifted instead, never stopped.
2. On [Controls](controls.md), create fan roles and assign curves. Concepts: [Profiles and Curves](profiles-and-curves.md).
3. Click **Save** on the Controls page. Nothing you edit reaches the daemon until you do.
4. Pick the profile in the selector (page header or sidebar) and click **Apply**. The daemon then runs it, and keeps running it after you close the GUI and after a reboot, until you apply another or press **Stop** in the sidebar ([why](profiles-and-curves.md#the-daemon-drives-the-fans)). Until you apply a profile, no curve controls any fan.

## When to redo what

| After this event | What can break | What to redo |
|---|---|---|
| **Kernel update** | The DKMS module silently fails to rebuild when the installed headers don't match the new kernel, so motherboard fans/sensors vanish | [Driver Setup § Step 2](driver-setup.md#step-2--prerequisites-dkms--kernel-headers) and [Staying current](driver-setup.md#staying-current) |
| **BIOS update or settings reset** | Firmware usually restores its fan-curve defaults. Check the BIOS curve has no 0% point, and re-run Test PWM Control in case the firmware now takes headers back | [Driver Setup § Step 5 (BIOS)](driver-setup.md#step-5--bios-settings-the-half-people-skip), then re-run the readiness check |
| **Fan regression with a driver installed months ago** | `-git` AUR drivers only pick up upstream fixes when reinstalled | [Staying current](driver-setup.md#staying-current) |
| **Bootloader change / kernel command-line edit** | `amdgpu.ppfeaturemask` falls off the command line, so GPU fan writes stop working | [AMD GPU prerequisite](driver-setup.md#amd-gpu-fan-control-prerequisite-rdna3); check with `cat /proc/cmdline` |

## Where to go next

- Something failed along the way → [Hardware Troubleshooting](hardware-troubleshooting.md)
- Driver depth (DKMS, module parameters, Secure Boot, rollback) → [Driver Setup](driver-setup.md)
- How profiles, fan roles, and curves fit together → [Profiles and Curves](profiles-and-curves.md)

---

Previous: [Getting Started](getting-started.md) | Next: [Dashboard](dashboard.md) | Back to [Table of Contents](README.md)
