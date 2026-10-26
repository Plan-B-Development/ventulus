# Migrating from Another Fan Program

This page is for a machine where another program has already controlled the fans:
`fancontrol`, CoolerControl, fan2go, thinkfan, a GPU tool such as LACT or CoreCtrl,
`liquidctl` in a startup script, or a script of your own. If none of these has run on
this machine, follow the [Setup Checklist](setup-checklist.md) instead.

A switch is not a clean install. The old program can leave services that still start
at boot, driver options the hardware needs, and fans held at its last speed. So the
order matters: take stock, sort the drivers from the control software, stop the
control software, let Ventulus take over and check it, and only then clean up. Nothing
here asks you to uninstall or delete anything before the last step.

Ventulus reads and writes the fans through the same kernel drivers those programs
use. A driver you installed for one of them is usually exactly what Ventulus needs, so
only the program that decides the fan speeds changes.

**Install Ventulus first**, as [Getting Started](getting-started.md#installation)
describes, including [After installing](getting-started.md#after-installing). Its
**System State** and **Hardware** pages help with the inventory below. Do not run a
fan test or the Fan Wizard, or apply a profile, until Step 4: until then the daemon
drives no fan, except in a thermal emergency, when it runs every fan at full speed.

## Step 1 — Take stock

Find out what is there before you stop or remove anything. These commands only read,
and none needs `sudo`:

```bash
# Fan-control services: installed, and whether each starts at boot
systemctl list-unit-files --type=service --no-pager | grep -iE 'fancontrol|coolercontrol|fan2go|thinkfan|lactd'
# ...and which of them is running now
systemctl list-units --type=service --no-pager | grep -iE 'fancontrol|coolercontrol|fan2go|thinkfan|lactd'
# fancontrol started by hand rather than as a service: this file exists while it runs
ls /run/fancontrol.pid
# Your own units, scripts and autostart entries that set fan speeds
grep -rlsE 'pwm[0-9]|liquidctl|fancontrol' /etc/systemd/system /etc/rc.local ~/.config/systemd/user ~/.config/autostart
# Out-of-tree drivers built with DKMS, and the kernels each is built for
dkms status
# Driver options and boot-time driver lists for fan chips
grep -rsE '^[^#]*(it87|nct6|w83|f71|thinkpad)' /etc/modprobe.d /etc/modules-load.d /etc/conf.d/lm_sensors /etc/modules
# Kernel parameters
cat /proc/cmdline
```

An `ls` that says *No such file or directory* means no `fancontrol` is running by
hand, and a `grep` that prints nothing found nothing. Check cron as well
(`crontab -l` and `sudo crontab -l`) if you ever set fan speeds from a scheduled job.
If `dkms` is not installed, you have no DKMS drivers. In the driver lists,
`/etc/modules-load.d/ventulus.conf` is Ventulus's own.

Write down two more things the commands cannot see: which fans the old program
controlled, and any BIOS setting you changed for it (a header set to *Full Speed*, a
changed curve). On the Ventulus side, the **Hardware Registry** on **System State**
lists each fan chip, the driver bound to it, and whether that driver is part of the
kernel.

## Step 2 — Sort the drivers from the control software

A driver makes the hardware visible to Linux: it is what puts the fan headers under
`/sys/class/hwmon`. A control program decides what to write there. Stopping the old
program does not mean removing its driver, because Ventulus needs the same one.

| What Step 1 found | What it is | What to do now |
|---|---|---|
| An `it87`, `nct6687d` or other driver in `dkms status`, whether from the AUR, from [CoolerControl's packages](https://docs.coolercontrol.org/devices/motherboards#it87-ite) or built from source | An out-of-tree driver | **Keep it.** Ventulus drives the fans through it |
| An option for your fan chip's driver in `/etc/modprobe.d/` (`ignore_resource_conflict=1`, `force_id=…`) | How that driver binds to the chip | **Keep it** |
| Your fan chip's driver in a boot-time list (`/etc/modules-load.d/`, `/etc/conf.d/lm_sensors` or `/etc/modules`) | Loads the driver at boot | **Keep it for now.** Ventulus's own list loads `nct6775`, `it87`, `w83627ehf` and `drivetemp`, but not `nct6687` |
| `acpi_enforce_resources=lax` or `amdgpu.ppfeaturemask=…` in `/proc/cmdline` | Lets a driver bind to its chip, or unlocks AMD GPU fan control | **Keep it** |
| `thinkpad_acpi` with `fan_control=1` | Makes a ThinkPad's fan writable at all ([kernel docs](https://docs.kernel.org/admin-guide/laptops/thinkpad-acpi.html#fan-control-and-monitoring-fan-speed-fan-enable-disable)) | **Keep it** |
| `fancontrol`, CoolerControl, fan2go, thinkfan, LACT, CoreCtrl, or a unit or script of your own | Control software | **Stop it** (Step 3) |
| Their configuration: `/etc/fancontrol`, `/etc/coolercontrol/`, `/etc/fan2go/` | Settings for a program that will no longer run | **Leave it** where it is |
| The `lm_sensors` package | The `sensors` and `sensors-detect` commands; on Arch and Fedora it also carries `fancontrol` | Ventulus does not need it. **Leave it** for now |

## Step 3 — Stop the old control software

Stop and disable each control service Step 1 found, under whatever name it has.
`disable --now` stops it now and keeps it from starting at the next boot. It removes
nothing:

```bash
sudo systemctl disable --now fancontrol.service      # lm_sensors' fancontrol
sudo systemctl disable --now coolercontrold.service  # CoolerControl
sudo systemctl disable --now fan2go.service          # fan2go
sudo systemctl disable --now thinkfan.service        # thinkfan
```

What each one does to the fans as it stops:

- **fancontrol** puts each header back to the mode and speed it found when it started,
  and runs any header it cannot put back at full speed
  ([the script](https://github.com/lm-sensors/lm-sensors/blob/master/prog/pwm/fancontrol)).
  That takes a normal stop: if it was killed outright, its headers stay as it left
  them, and a `/run/fancontrol.pid` with no `fancontrol` running
  (`pgrep -a fancontrol` prints nothing) is left over. A reboot clears both.
- **CoolerControl** sets each header back to the mode it read when `coolercontrold`
  started ([source](https://gitlab.com/coolercontrol/coolercontrol/-/blob/main/coolercontrold/daemon/src/repositories/hwmon/fans.rs)),
  except on the ThinkPad and ASUS laptop fan drivers, which it hands back in automatic
  mode ([source](https://gitlab.com/coolercontrol/coolercontrol/-/blob/main/coolercontrold/daemon/src/repositories/hwmon/devices.rs)).
- **fan2go** restores each fan's original control mode, unless its configuration sets
  `onExit` to something else ([README](https://github.com/markusressel/fan2go#advanced-options)).

The rest:

- **Your own units and scripts** that set fan speeds: disable them the same way, or
  remove the lines that write `pwm` files.
- **`liquidctl` in a startup unit or script** sets its speeds again at every boot.
  Where a kernel driver is bound to the cooler, liquidctl goes through that driver
  ([liquidctl(8)](https://man.archlinux.org/man/extra/liquidctl/liquidctl.8.en)), the
  same one Ventulus drives. For a cooler Ventulus will drive, remove the
  `set … speed` commands. Lighting and screen commands can stay.
- **GPU tools** (LACT, CoreCtrl): give each GPU fan one owner. A tool can keep a GPU
  that no Ventulus profile names ([Setup Checklist § Step 5](setup-checklist.md#step-5--stop-competing-fan-control-software)).
  For Ventulus to drive it, stop the tool: `sudo systemctl disable --now lactd.service`
  for LACT; quit CoreCtrl and remove it from your desktop's autostart.
- **CoolerControl, if you keep it** for something Ventulus cannot drive (lighting, an
  LCD, a USB cooler with no kernel driver): make sure it controls none of the fans
  Ventulus will drive. **On a Gigabyte board, also turn off its Super-I/O detection**
  (Settings → General, or `sensors_auto_detect = false` in
  `/etc/coolercontrol/config.toml`). It runs each time `coolercontrold` starts
  ([CoolerControl docs](https://docs.coolercontrol.org/devices/kernel-modules#built-in-super-i-o-detection)),
  and at a port where no chip identifies itself without one, it writes each chip
  family's config-mode unlock ([source](https://gitlab.com/coolercontrol/coolercontrol/-/blob/main/coolercontrold/cc-detect/src/superio.rs)).
  That is the kind of probe that can hide a Gigabyte board's second fan chip
  ([why, and how to recover](hardware-troubleshooting.md#some-of-my-fan-headers-are-missing--only-5-of-8-show-up)),
  and the Ventulus package's guard cannot stop it, because it writes the ports itself
  rather than loading a module.

### Check that nothing still holds a header

With the old software stopped, list each header's mode:

```bash
find /sys/devices -path '*/hwmon/hwmon*/pwm*_enable' -exec sh -c 'for f; do echo "$(cat "${f%/*}/name") ${f##*/} $(cat "$f")"; done' sh {} +
```

Each line gives a chip, a header and its mode: `2` or higher is the board's own
automatic control, `0` is full speed, and `1` is manual, meaning something set that
header's speed and still holds it. If any line ends in `1`, reboot and run it again:
the BIOS sets every header up afresh as the machine starts. If a `1` comes back after
the reboot, run Step 1's commands again, because something may still start at boot.
If they find nothing, that header starts in manual mode on your board, and nothing
needs doing. A GPU fan you left to a GPU tool (its line names `amdgpu`) can read `1`
too.

Keep this list: Step 4 compares against it. This check matters because the Ventulus
daemon gives each header back exactly as it found it the first time it took it. A
header the old program still holds at that moment would later be given back to that
program's last speed instead of to the BIOS.

## Step 4 — Let Ventulus take over, and check it

1. **The daemon is running:** `systemctl is-active ventulusd` prints `active`, and
   **Overview ▸ Daemon Health** reads *healthy*.
2. **Your fans are all there:** the headers the old program controlled appear under
   **Hardware ▸ Cooling Hardware**, and each chip and its driver in the **Hardware
   Registry** on System State. If some are missing, see
   [Setup Checklist § Step 4](setup-checklist.md#step-4--read-your-result).
3. **Nothing else is running:** Step 1's service commands show nothing running and
   nothing enabled, and `/run/fancontrol.pid` is gone.
4. **A fan test passes:** run **Test Control** on a chassis fan, as in
   [Setup Checklist § Step 6](setup-checklist.md#step-6--verify-control-end-to-end).
5. **A profile runs:** create and apply one, as in
   [Setup Checklist § Step 7](setup-checklist.md#step-7--create-your-first-profile).
6. **Stopping Ventulus leaves the fans safe:**

   ```bash
   sudo systemctl stop ventulusd
   ```

   Run the header check from Step 3 again. Every header should be back in the mode
   that check showed, under the board's own control (the app reads *Disconnected*
   meanwhile). Then start the daemon again, and it picks up the profile you applied:

   ```bash
   sudo systemctl start ventulusd
   ```

   If a header comes back in mode `1` instead, Ventulus first took it while the old
   program still held it, and gave it back that way. Disable that program and
   reboot: the daemon then takes each header as the BIOS set it up. Repeat this stop
   check to confirm.

## Step 5 — Clean up (optional)

Only once Step 4 passes. Nothing here is needed for Ventulus to work.

| Item | Verdict | Why |
|---|---|---|
| The old program's packages: CoolerControl's, fan2go, thinkfan, and on Debian and Ubuntu `fancontrol` | **Safe to remove** | Ventulus uses none of them. On Arch and Fedora `fancontrol` is part of `lm_sensors`, which also gives you `sensors`: keep it if you use that |
| `liquidctl` speed commands in a startup unit or script, for a cooler Ventulus drives | **Safe to remove** | Keep the lighting and screen commands |
| The old program's configuration: `/etc/fancontrol`, `/etc/coolercontrol/`, `/var/lib/coolercontrol/`, `/etc/fan2go/` | **Optional** | Nothing reads it once its program is gone. Keeping it makes going back easier |
| Udev rules and group memberships you added for the old program, such as liquidctl's `71-liquidctl.rules` | **Optional** | Only that program needs them: the Ventulus daemon runs as root |
| The DKMS drivers from Step 2 | **Keep** | Ventulus drives the fans through them. If one came from CoolerControl's package repository, keep that repository too, or the driver stops getting updates |
| Driver options in `/etc/modprobe.d/`, and kernel parameters such as `acpi_enforce_resources=lax`, `amdgpu.ppfeaturemask` or `thinkpad_acpi fan_control=1` | **Keep** | Without them the driver may not bind, or the fan cannot be written |
| Boot-time lists that load your fan chip's driver (`/etc/modules-load.d/`, `/etc/conf.d/lm_sensors`, `/etc/modules`) | **Do not remove until verified** | A line for a driver Ventulus's own list loads too (`nct6775`, `it87`, `w83627ehf`, `drivetemp`) is redundant. Comment it out, reboot, and remove it only if the same fans come back. Any other driver, such as `nct6687`, needs its line |
| BIOS settings you changed for the old program | **Do not change until verified** | Compare them with [Driver Setup § Step 5](driver-setup.md#step-5--bios-settings-the-half-people-skip). Change one at a time, and run **Test Control** again after each |

## Going back

To return to the old program, stop Ventulus, which gives every header back as it
stops, then enable the old program again. You do not need to remove Ventulus:

```bash
sudo systemctl disable --now ventulusd
sudo systemctl enable --now fancontrol.service   # or the service you disabled in Step 3
```

---

Back to [Setup Checklist](setup-checklist.md) | [Table of Contents](README.md)
