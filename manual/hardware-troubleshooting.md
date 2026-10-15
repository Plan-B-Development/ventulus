# Hardware Troubleshooting

This page starts from what you see: missing sensors, missing or read-only fan
headers, fans at full speed, a GPU fan that will not respond. Each section says how
to tell what is going on and what to do.

Two pages in the app do most of the diagnosis. **System State** is the health
report: your board, its fan chips and their drivers, BIOS interference, and the
thermal and GPU state. The **Hardware** page holds the daemon's readiness checklist
and the fan tests. [System Health](diagnostics.md) describes both pages section by
section, and [Fan Tests and Reports](fan-tests.md) explains every test and its
results. After you change anything, click **Rescan Hardware** in the footer.

If a driver is missing, [Driver Setup](driver-setup.md) has the install steps. New
to terms like hwmon, Super I/O or `pwm_enable`?
[Understanding Motherboard Fan Control](understanding-fan-control.md) explains them.

## Sensors missing or fewer than expected

Fan control depends on sensors: curves need temperatures, and the daemon's thermal
safety needs a CPU sensor. If the Dashboard or the **Overview** page shows nothing,
or less than you expect, work down this list:

- **No CPU temperature.** The CPU drivers (`k10temp` for AMD, `coretemp` for Intel)
  are in the mainline kernel and load by themselves on nearly every distribution. If
  the **CPU Thermal State** row on **System State** reads *No_sensor_fallback*, load
  the module by hand (`sudo modprobe k10temp` or `sudo modprobe coretemp`) and check
  `sudo dmesg` for errors. Then click **Rescan Hardware**: the daemon picks up the
  sensor within a couple of seconds, with no restart.
