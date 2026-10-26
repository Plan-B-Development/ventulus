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

## Find your symptom

| What you see | Where to start |
|---|---|
| The app says **Disconnected**, or shows a banner about versions | [The app cannot reach the daemon](#the-app-cannot-reach-the-daemon) |
| No motherboard fans at all | [No motherboard fans at all](#no-motherboard-fans-at-all) |
| Temperatures, but no fans | [Temperatures appear, but no fans](#temperatures-appear-but-no-fans) |
| You installed a driver and nothing changed | [A driver is installed, but Ventulus still sees nothing](#a-driver-is-installed-but-ventulus-still-sees-nothing) |
| Fans disappeared after a kernel update | [It worked before a kernel update](#it-worked-before-a-kernel-update) |
| Fewer sensors than you expect | [Sensors missing or fewer than expected](#sensors-missing-or-fewer-than-expected) |
| Every header is read-only | ["All my hwmon headers show as read-only"](#all-my-hwmon-headers-show-as-read-only) |
| A fan's speed shows, but changing it does nothing | [A fan's speed shows, but the fan cannot be controlled](#a-fans-speed-shows-but-the-fan-cannot-be-controlled) |
| Some headers are missing, on a Gigabyte board | ["Some of my fan headers are missing"](#some-of-my-fan-headers-are-missing--only-5-of-8-show-up) |
| A speed changes, then changes back | [A fan's speed changes, then changes back](#a-fans-speed-changes-then-changes-back), and [The BIOS keeps taking fan control back](#the-bios-keeps-taking-fan-control-back) |
| A header says *no fan detected* | ["No fan detected" on a header](#no-fan-detected-on-a-header) |
| Every fan at full speed, or at about 40 % | ["Fans run at full speed regardless of profile"](#fans-run-at-full-speed-regardless-of-profile) |
| A fan another program could drive does nothing here | [It worked in another fan-control program](#it-worked-in-another-fan-control-program) |
| A header shows a generic name such as `pwm2` | [Per-board hwmon header label resolver](#per-board-hwmon-header-label-resolver) |
| A GPU fan does not respond | [Intel Arc](#intel-arc-gpus-are-monitor-only), [NVIDIA](#nvidia-gpus-are-monitor-only), or [AMD: *feature_unavailable*](#gpu-fan-control-says-feature_unavailable) |

## The app cannot reach the daemon

The status banner reads **Disconnected**, the Dashboard shows its disconnected
screen, and a banner says *Daemon disconnected — retrying...*. The app tries again
every second and reconnects by itself as soon as the daemon answers, so there is no
need to restart it. Work down this list:

1. **Is the daemon running?** `systemctl is-active ventulusd` prints `active` when it
   is.
   - `inactive`: it is installed but not started. `sudo systemctl enable --now ventulusd`
     starts it now and at every boot; the Dashboard offers the same command when the
     service is not enabled.
   - `failed`: `systemctl status ventulusd` and `journalctl -u ventulusd -b` say why.
     The usual causes are a bad edit to `/etc/ventulus/daemon.toml`, which the journal
     names, and a second copy of the daemon already running, for example one started
     by hand in a terminal: the newcomer exits with status 75 and *another ventulusd
     is already running*. The daemon's
     [User Guide](https://github.com/Plan-B-Development/ventulusd/blob/main/docs/USER_GUIDE.md#the-daemon-does-not-start)
     has the rest.
2. **Is the socket there?** `ls -la /run/ventulus/ventulus.sock` should show
   `srw-rw-rw-`. Every local user can open it, so there is no group to join and no
   need to log out. If the daemon is running and the file is missing, restart the
   daemon (`sudo systemctl restart ventulusd`). A socket file left behind by a daemon
   that crashed does no harm: the next start removes it.
3. **Did you point the app somewhere else?** `ventulus --socket <path>` must name the
   path the daemon listens on, `[ipc] socket_path` in `/etc/ventulus/daemon.toml`.
   Leave both at the default unless you have a reason to move them.
4. **Connected, with a banner about versions.** The app and the daemon do not need
   matching version numbers: the app asks the daemon what it supports and hides what
   an older daemon lacks. Two banners mean a real mismatch:
   - *Daemon upgrade required*: the daemon is too old for this app to control fans
     through it. **Apply**, **Stop** and **Manual** are off until you upgrade
     `ventulusd`.
   - *This GUI is older than the daemon supports*: fan control is unaffected, because
     the daemon drives the fans itself, but some screens may not show everything it
     can do. Upgrade the app.
5. **Connected, but no fans.** The daemon starts and answers even when it found
   nothing to control. A **No hardware** message on the Dashboard is a hardware
   question: see [No motherboard fans at all](#no-motherboard-fans-at-all).

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
Its default answers are not a safe mode: the Super-I/O scan, which writes to I/O ports
0x2E and 0x4E to find the chip, defaults to *yes*, and the
[script](https://github.com/lm-sensors/lm-sensors/blob/master/prog/detect/sensors-detect)
itself calls it only "usually safe"; the man page warns that `--auto`, which takes
every default, "isn't necessarily safe". If you do run it, answer each question yourself, and do not force a probe it
would skip by default. **Never run it after boot on a Gigabyte board.** Its Super-I/O
scan can wedge the Super-I/O bridge so that a second chip vanishes, the package's
guard cannot stop it (it probes the ports itself rather than loading a module), and
**a reboot may not bring the chip back: power down at the wall**, because the bridge
keeps standby power (see
["Some of my fan headers are missing"](#some-of-my-fan-headers-are-missing--only-5-of-8-show-up)).

## No motherboard fans at all

Motherboard fan headers belong to the board's fan chip, usually a Super-I/O chip from
ITE or Nuvoton, and the daemon reaches them only through that chip's kernel driver.
Work down these checks in order:

1. **Has the kernel published a fan chip?**

   ```bash
   cat /sys/class/hwmon/hwmon*/name
   ```

   A fan chip appears under its own name, such as `it8696`, `nct6798` or `nct6687`.
   If the list holds only names such as `k10temp`, `coretemp`, `nvme`, `amdgpu`,
   `acpitz`, `gigabyte_wmi` or `asusec`, no fan chip has a driver yet: those are the
   processor, drives, graphics card and firmware interfaces (see
   [Temperatures appear, but no fans](#temperatures-appear-but-no-fans)).
2. **Is a fan-chip driver loaded?**

   ```bash
   lsmod | grep -E '^(nct6775|nct6683|nct6687|it87|w83627ehf|f71882fg) '
   ```

   - **Nothing, straight after installing Ventulus:** the package's module list loads
     the drivers at boot. Reboot, or load them now as
     [Getting Started § After installing](getting-started.md#after-installing) shows.
   - **Nothing, after a reboot:** a driver that finds no chip of its own does not stay
     loaded, so your chip needs a driver that is not loaded yet. Step 3 names it. Do
     not load drivers by guesswork: on a Gigabyte board the wrong one can hide a second
     fan chip until the power is cut.
   - **A driver you installed yourself:** see
     [A driver is installed, but Ventulus still sees nothing](#a-driver-is-installed-but-ventulus-still-sees-nothing).
3. **Which chip is it, and what does it need?** The **Hardware** page identifies your
   board's chip without probing it, and the **Hardware Registry** on **System State**
   names the driver it needs. *Motherboard Super-I/O chip detected without its driver
   loaded* means the chip is there and the driver is the missing piece: the row names
   it, and [Driver Setup](driver-setup.md) installs it if it is not part of your
   kernel. *No motherboard Super-I/O chip was detected* sends you to step 4. Chip by
   chip, the support list is in [Hardware Compatibility](../docs/19_Hardware_Compatibility.md).
4. **Does your machine reach its fans another way?** Not every machine has a fan chip
   Linux can drive:
   - **Laptops** run their fans from the embedded controller, and only some have a
     Linux driver that exposes them: Dell's `dell_smm` on the models the kernel allows,
     and ThinkPads through `thinkpad_acpi` with `fan_control=1`
     ([kernel docs](https://docs.kernel.org/admin-guide/laptops/thinkpad-acpi.html#fan-control-and-monitoring-fan-speed-fan-enable-disable)).
     Many laptops expose none.
   - **Some prebuilt desktops** run their fans from firmware that no kernel driver
     reaches.
   - **Fans on a USB hub or cooler** are reached only through that device's own kernel
     driver: see [Supported coolers and controllers](getting-started.md#supported-coolers-and-controllers).
   - **An OpenFAN controller** has its own page: [OpenFAN Controller](openfan-controller.md).
5. **The kernel shows the fans, but Ventulus does not.** If step 1 lists your fan chip
   but the **Hardware** page shows none of its headers: the daemon looks
   for fan headers only when it starts. Restart it with
   `sudo systemctl restart ventulusd`; **Rescan Hardware** picks up new sensors, not
   new headers. If the headers are still missing after a restart, that is a fault in
   Ventulus: report it with a [support bundle](diagnostics.md#export-support-bundle).

## Temperatures appear, but no fans

Temperatures and fans often come from different drivers, so seeing temperatures
proves nothing about fan control:

| Driver | What it reports | Fans |
|---|---|---|
| `k10temp` (AMD), `coretemp` (Intel) | The processor | None |
| `nvme`, `drivetemp` | Drives | None |
| `amdgpu` and other graphics drivers | The graphics card | Only the card's own fan |
| `gigabyte_wmi` | Six board temperatures, read through the firmware | None |
| `asus_ec_sensors` (listed as `asusec`), `asus_wmi_sensors` | Board temperatures and some fan speeds, read through the firmware | Read-only: they never set a speed |
| `acpitz` | The firmware's thermal zone | None |

None of them can drive a motherboard fan header. That is the job of the board's fan
chip, which needs its own driver, so identify that chip separately:
[No motherboard fans at all](#no-motherboard-fans-at-all), step 3, does it. On a
Gigabyte board `gigabyte_wmi` often loads by itself, and it does not mean the fan
chip has a driver: that driver is `it87`.

## A driver is installed, but Ventulus still sees nothing

Each check below is a link in the chain from an installed driver to a fan on the
**Hardware** page. Go through them in order:

1. **Built for the kernel you run.** `dkms status` must list the running kernel
   (`uname -r`) as `installed`. If it shows only *added* or *built*, or nothing for
   your kernel, install that kernel's headers
   ([Driver Setup, Step 2](driver-setup.md#step-2--prerequisites-dkms--kernel-headers))
   and run `sudo dkms autoinstall`.
2. **Loaded.** `lsmod | grep -E '^(it87|nct6687) '` lists the driver once it is loaded.
   If it is missing, load it by hand and read the error: `sudo modprobe it87` (or
   `nct6687`).
   - *Key was rejected by service* or *Operation not permitted*: your kernel loads only
     signed drivers. See [Secure Boot and DKMS modules](driver-setup.md#secure-boot-and-dkms-modules).
   - *No such device*: the driver found no chip it supports. Check that it is the
     driver the **Hardware Registry** names for your chip.
   - *Invalid argument* on an Intel Z890 or B860 Gigabyte board: a known fault in some
     2026-09 driver builds (Case A2 under
     ["Some of my fan headers are missing"](#some-of-my-fan-headers-are-missing--only-5-of-8-show-up)).
   - *Module not found*: it is not installed for this kernel. Go back to step 1.
3. **Your build, not the kernel's own.** The kernel ships its own `it87`, which
   cannot drive every chip, and its own `nct6683`, which also calls its device
   `nct6687` and publishes it read-only:
   [Is the loaded driver the one you installed?](driver-setup.md#is-the-loaded-driver-the-one-you-installed)
   tells them apart.
4. **Bound to your chip.** `cat /sys/class/hwmon/hwmon*/name` lists the chip, and for
   `it87`, `sudo dmesg | grep -i it87` shows a *Found … chip* line for each chip the
   driver took.
5. **Loaded at every boot.** The package's module list loads `it87` at boot.
   `nct6687` is not on it and needs a file of its own: see
   [the nct6687d driver needs two more lines](driver-setup.md#every-distribution-the-nct6687d-driver-needs-two-more-lines).
6. **Permissions.** Nothing to change. The daemon runs as root and reads and writes the
   files itself, and the app never touches them, so Ventulus needs no udev rule, group
   or `chmod`.
7. **The daemon has looked again.** The daemon looks for fan headers only when it
   starts: `sudo systemctl restart ventulusd`, or reboot. **Rescan Hardware** adds
   sensors, not headers.

## It worked before a kernel update

When fans that came from an out-of-tree driver vanish after a kernel update, the
driver is almost always not running on the new kernel. In order of likelihood:

- **It was not built for the new kernel.** DKMS builds the driver for each kernel only
  when that kernel's headers are installed. `dkms status` shows whether it did;
  [After a kernel update](driver-setup.md#after-a-kernel-update) has the commands. On
  a Gigabyte board, Ventulus usually says so itself: the missing-chip warning reads
  *The it87 driver loaded is the kernel's own*.
- **It was built but does not load.** `sudo modprobe it87` (or `nct6687`) gives the
  reason, as in
  [A driver is installed, but Ventulus still sees nothing](#a-driver-is-installed-but-ventulus-still-sees-nothing).
  *Key was rejected by service* means the new build is unsigned or signed with a key
  this machine does not trust: `mokutil --test-key /var/lib/dkms/mok.pub` says
  whether the DKMS key is enrolled.
- **It does not build for the new kernel yet.** A new kernel can break an out-of-tree
  driver until upstream catches up. Boot the previous kernel in the meantime:
  [Staying current](driver-setup.md#staying-current) says which distributions keep it.
- **The kernel now has a driver of its own.** From Linux 7.1 the kernel's `it87` drives
  the IT8689E, so the out-of-tree driver is optional there:
  [IT8689E: the kernel's own driver](driver-setup.md#it8689e-the-kernels-own-driver-from-linux-71).
- **Something changed how modules load.** `grep -Ev '^(#|$)' /etc/modules-load.d/ventulus.conf`
  should still list the drivers. A driver you added to the initramfs yourself has to
  be rebuilt into it; the commands under
  [If it still fails after a genuine power cut](#if-it-still-fails-after-a-genuine-power-cut)
  list what an initramfs carries.

If an AMD graphics card misbehaves after the update instead, look for the kernel
advisory described in
["A popup said my kernel has a known regression"](#a-popup-said-my-kernel-has-a-known-regression--should-i-worry).

## "All my hwmon headers show as read-only"

Open the **System State** page:

- If the **Hardware Registry** lists the expected chip but its **Driver Status** is
  *not loaded*, the kernel module is missing. The row names the module to install
  (for example the out-of-tree `frankcrawford/it87` driver for Gigabyte AM5 boards), and
  the Hardware page's **How to enable** section gives the steps for your distribution.
- If the driver is loaded but the summary line says **0 writable**, the bound driver
  publishes the pwm files read-only. On MSI and ASRock Nuvoton boards that usually
  means the in-kernel `nct6683` is bound; it never makes PWM writable outside Mitac
  OEM systems, so you need the out-of-tree driver the registry names. See
  [Driver Setup](driver-setup.md).
- If the headers are writable but a fan test reports *BIOS/EC reverted pwm_enable*,
  the firmware is taking control back: see
  [The BIOS keeps taking fan control back](#the-bios-keeps-taking-fan-control-back).
- If an ACPI resource conflict blocks the driver, the kernel log says so:
  `sudo dmesg | grep -i "conflicts with OpRegion"`. Ventulus cannot check this for you, because the daemon's
  sandbox hides the kernel log. For `it87`, prefer `options it87 ignore_resource_conflict=1`;
  `acpi_enforce_resources=lax` is the system-wide fallback, and the only option for
  `nct6775`.

## A fan's speed shows, but the fan cannot be controlled

A speed reading needs only a tachometer input; control needs a writable output that
drives the same fan. The header's card on the **Hardware** page shows which you have:
its **Details** list the PWM write, readback, `pwm_enable`, PWM/DC mode and reclaim
count ([System Health § Cooling Hardware](diagnostics.md#cooling-hardware)). Then:

- **There is no control for that input.** Many boards have more speed inputs than
  control outputs, and some drivers only read: `asus_ec_sensors` reports the CPU_Opt,
  chipset and VRM fans but never sets them, and the it87 board catalogue lists extra
  fan inputs with no speed control. A speed with no header to drive is not a fault.
- **The header is read-only.** The driver publishes the control, but not as writable:
  see ["All my hwmon headers show as read-only"](#all-my-hwmon-headers-show-as-read-only).
- **The header is in the wrong mode for the fan.** A header drives a fan by PWM signal
  (4-pin fans) or by voltage, called DC mode (3-pin fans). A 3-pin fan has no PWM wire,
  so on a header in PWM mode it runs at full speed whatever duty you set. **Details**
  shows the mode; set it in the BIOS
  ([Driver Setup § BIOS settings](driver-setup.md#step-5--bios-settings-the-half-people-skip)).
- **The firmware takes the header back.** See
  [The BIOS keeps taking fan control back](#the-bios-keeps-taking-fan-control-back).
- **The writes fail.** Permissions are not the cause with Ventulus: the daemon runs as
  root and writes the files itself. A write the driver refuses is logged in the
  daemon's journal, which the **Logs** page shows in its inspector's **Journal** tab,
  or `journalctl -u ventulusd -b | grep 'hwmon write failed'`.
- **The speed comes from another fan.** A splitter or a hub reports one fan's speed,
  usually the one on its first connector, while the header drives all of them. A hub
  powered from SATA takes only the PWM signal from the header. An AIO pump on a header
  can run its own speed. **Discover Control Path**
  ([Fan Tests](fan-tests.md#discover-control-path)) finds which header moves which
  speed reading, and **Test PWM Control** reports *PWM accepted but RPM did not change*
  when the write held but nothing it measures responded.

## "Some of my fan headers are missing — only 5 of 8 show up"

Open the **System State** page. If a *Super-I/O chip not enumerated* card (the
dual-chip warning) sits under the **System Health Overview**, your motherboard is one
of the Gigabyte boards with two ITE chips (X870E AORUS MASTER, X670E AORUS MASTER,
Z790 AORUS MASTER and others), and one of them did not appear. Ventulus knows which
chips to expect from its own list of boards or, for a Gigabyte board that list does
not include, from the board's firmware layout. When the layout was the source, the
warning says so and names it.

**Case A: the driver is not loaded.** Run `sudo dmesg | grep -i it87` (or
`journalctl -k -b | grep -i it87`). Each chip the driver found prints a line such as
`Found IT8696E chip at 0xa40 … revision 0`. If there are no `it87` lines at all, or
`modprobe` says "module not found":

1. Install the `frankcrawford/it87` driver (see [Driver Setup](driver-setup.md#step-3--install-the-driver)). Current builds reach
   the secondary chip's extra headers through MMIO, which is on by default.
2. Reboot, then click **Rescan Hardware**.

**Case A1: the kernel's own it87 is loaded.** The warning then says *The it87 driver
loaded is the kernel's own, and it cannot drive* the missing chip. The kernel ships an
`it87` too, and it drives only some of these chips. If you had installed the
out-of-tree driver, a kernel update is the usual cause: DKMS builds the driver once
for each kernel, and when that build failed, or the new kernel's headers were not
installed, the new kernel booted with its own `it87`.

1. Run `dkms status`. It lists each kernel the driver is built and installed for.
   If it lists nothing for `it87`, the driver was never installed: go to Case A.
2. Install the headers for the kernel you are running
   ([Driver Setup, Step 2](driver-setup.md#step-2--prerequisites-dkms--kernel-headers)), then
   build the driver for it: `sudo dkms autoinstall`.
3. Reboot, then click **Rescan Hardware**.

If loading it then fails with *Key was rejected by service* or *Operation not
permitted*, your kernel only loads signed drivers. The warning says so when the daemon
can tell. See [Secure Boot and DKMS modules](driver-setup.md#secure-boot-and-dkms-modules).

**Case A2: an Intel Z890 / B860 board on a 2026-09 driver build.** If `modprobe it87`
fails with *Invalid argument* after a line like `H2RAM set_slot(1,…) failed: -22`, or
the log shows *Found IT8696E chip* but no chip appears, the driver build is at fault,
not your board: builds from 2026-09-09 to 2026-10-01 fail this way on Gigabyte Z890 /
B860 boards ([it87 #139](https://github.com/frankcrawford/it87/issues/139),
[#138](https://github.com/frankcrawford/it87/issues/138)). It was fixed on
2026-10-02 ([PR #140](https://github.com/frankcrawford/it87/pull/140)):

1. Rebuild the driver from current source, with the
   [update commands in Driver Setup](driver-setup.md#updating-the-driver) for your distribution.
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
debug (the Arch, CachyOS, Debian, Ubuntu and Fedora kernels are), you can make the driver print it:

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

- another `modules-load.d` file, the module list `sensors-detect` saved (`/etc/conf.d/lm_sensors`
  on Arch, `/etc/modules` on Debian and Ubuntu, `/etc/sysconfig/lm_sensors` on Fedora), or a distribution default,
  loading `nct6775` where the guard has not acted;
- `sensors-detect`, run by hand or by a script;
- a Super-I/O module baked into your initramfs
  (on Arch, `for i in /boot/initramfs-*.img; do echo "$i"; lsinitcpio "$i" | grep -E 'nct6775|w83627|it87'; done`,
  and CachyOS names its images `initramfs-linux-cachyos*.img`; on Debian and Ubuntu,
  `sudo lsinitramfs /boot/initrd.img-$(uname -r) | grep -E 'nct6775|w83627|it87'`; on Fedora,
  `sudo lsinitrd | grep -E 'nct6775|w83627|it87'`);
- any other tool that probes Super-I/O ports.

**Do not** reach for these. They are known not to help, and one makes things worse:

- **`mmio=on`**: already the driver default; setting it changes nothing.
- **Reinstalling or rebuilding the it87 driver**: the block is not a driver bug, and it reproduces
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

- **Gigabyte:** a `frankcrawford/it87` build from 2026-08-24 or later carries the fixes
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

## A fan's speed changes, then changes back

Start with the header's card on the **Hardware** page, which shows the PWM the daemon
**requested** next to the PWM the hardware **reports back**.

**They disagree:** something other than Ventulus set the duty.

- **Another program.** A second fan-control program, a vendor tool or a script writing
  the same header. The daemon corrects it three times, then flags the header **Fan
  duty is not holding** (above). Find and stop the other program:
  [Migrating § Check that nothing still holds a header](migrating.md#check-that-nothing-still-holds-a-header).
- **The BIOS or embedded controller.** It switches the header back to automatic: see
  [The BIOS keeps taking fan control back](#the-bios-keeps-taking-fan-control-back).

**They agree, but the speed moves on its own:** the device has its own controller. An
AIO pump or a fan hub can follow its own curve whatever duty it is given, and Ventulus
drives only what the device lets the kernel set.

**The requested value itself changed:** Ventulus asked for it, and that is usually
deliberate.

- **A manual override ended.** It lasts while the app keeps it alive; when you switch
  **Manual** off or close the app, the curve resumes
  ([Controls § Inline manual override](controls.md#inline-manual-override)).
- **The daemon's thermal safety acted.** It runs fans faster over everything else:
  see ["Fans run at full speed regardless of profile"](#fans-run-at-full-speed-regardless-of-profile).
- **A fan test or Identify ran.** Each drives the header while it runs, then gives it
  back.
- **The curve followed its sensor.** A sensor that jumps by a few degrees moves the
  fans with it. A wider [slow-down band](profiles-and-curves.md#slow-down-band) or a
  steadier sensor keeps them still; a rising temperature still speeds them up at once.

**On a graphics card,** another GPU tool (LACT, CoreCtrl) or a GPU reset takes the fan
back; on an RX 6000 or older, **Test GPU Fan Control** reports it as *GPU fan left
manual mode*.

Two copies of Ventulus cannot fight over a fan: only the daemon writes fan speeds,
only one daemon can run (a second exits at once), and the app and the tray only ask
it.

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

## It worked in another fan-control program

Another program driving a fan does not prove that Ventulus can. Work out how the old
program reached it:

- **Through the kernel's fan controls (hwmon), as Ventulus does.** `fancontrol`,
  fan2go, and CoolerControl for motherboard headers all do. Ventulus reaches
  the same headers once the old program has stopped and handed them back:
  [Migrating from Another Fan Program](migrating.md).
- **Through a driver it installed.** CoolerControl, for example, offers out-of-tree
  `it87` and `nct6687` packages from its own repository. If you removed that driver
  along with the program, the headers went with it: reinstall it
  ([Driver Setup](driver-setup.md)), or keep it if you still have it.
- **By talking to a USB device directly.** `liquidctl`, CoolerControl's USB support,
  OpenRGB and vendor tools reach coolers and hubs that have no kernel driver. Ventulus
  reaches a device only through a kernel driver, so such a device stays invisible to
  it: [Supported coolers and controllers](getting-started.md#supported-coolers-and-controllers)
  lists what it can drive.
- **Through a GPU interface Ventulus leaves alone.** LACT and CoreCtrl can drive an AMD
  RX 6000 or older card's fan, which Ventulus monitors but does not drive in a
  profile; NVIDIA tools drive NVIDIA fans, which Ventulus only monitors
  ([NVIDIA GPUs are monitor-only](#nvidia-gpus-are-monitor-only)).
- **With permissions it set up.** A udev rule that opens a USB device or the fan files
  to your user is for that program. Ventulus needs none: its daemon runs as root. Leave
  such a rule while anything else uses it.

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
5. **The board catalogue name**, on Gigabyte boards (next section).
6. **The node id** (`pwm1`), when nothing above knows the board.

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

### Board header names from the it87 catalogue

**What it does.** On a Gigabyte board running the out-of-tree
[it87 driver](driver-setup.md), the board publishes its firmware layout, a code
called the SIV (`A008090A` on an X870E AORUS MASTER). The daemon looks the layout up
in a catalogue built from the it87 project's Gigabyte sensor configurations and names
the fan headers and temperatures the driver left unnamed: `CPU_FAN`,
`SYS_FAN5_PUMP`, `VRM MOS`. (Names for extra fan inputs with no speed control appear
only in the Board layout panel.) A header's name becomes its name everywhere in
Ventulus, and it does what the same label from the driver would do:

- a header named `…_PUMP` is protected as a pump: identify changes its speed instead
  of stopping it, no [fan test](fan-tests.md) drives it below the pump floor, and a
  profile holds it at that floor (30 %, or 70 % on a header in DC mode);
- a header named `CPU_FAN` or `CPU_OPT` gets the 30 % minimum in a fan role.

A `…_PUMP` header takes a pump or a fan; the name says what the header is for, not
what is plugged into it. Temperatures get their names for display only: a
temperature the catalogue calls `CPU` is a board thermistor, not your CPU's own
sensor, and Ventulus never treats it as one. An `EC_TEMP` header reads a thermistor
probe you plug in; without one, ignore its reading.

**How sure it is.** The names come from configurations other owners wrote and
checked for their boards, matched on the layout code rather than the board name, and
are **not verified on your board**. The header's card says so ("Named from the it87
board catalogue for layout …; not verified on this board."), and the header's details
show the board name and where the shown name came from. The **Board layout** panel on the Hardware page
shows the layout code, whether the catalogue lists your board model for it, and
every name it gave. If a name is wrong, set the header's role on its card (**Set
role…**): a role you assign can add pump protection or a floor, but can never take
away the protection a pump name gives. Rename the header to change what it is
called.

**Why some names stay generic.**

- Your driver publishes no layout code: the in-kernel `it87`, or an out-of-tree
  build older than the one that added it. See [Driver Setup](driver-setup.md).
- You installed the driver after the daemon started. The daemon reads the layout
  once, as it starts: restart it (`sudo systemctl restart ventulusd`), or reboot.
- The layout is not in the catalogue yet.
- The layout does not map that channel ("Not mapped for this board"). That does not
  mean nothing is connected.
- Two independent readings of GIGABYTE's own sensor tables disagree about that
  channel, so it is left unnamed rather than guessed.
- The driver already names the channel. A driver label always wins.

**How to help.** If a name is wrong, or a layout is missing, open an issue with the
output of `cat /sys/class/gigabyte/id/gigabyte_siv`, your board model, and which
physical header the fan is on (the Fan Wizard finds that out safely). The fix belongs
upstream in the it87 project's Gigabyte configurations, from which the catalogue is
regenerated.

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
