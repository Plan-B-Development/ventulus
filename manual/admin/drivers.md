# Drivers and Other Fan Software

Ventulus reaches fans and sensors only through Linux's own drivers: it never talks
to a chip or a USB device directly. This page covers what the packages load for
you, the rules around them, and the other fan software that must not run beside
Ventulus. The step-by-step install of an out-of-tree driver is
[Driver Setup](../driver-setup.md); a driver problem seen as a symptom is in
[Hardware Troubleshooting](../hardware-troubleshooting.md); the chip-by-chip tables
are [Hardware Compatibility](../../docs/19_Hardware_Compatibility.md).

The daemon finds sensors and fan headers by scanning `/sys/class/hwmon/`. A
device appears there only once its kernel driver is loaded.

## What the packages load

The package installs `/etc/modules-load.d/ventulus.conf`,
which loads the common Super-I/O drivers at boot. The kernel cannot load them by
itself, because the chips sit on ISA ports:

| Module | Chipset | Common boards |
|--------|---------|---------------|
| `nct6775` | Nuvoton NCT6775–NCT6799 (incl. NCT5585D and the ASUS NCT6701D, which it reports as `nct6799`) | ASUS (AM4 500-series onward, Intel), ASRock, older MSI (AM4 300/400, the original X570 boards, Intel ≤ 300-series) |
| `it87` | ITE IT87xx/IT86xx: the in-kernel driver covers only older parts plus IT8689E (7.1+) and IT87952E (6.3+); IT8686E/IT8688E/IT8696E/IT8665E need the out-of-tree `frankcrawford/it87`. The daemon reads the running kernel's version for the IT8689E | Gigabyte; ASUS AM4 300/400-series (IT8665E) |
| `w83627ehf` | Winbond W83627EHF/DHG | Older boards |
| `drivetemp` | SATA/SAS drive temperature | All SATA drives |

To stop loading one, comment out its line and run
`sudo systemctl restart systemd-modules-load` (`start` does nothing once the unit
has run) or reboot. Do not rename or delete the file: pacman, dnf and the
tarball's `install.sh` put a missing one back at the next upgrade (apt leaves it
deleted). Every format keeps an edited one, delivering a changed default beside
it as `ventulus.conf.pacnew`, `.rpmnew` or `.new`; apt asks which to keep.

No package loads the file as it installs, so the drivers arrive at the next boot.
To load them without one, run `sudo systemctl restart systemd-modules-load` and
then `sudo systemctl restart ventulusd`, because the daemon looks for fan headers
only as it starts. On most boards other than Gigabyte's, the first command reports
that the job failed, and `systemctl --failed` then lists
`systemd-modules-load.service` after every boot. That is a fault in the package
and stops nothing loading: `nct6775` or `w83627ehf` found no chip, and the
Super-I/O guard below, which loads those two, passes that on as an error. Every
other module still loads; `lsmod` shows which did.

CPU temperature modules (`coretemp` for Intel, `k10temp` for AMD) and SMBus
adapter modules (`i2c-i801`, `i2c-piix4`) load automatically through PCI/ACPI
matching.

## The Super-I/O guard