- **No motherboard temperatures or fan RPMs.** Super-I/O chips sit on old ISA ports
  with nothing to announce them, so their drivers cannot load by themselves. The
  daemon package ships `/etc/modules-load.d/ventulus.conf`, which loads `nct6775`,
  `it87`, `w83627ehf` and `drivetemp` at boot. On a Gigabyte board, `nct6775` and
  `w83627ehf` can hide a second fan chip until the machine is powered down at the
  wall (see
  ["Some of my fan headers are missing"](#some-of-my-fan-headers-are-missing--only-5-of-8-show-up)),
  so the package also installs a guard, `/usr/lib/modprobe.d/ventulus-superio.conf`,
  that stops those two loading on every Gigabyte board and leaves them alone
  everywhere else. Gigabyte boards use ITE chips, which those drivers cannot drive.
  Each module it declines is logged: `sudo journalctl -b -t ventulus-superio-guard`.
  If you have a Gigabyte board that really carries a Nuvoton chip, turn the guard off
  by creating an **empty** file of the **same name**,
  `/etc/modprobe.d/ventulus-superio.conf`, and rebooting. A same-named file in `/etc`
  masks the package's copy; a file of another name does not reliably win. If your chip
  needs an out-of-tree driver instead, the **Hardware Registry** on System State says
  so; see [Driver Setup](driver-setup.md).
- **No memory (DIMM) temperatures.** These are optional: many machines have none, and
  nothing about fan control depends on them. Check, in order:
  - **DDR5** needs kernel 6.11 or later. The kernel registers modules from the
    firmware's memory table: if the table lists a mix of memory types it registers
    none, and on a bus with more than 8 slots it tries only the first 8 addresses.
    Current kernels also skip DDR5 modules on Intel boards whose firmware locks SPD
    writes ("SPD Write Disable"). `ls /sys/bus/i2c/drivers/spd5118/` lists the modules
    it found; `sudo dmesg | grep -i spd` shows what it did.
  - **DDR4** needs a module with a thermal sensor, and most consumer DDR4 has none.
    Where one exists it appears as a `jc42` sensor. Some DDR5 modules have no working
    sensor either.
  - **RGB tools.** OpenRGB and similar tools use the same SMBus addresses and can
    conflict with the memory driver while they run.
  - **A module listed under unavailable sensors as "disabled"** has its sensor switched
    off as the driver sees it (`temp1_enable` is 0, as the firmware left it or as
    something wrote it). The driver would keep returning the last value, so the daemon
    does not use it. It recovers by itself once the sensor is switched back on through
    `temp1_enable`; the daemon never writes to the module. A change made over raw
    SMBus, bypassing the driver, is not seen until the driver reloads.
  - **After suspend** some boards fail to talk to the modules again, and the sensors
    show as unavailable until the next boot. If resume itself misbehaves,
    `blacklist spd5118` in a file under `/etc/modprobe.d/` turns the driver off (you
    lose the reading).
  - Each module is named by its bus address (**DIMM 0x51**, **DIMM 0x53**…), because
    the kernel does not report which slot an address belongs to. Two modules at the
    same address on different SMBus segments get the segment added, as in
    **DIMM 0x51 (p2)**; hover for the full id. A module keeps its id when the kernel
    renumbers its i2c bus (after a GPU change, say), so curves and chart settings stay
    attached. If two modules could match one saved setting, nothing is moved: pick the
    sensor again.
- **No drive temperatures.** NVMe drives report through the kernel's `nvme` driver
  automatically; SATA and SAS drives need `drivetemp`, which the modules-load file
  above already loads.
- **`lm_sensors` is optional.** The daemon reads `/sys/class/hwmon` directly. The
  `sensors` command from `lm_sensors` is handy for cross-checking what the kernel
  exposes.

### About `sensors-detect`

Use the **Hardware** page first: its readiness checklist and Super-I/O section
identify your board's chips **without probing the hardware**. Treat
`sudo sensors-detect` as a **last resort**, at your own risk: its probing "can access
chips in a way these chips do not like, causing problems ranging from SMBus lockup to
permanent hardware damage (a rare case, thankfully)"
([sensors-detect(8)](https://man.archlinux.org/man/extra/lm_sensors/sensors-detect.8.en)).
If you do run it, accept its conservative defaults rather than answering yes to every
probe, and **never run it after boot on a Gigabyte board**. It can wedge the Super-I/O
bridge so that a second chip vanishes, the package's guard cannot stop it (it probes
the ports itself rather than loading a module), and **a reboot may not bring the chip
back: power down at the wall**, because the bridge keeps standby power (see
["Some of my fan headers are missing"](#some-of-my-fan-headers-are-missing--only-5-of-8-show-up)).

## "All my hwmon headers show as read-only"

Open the **System State** page:

- If the **Hardware Registry** lists the expected chip but its **Driver Status** is
  *not loaded*, the kernel module is missing. The row names the module to install
  (for example `it87-dkms-git` from the AUR for Gigabyte AM5 boards).
- If the driver is loaded but the summary line says **0 writable**, the bound driver
  publishes the pwm files read-only. On MSI and ASRock Nuvoton boards that usually
  means the in-kernel `nct6683` is bound; it never makes PWM writable outside Mitac
  OEM systems, so you need the out-of-tree driver the registry names. See
  [Driver Setup](driver-setup.md).
- If the headers are writable but a fan test reports *BIOS/EC reverted pwm_enable*,
  the firmware is taking control back: see
  [The BIOS keeps taking fan control back](#the-bios-keeps-taking-fan-control-back).
- If an ACPI resource conflict blocks the driver, an *ACPI I/O port conflict* card
  says so. For `it87`, prefer `options it87 ignore_resource_conflict=1`;
  `acpi_enforce_resources=lax` is the system-wide fallback, and the only option for
  `nct6775`.

## "Some of my fan headers are missing — only 5 of 8 show up"

Open the **System State** page. If a *Super-I/O chip not enumerated* card (the
dual-chip warning) sits under the **System Health Overview**, your motherboard is one
of the Gigabyte boards with two ITE chips (X870E AORUS MASTER, X670E AORUS MASTER,
Z790 AORUS MASTER and others), and one of them did not appear.

**Case A: the driver is not loaded.** Run `sudo dmesg | grep -i it87` (or
`journalctl -k -b | grep -i it87`). Each chip the driver found prints a line such as
`Found IT8696E chip at 0xa40 … revision 0`. If there are no `it87` lines at all, or
`modprobe` says "module not found":

1. Install `it87-dkms-git` (see [Driver Setup](driver-setup.md)). Current builds reach
   the secondary chip's extra headers through MMIO, which is on by default.
2. Reboot, then click **Rescan Hardware**.

**Case A2: an Intel Z890 / B860 board on a 2026-09 driver build.** If `modprobe it87`
fails with *Invalid argument* after a line like `H2RAM set_slot(1,…) failed: -22`, or
the log shows *Found IT8696E chip* but no chip appears, the driver build is at fault,
not your board: builds from 2026-09-09 to 2026-10-01 fail this way on Gigabyte Z890 /
B860 boards ([it87 #139](https://github.com/frankcrawford/it87/issues/139),
[#138](https://github.com/frankcrawford/it87/issues/138)). It was fixed on
2026-10-02 ([PR #140](https://github.com/frankcrawford/it87/pull/140)):

1. Rebuild the driver: `yay -S it87-dkms-git`.
2. Reboot, then click **Rescan Hardware**.

Do not go on to Case B for this. `options it87 mmio=off` also gets such a build to
load, but the second chip then loses its extra headers (SYS_FAN7/8_PUMP on the Z890
AORUS MASTER), so use it only until you can rebuild, then remove it.

**Case B: the driver is loaded, but a chip is missing.** The secondary chip is
blocked. Work down the recovery ladder below. It is the one upstream gives, and it
clears the block whichever ID the blocked chip reports.

**What is happening.** Your board's secondary Super-I/O sits behind an ITE
eSPI-to-LPC bridge. Something wrote a Super-I/O *config-mode unlock* to port
0x2E/0x4E, which put the **bridge** into configuration mode, and while it is there the
bridge answers in place of the IT87952E behind it. `it87` looks for a chip, finds the
bridge, and gives up. You lose every header on the secondary chip: on an X870E AORUS
MASTER that is 3 of 8 fan headers and 3 of 9 temperatures.

**What writes that unlock.** Almost always the `nct6775` or `w83627ehf` kernel modules.
Both write the unlock *before* reading the device ID, so they do the damage even
though they then fail to load with "No such device": they are Nuvoton and Winbond
drivers, and your board is ITE. Running `sensors-detect` does the same.

> **Measured, not theorised.** On 2026-09-05, on an X870E AORUS MASTER: loading
> `nct6775` made the working `it87952-isa-0a60` chip disappear within a single boot,
> while reloading `it87` by itself changed nothing. Suppressing both modules and
> cutting power restored 3 fans, 3 PWMs and 3 thermistor temperatures.

**The block can survive a reboot**, and a normal shut-down, because the bridge keeps
its standby power. On that X870E AORUS MASTER only removing mains power cleared it.
This is the most important thing on this page: *if you reboot, test, and see no
change, the fix has not failed. Go on to the power cut.*

### Recovery, step by step

1. **Check whether the package's guard covers your board.** The `ventulusd` package
   installs a guard that stops the two modules loading on every Gigabyte board, and
   logs each time it does:

   ```
   sudo journalctl -b -t ventulus-superio-guard
   ```

   A line such as *not loading nct6775: X870E AORUS MASTER is a Gigabyte board, and
   Gigabyte boards use ITE Super-I/O chips* means your board is covered: skip to
   step 3. No line means the guard did not act: the board's vendor is not Gigabyte
   (or the firmware reports no vendor and the board is not one the guard lists), an
   older package is installed, or nothing asked for the modules this boot. Do not use
   `lsmod` for this: the modules fail to load on these boards even when their probe
   has already done the damage, so an empty `lsmod` proves nothing.

2. **Otherwise, suppress the two modules yourself.** Create
   `/etc/modprobe.d/ventulus-superio-local.conf`:

   ```
   install nct6775 /bin/true
   install w83627ehf /bin/true
   ```

   Use `install`, **not** `blacklist`: `blacklist` is ignored by the explicit
   `modprobe` that systemd issues at boot, so it would silently do nothing here.

3. **Confirm nothing else loads them, and stop running `sensors-detect`.** Look for
   other files naming `nct6775` or `w83627ehf`. `lm_sensors.service` loads whatever
   `sensors-detect` once wrote to `/etc/conf.d/lm_sensors`, so check that file too:

   ```
   grep -rn 'nct6775\|w83627ehf' /etc/modules-load.d/ /etc/conf.d/lm_sensors
   ```

   A module named there still goes through the guard (or your file from step 2), so
   it is only a trigger where neither is in place, but removing it costs nothing on a
   Gigabyte board. `sensors-detect` is different: it probes the ports directly, so no
   guard can stop it. Do not run it on this board.

4. **Reboot, then click Rescan Hardware.** If the missing chip is back, you are done.

5. **Still missing: power down fully.** Shut the machine down, then **either** switch
   the PSU off at the back (the `0`/`O` side of the rocker) **or** unplug it at the
   wall. Wait about 10 seconds. A normal shut-down that leaves the PSU switched on is
   not enough.

6. **Power back on and verify:**

   ```
   sudo dmesg | grep -i it87
   sensors | grep -c '^it8'
   ```

   You want a second `Found IT...E chip` line, and two `it8*` chips rather than one.

7. **Click Rescan Hardware** in the app. The dual-chip warning on **System State**
   disappears once every expected chip is present. New fan headers need a daemon
   restart (`sudo systemctl restart ventulusd`) before they appear on the
   **Controls** page.

**Optional: the ID the driver read, for a bug report.** On kernels built with dynamic
debug (Arch's and CachyOS's are), you can make the driver print it:

```
echo 'options it87 dyndbg=+p' | sudo tee /etc/modprobe.d/it87-debug.conf
# reboot, then:
sudo dmesg | grep -i 'unsupported chip'
sudo rm /etc/modprobe.d/it87-debug.conf
```

A blocked chip reads `0xFFFF` without the unlock key and `0x8883` with it, and the
ladder above clears both
([issue #70](https://github.com/frankcrawford/it87/issues/70)).

### If it still fails after a genuine power cut

Something else is still writing the unlock before `it87` reads. Check, in this order:

- another `modules-load.d` file, `/etc/conf.d/lm_sensors`, or a distribution default,
  loading `nct6775` where the guard has not acted;
- `sensors-detect`, run by hand or by a script;
- a Super-I/O module baked into your initramfs
  (`for i in /boot/initramfs-*.img; do echo "$i"; lsinitcpio "$i" | grep -E 'nct6775|w83627|it87'; done`;
  CachyOS names its images `initramfs-linux-cachyos*.img`);
- any other tool that probes Super-I/O ports.

**Do not** reach for these. They are known not to help, and one makes things worse:

- **`mmio=on`**: already the driver default; setting it changes nothing.
- **Reinstalling `it87-dkms-git`**: the block is not a driver bug, and it reproduces
  on the current upstream code.
- **`force_id`**: the reporter on
  [issue #81](https://github.com/frankcrawford/it87/issues/81) forced the ID and still
  lost three fans and a water pump. Upstream tells people not to use it.
- **`sensors-detect`**: it is one of the things that *cause* the block.

**This is per board, not per family.** Other boards with the same IT8696E + IT87952E
pairing work out of the box: the X870E AORUS ELITE X3D is owner-confirmed with both
chips controllable ([issue #89](https://github.com/frankcrawford/it87/issues/89)).
Background on the bridge is in
[issue #64](https://github.com/frankcrawford/it87/issues/64).

On **IT8665E** boards (the X399-era ASUS ROG Zenith Extreme, and ASUS AM4
300/400-series boards such as the PRIME X470-PRO), an `it87` build from before
2026-07-22 garbled PWM writes with MMIO on. Upstream removed MMIO for that chip
([PR #120](https://github.com/frankcrawford/it87/pull/120)); update the driver rather
than setting `options it87 mmio=off`.

## The BIOS keeps taking fan control back

Some boards, most often Gigabyte AM5 with Smart Fan 6, repeatedly switch a header
from manual back to automatic. Each switch is a *reclaim*: the daemon sets the header
back to manual, and the firmware takes it again. A fan test that reports *BIOS/EC
reverted pwm_enable* has caught one in the act.

The **Interference Monitor** on **System State** counts reclaims per header:

| Reclaim count | Colour | Meaning |
|---------------|--------|---------|
| **0** | Green (OK) | The header is controlled cleanly |
| **1–9** | Amber (WARN) | Occasional reclaims; control still works, but the firmware is fighting back |
| **10 or more** | Red (HIGH) | Persistent contention; expect the fan speed to drift even though the daemon keeps writing |

The count never resets while the daemon runs, so it is dated: once every affected
header has been quiet for an hour, the warning stands down and the monitor relabels
the count **Past Interference**, with how long ago it was. That separates a BIOS
fighting you *now* from one that lost the argument hours ago. Each header's card on
the **Hardware** page shows the count too, under **Details ▸ Capabilities**, and a
header currently under firmware control with reclaims on record shows **Control
reclaimed**.

Because the daemon takes the header back each time, control still works in the WARN
and HIGH bands, but the fix is per vendor, and the board notes on System State carry
it for your chip:

- **Gigabyte:** an `it87-dkms-git` build from 2026-08-24 or later carries the fixes
  for the firmware logic that retakes headers
  ([PR #128](https://github.com/frankcrawford/it87/pull/128)). If yours is older,
  rebuild it.
- **Other vendors:** see [Driver Setup § BIOS settings](driver-setup.md#step-5--bios-settings-the-half-people-skip)
  and the vendor guides.

Setting a header to *Full Speed* in the BIOS is a fail-safe, not a fix: on some boards
it locks Linux out of that header.

If a header is flagged **Fan duty is not holding** instead, the daemon has stopped
correcting it because something keeps changing the duty itself: usually another
fan-control program, or the board's own fan control. Stop the other program (see
[Setup Checklist § Step 5](setup-checklist.md#step-5--stop-competing-fan-control-software)).

## "No fan detected" on a header

Modern boards have more fan headers than most builds use: the X870E AORUS MASTER has
8 (5 on the IT8696E and 3 on the IT87952E), and a typical build fills 3 or 4. So that
you do not assign a curve to an empty header, Ventulus marks any **writable** header
reading 0 RPM *(no fan detected)*, on the Overview page, in the Controls member picker
and in the Fan Wizard. If a fan is plugged in and you still see it, the usual causes
are:

- the fan has no tachometer (a 3-pin fan without RPM sense, or a pump on a PWM-only
  header);
- the fan is stopped because the header is being driven at 0 % (zero-RPM mode);
- the fan has stalled.

Run **Test Control** on the header. If the write takes effect but the RPM does not
change, the header is controllable but cannot confirm a fan; if the write is
reverted, the BIOS is overriding control. To tell Ventulus that nothing is plugged
in, set the header's role to **No fan** on the **Hardware** page.

## "Fans run at full speed regardless of profile"

The daemon's thermal safety has forced them. It has three ways of doing so, and the
speed tells you which:

- **100 % on every fan, CPU hot or a CPU sensor reading high:** the **CPU
  emergency**. A CPU sensor reached this machine's emergency limit (at least 105 °C,
  shown on the **CPU Thermal State** row on **System State**). It holds until a
  *current* CPU reading is 80 °C or below.
- **100 % on every fan, with a coolant sensor:** the **coolant emergency**. A coolant
  sensor the daemon recognises reached the coolant limit (60 °C unless you changed it
  in **Settings**). It holds until a current coolant reading is 5 °C below the limit.
- **About 40 % on your profile's fans:** the **no-sensor fallback**. The daemon has had
  no current CPU reading for 5 seconds, because the sensor is missing or has stopped
  updating. See [Sensors missing or fewer than expected](#sensors-missing-or-fewer-than-expected).

Each is shown on the footer's thermal chip (click it for the detail), as a banner on
the Dashboard, and as an alert naming its cause. Normal control resumes by itself when
the daemon reports a normal state again. Fans pinned during one of these are the
daemon protecting the machine, not a stuck profile. The rules in full are in
[Understanding Motherboard Fan Control § What keeps your machine safe](understanding-fan-control.md#what-keeps-your-machine-safe).

**A faulty CPU sensor stuck at or above the limit keeps the emergency on.** One
reading at the limit is enough to start it, and the daemon never decides on its own
that the reading was wrong; it waits for that sensor to read 80 °C or below. So if the
fans stay at 100 % while the machine is cool, look on the **Overview** page for a CPU
sensor reporting an impossible temperature, then fix or unload the driver that reports
it, or report it so that the sensor can be set aside. **If that was your only CPU
sensor, unloading its driver does not end the emergency**, because a sensor that
disappears keeps it on: restart the daemon afterwards
(`sudo systemctl restart ventulusd`), which then applies the 40 % fallback.

**A CPU pinned at its ceiling is a different warning.** A modern CPU slows itself down
at its own temperature ceiling, below the emergency limit, so a stopped pump or
stalled fans usually show up as a hot, slow CPU rather than as an emergency. The
daemon warns about that (*CPU at its limit with low cooling*) and about a pump that
stops turning. If the CPU sits at its ceiling under a load it used to handle, check
the pump and the fan speeds.

## Per-board hwmon header label resolver

On many boards the chip publishes no fan-header names at all: the silkscreen labels
(`CPU_FAN`, `SYS_FAN1`…) are printed on the board, not stored in the chip. Every
Gigabyte board using the `it87` driver is like this, and the daemon reports such a
header by its node id (`pwm1`, `pwm2`…).

Ventulus fills the gap by choosing each header's name in this order:

1. **Your name for it**, set in the [Fan Wizard](fan-wizard.md) or by renaming the fan
   wherever it appears.
2. **The label the chip published**, when it really published one. A label that only
   repeats the header's node id (`pwm1` on header 1) is skipped.
3. **`/etc/sensors.d` and `/usr/share/sensors/*`** chip blocks (libsensors
   configuration: `chip`, `label` and `ignore` lines).
4. **Ventulus's own per-board table**, matched on your board's vendor and model.
5. **The node id** (`pwm1`), when nothing above knows the board.

The name is not only cosmetic: a header whose name says CPU or pump gets the 30 %
minimum when it joins a fan role. The per-board table currently covers the
**Gigabyte X870E AORUS MASTER**:

- IT8696E primary chip: 5 verified silkscreen labels, `CPU_FAN`, `SYS_FAN1`,
  `SYS_FAN2`, `SYS_FAN3` and `CPU_OPT`.
- IT87952E secondary chip: 3 labels (`SYS_FAN5_PUMP`, `SYS_FAN6_PUMP`, `SYS_FAN4`) from
  two owners' configurations in
  [frankcrawford/it87 issue #103](https://github.com/frankcrawford/it87/issues/103)
  and the it87 project's Gigabyte sensor catalogue, confirmed on a physical board: a
  fan plugged into SYS_FAN4 reads on the third channel, which rules out the one source
  that ordered them differently.

A label with an `(unverified)` suffix is a hint, not a fact (no table entry carries
one today). The Fan Wizard is the safe way to confirm which physical fan is on which
header.

## Intel Arc GPUs are monitor-only

Ventulus **monitors** an Intel Arc discrete GPU (Battlemage / B-series on the `xe`
driver, Alchemist / A-series on `i915`) but cannot control its fan:

- Its package, VRAM, memory-controller and PCIe temperatures appear on the Dashboard
  and the **Overview** page, and any of them can drive a curve for *other* fans.
- Its fan appears in the fan tables with the control method **read-only
  (firmware-managed)**, is never offered as a curve member, and is never written to.

This is by design, not a missing driver. In a mainline kernel the `xe` and `i915`
drivers expose the fan's RPM read-only and no write control at all: firmware on the
card runs the fan by itself, and on a stock kernel no Linux tool can set its speed. So
`ppfeaturemask`, overdrive and the GPU fan test do not apply.

Intel has posted kernel patches that add fan control to `xe`; they were still under
review in October 2026. If you run a kernel patched with them, Ventulus lists the Arc
fan as a motherboard header on chip `xe`: do not add that header to a profile, because
Ventulus would then drive a GPU fan with motherboard-fan rules.

An Arc fan can read 0 RPM while it spins: one B580 owner sees this with PCIe power
saving (ASPM) on ([drm/xe #9328](https://gitlab.freedesktop.org/drm/xe/kernel/-/issues/9328),
open). So 0 RPM on an Arc card is not proof of a stopped fan.

Cards the PCI ID database names (the B580, B570, Pro B50/B60/B65/B70 and the A-series
cards) show their model name; other Intel discrete GPUs show as "Intel D-GPU".

## NVIDIA GPUs are monitor-only

Ventulus **monitors** an NVIDIA discrete GPU but does not drive its fan:

- Its temperature appears on the Dashboard and the **Overview** page, and can drive a
  curve for *other* fans.
- Its fan appears in the fan tables as **read-only**, is never offered as a curve
  member, and is never written to. Through NVML it also shows the duty the driver
  reports ("N% duty"), which is not a commanded value and can exceed 100 %. NVIDIA
  documents that duty, and the RPM NVML gives, as the fan's *intended* speed: a fan
  that is blocked or failed still shows it.

NVIDIA has two driver worlds, and Ventulus treats both as read-only:

- **`nouveau`**, the open driver, publishes a temperature (and on some cards fan RPM
  and a writable `pwm1`, which Ventulus excludes from control: GPU fans belong to the
  GPU, the same rule as for AMD) **only on cards older than Turing**. On Turing (RTX 20)
  and newer it runs NVIDIA's GSP firmware and publishes no sensors at all, so Ventulus
  cannot see such a card through `nouveau`.
- **The proprietary driver** exposes no hwmon fan at all. Ventulus can read its
  temperature and fan telemetry through the **NVML** library. That path is **off by
  default** (`[detection] enable_nvidia_telemetry` in the daemon's configuration, plus
  a `/dev/nvidia*` systemd drop-in) and **experimental**: built and tested, but not yet
  verified on NVIDIA hardware. It never writes to the GPU.

## "GPU fan control says feature_unavailable"

Open **System State** and look at the GPU rows on the **Safety & GPU Limits** card. If
`amdgpu.ppfeaturemask` is missing bit `0x4000` (`PP_OVERDRIVE_MASK`), the kernel does
not expose firmware fan curves on RX 7000 and RX 9000 cards. Add
`amdgpu.ppfeaturemask=0xfff7ffff` to your kernel command line and reboot:
[Driver Setup](driver-setup.md#amd-gpu-fan-control-prerequisite-rdna3) has the steps
for each bootloader. An RX 6000 or older card is monitored and can be tested and
reset, but no profile drives it.

## "A popup said my kernel has a known regression — should I worry?"

When the running kernel matches a published amdgpu regression that affects your
hardware, Ventulus shows a popup, and the warning stays as an **Advisory** row on
System State's **Safety & GPU Limits** card until you acknowledge it. The popup's
details carry the upstream references. The one catalogued today:

- **`rdna_mes_hang_drm_amd_4765` (Critical):** raised on Linux **6.18.0–6.18.6** and
  **6.17.9–6.17.13** with an RDNA3, RDNA3.5 or RDNA4 GPU anywhere in the machine (RX
  7000 / RX 9000, Radeon Pro W7000 and AI PRO cards, and integrated graphics such as
  the Radeon 780M, 890M or 8060S); the message names which. A compute job running
  beside a 3D workload can hang the GPU, and while the system is hung nothing can
  change a fan's speed ([drm/amd #4765](https://gitlab.freedesktop.org/drm/amd/-/issues/4765)).
  It is **fixed in 6.18.7 and 6.19**: update to the **latest 6.18 longterm** release or
  a current **7.x** kernel. **Do not** move to 6.15, 6.16 or 6.17: none was a longterm
  kernel, all are end-of-life, and 6.17.9 onward carries this bug. The check uses the
  version number, so a distribution kernel that already carries the fix may still be
  flagged.

**OK** hides the popup for the rest of this session; it comes back the next time you
start Ventulus. **Don't show again** hides it for good, by recording its id in the
`acknowledged_kernel_warnings` field of `~/.config/ventulus/app_settings.json`. To
bring dismissed advisories back, press **Clear dismissed** beside *Dismissed driver
advisories* in **Settings → Prompts & Dismissals**.

---

Previous: [Profiles and Curves Reference](profiles-and-curves.md) | Next: [Driver Setup](driver-setup.md) | Back to [Table of Contents](README.md)