On a Gigabyte board the package stops `nct6775` and
`w83627ehf` from loading, even though the file above lists them. Gigabyte boards
use ITE Super-I/O chips, which those Nuvoton/Winbond drivers can never bind, and
their probe writes a config-mode unlock that can latch the ITE bridge in front of
a board's second fan chip. That hides the chip until a reboot, and on some boards
until the machine is powered down at the wall. The guard covers every Gigabyte
board, and any board it lists whose firmware reports no vendor. It is
`/usr/lib/modprobe.d/ventulus-superio.conf`, with its helper
`/usr/lib/ventulus/ventulus-superio-guard`; on any other board it loads the module
unchanged. Each time it declines a module it says so in the journal:
`journalctl -b -t ventulus-superio-guard`. To turn it off, create an **empty**
`/etc/modprobe.d/ventulus-superio.conf`: the same name masks it. A file of any
other name does not reliably win, because modprobe reads every directory's files
in one name order and, for a module named twice, the first `install` line read
takes effect. The guard stops only modules. It cannot stop a program that writes
the ports itself: [`sensors-detect`](#about-sensors-detect), or CoolerControl's built-in Super-I/O
detection, which runs each time `coolercontrold` starts and, at a port where no
chip identifies itself, writes each chip family's config-mode unlock
([CoolerControl docs](https://docs.coolercontrol.org/devices/kernel-modules#built-in-super-i-o-detection)).
If you keep CoolerControl on a Gigabyte board, turn that off (Settings → General,
or `sensors_auto_detect = false` in `/etc/coolercontrol/config.toml`). The guard
prevents the latch; it does not clear one already set. For that, see
[Hardware Troubleshooting](../hardware-troubleshooting.md#some-of-my-fan-headers-are-missing--only-5-of-8-show-up).

## ACPI resource conflicts

If a Super-I/O module fails to bind with `ACPI resource
conflict` or *Device or resource busy* in the kernel log, update the driver first:
current builds of the out-of-tree it87 driver avoid the conflict through MMIO on IT8688E,
IT8689E, IT8696E and IT8698E chips. Boards with an IT8686E, or with an IT8792E or
IT87952E second chip, can still need the option below (it87 PRs
[#135](https://github.com/frankcrawford/it87/pull/135) and
[#141](https://github.com/frankcrawford/it87/pull/141), X399 boards; issue
[#139](https://github.com/frankcrawford/it87/issues/139), Z890). For `it87`,
prefer the driver-local `options it87 ignore_resource_conflict=1` in
`/etc/modprobe.d/it87.conf`; the it87 documentation notes that the system-wide
`acpi_enforce_resources=lax` can cause boot failures on some systems. The Nuvoton
drivers (`nct6775`, `nct6687`) have no driver-local option, so for them
`acpi_enforce_resources=lax` on the kernel command line is the only kernel-side
remedy.

## Out-of-tree drivers

Newer boards need drivers that are not in the mainline
kernel, built with DKMS from their upstream projects:
[`frankcrawford/it87`](https://github.com/frankcrawford/it87) for newer ITE chips,
[`Fred78290/nct6687d`](https://github.com/Fred78290/nct6687d) for MSI NCT6687D boards
and some ASRock NCT6686D boards (on Arch, the AUR packages `it87-dkms-git` and
`nct6687d-dkms-git`). [Driver Setup](../driver-setup.md) covers installing,
signing and verifying them on each distribution, and the app's **Hardware** page
shows the steps for the one it runs on. Things to know:

- it87 builds from 2026-09-09 (it87 v2.0) give Gigabyte chips longer
  names, such as `it8696_a008090a`. The daemon strips that suffix, so fan header,
  sensor and voltage ids, and the pump roles, fan names and profiles that use
  them, do not change.
- On Intel Z890 / B860 Gigabyte boards, it87 builds from 2026-09-09 to
  2026-10-01 can fail to load ("Invalid argument") or bind no chip. Rebuild from
  2026-10-02 or later ([it87 PR #140](https://github.com/frankcrawford/it87/pull/140)).
  Current builds need kernel 6.4 or newer.
- Never load `nct6687` with `force=1` on a board whose chip is an NCT679x
  ([Driver Setup § Module parameters](../driver-setup.md#module-parameters-you-may-actually-need)).
- **After a kernel update** the new kernel can boot with its own `it87`, when the
  DKMS build for it failed or its headers were not installed. On most Gigabyte
  boards that driver cannot drive the main chip. The daemon tells the two apart
  (the module's out-of-tree taint) and says so in the Super-I/O advice, with
  `dkms status` and `sudo dkms autoinstall`. It never reads the DKMS tree itself:
  the sandbox keeps it out, and that stays so.
- **A kernel that loads only signed modules** refuses an unsigned out-of-tree build
  (*Key was rejected by service*, or *Operation not permitted* under lockdown).
  `GET /diagnostics/hardware` reports `kernel_security`: Secure Boot, the lockdown
  level, `module.sig_enforce` and the verdict, read from sysfs, securityfs and
  efivarfs. When the verdict is yes and a chip needs a driver that is not loaded,
  the Super-I/O advice says how to enrol the key DKMS signed the driver with.

## About `sensors-detect`

You do not need it: the package loads the common Super-I/O drivers, and the app's
**Hardware** page (its readiness checklist and Super-I/O section) identifies your
board's chips **without probing the hardware**. Treat
`sudo sensors-detect` as a **last resort**, at your own risk: its probing "can access
chips in a way these chips do not like, causing problems ranging from SMBus lockup to
permanent hardware damage (a rare case, thankfully)"
([sensors-detect(8)](https://man.archlinux.org/man/extra/lm_sensors/sensors-detect.8.en)).
Its default answers are not a safe mode: the Super-I/O scan, which writes to I/O ports
0x2E and 0x4E to find the chip, defaults to *yes*, and the
[script](https://github.com/lm-sensors/lm-sensors/blob/master/prog/detect/sensors-detect)
itself calls it only "usually safe"; the man page warns that `--auto`, which takes
every default, "isn't necessarily safe". If you do run it, answer each question yourself, and do not force a probe it
would skip by default.

**Never run it on a Gigabyte board.** Its Super-I/O
scan can wedge the Super-I/O bridge so that a second chip vanishes, the package's
guard cannot stop it (it probes the ports itself rather than loading a module), and
**a reboot may not bring the chip back: power down at the wall**, because the bridge
keeps standby power (see
["Some of my fan headers are missing"](../hardware-troubleshooting.md#some-of-my-fan-headers-are-missing--only-5-of-8-show-up)).

There is also nothing to gain by running it there: it has no entry for the ITE chips
on essentially every modern Gigabyte board
([Driver Setup § Module parameters](../driver-setup.md#module-parameters-you-may-actually-need)).
If you ran it and let it save a module list, the
[undo index](safety-and-recovery.md#undo-index) says where that list is.

## Other fan software

Only one program may drive a fan. A fan header's speed is one value, so two
programs writing it overwrite each other and the fan's speed swings between them.
Before Ventulus drives your fans, stop and disable each of these that you have:

| Program | Its service |
|---|---|
| `fancontrol` (lm_sensors) | `fancontrol.service`, or started by hand (`/run/fancontrol.pid` exists while it runs) |
| CoolerControl | `coolercontrold.service` |
| fan2go | `fan2go.service` |
| thinkfan | `thinkfan.service` |
| LACT (GPU fans) | `lactd.service` |
| CoreCtrl (GPU fans) | none: it runs in your desktop session |
| A vendor tool, or a unit or script of your own that writes fan speeds | yours |

The app's **System State** page reports which of these services are installed,
enabled or running, and the support bundle includes the same. [Migrating from Another Fan Program](../migrating.md) is the step-by-step
switch, including the drivers to keep and how to go back. The BIOS or the board's
embedded controller can also take a header back; that is in
[Hardware Troubleshooting § The BIOS keeps taking fan control back](../hardware-troubleshooting.md#the-bios-keeps-taking-fan-control-back).

---

Back to [Administration](README.md)
