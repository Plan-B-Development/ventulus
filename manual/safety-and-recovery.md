# Safety and Recovery

Ventulus changes how your fans and pump run, so a mistake or a fault can affect how
your machine is cooled. This page collects four things: what Ventulus does when
something goes wrong, the risk behind each change that needs care, how to undo every
change the manual describes, and how to ask for help. The daemon's safety rules are
explained once, in
[Understanding Motherboard Fan Control § What keeps your machine safe](understanding-fan-control.md#what-keeps-your-machine-safe);
this page links to them rather than repeating them. Read the notice on the
[contents page](README.md) too: these rules reduce risk, and nothing removes it.

## What happens when…

| When | What happens to your fans | What you do |
|---|---|---|
| **You close the app, or it crashes** | Nothing changes. The daemon keeps running the active profile and every safety rule. A **Manual** override lapses within 15 seconds, because the app no longer renews it, and that fan role goes back to its curve | Nothing |
| **You press Stop** | On its next tick the daemon gives back every motherboard header and GPU fan the profile drove: each header to exactly what it was doing before the daemon first took it, usually the BIOS's fan control. OpenFAN fans stay at their last speed or the **Exit minimum** (Settings), whichever is higher. The thermal emergency still acts with no profile running | Press **Apply** to start a profile again |
| **The daemon stops normally** (`systemctl stop`, a restart, shutdown, uninstall) | The same hand-back, done twice: by the daemon as it exits and again by systemd afterwards. Every GPU fan curve it wrote goes back to the card's own curve. OpenFAN fans and headers with no automatic mode stay at their last speed or the exit minimum (50 % unless you change it), whichever is higher, and a fan whose last speed the daemon lost track of is left at 100 %. A header whose mode cannot be restored is set to full speed | Nothing |
| **The daemon crashes or is killed** | systemd runs the hand-back for every motherboard header and GPU fan the daemon's records name. It cannot reach an OpenFAN controller, so those fans keep their last speed until the daemon is back. systemd restarts the daemon after 3 seconds, slowing to once a minute while it keeps failing, and the daemon loads your saved profile again | If it keeps restarting, `journalctl -u ventulusd -b` says why |
| **The daemon hangs** | If its control loop misses its once-a-second tick for 15 seconds, systemd stops it the normal way, kills it if that has not finished 10 seconds later, runs the hand-back and restarts it. A slow or stuck device does not trigger this: the loop keeps ticking past a write that has not returned | The journal shows `Watchdog timeout` |
| **You reboot or shut down** | The daemon stops normally (above), and the BIOS sets every header up again as the machine starts. Until the daemon has started and loaded your saved profile, the BIOS runs the fans | If the profile does not come back, see the daemon's [User Guide](https://github.com/Plan-B-Development/ventulusd/blob/main/docs/USER_GUIDE.md#the-profile-does-not-come-back-after-a-reboot) |
| **The machine suspends and resumes** | The package's sleep hook stretches the daemon's hang check for the sleep. After the resume the daemon sets each header it drives back to manual mode on its next write, and writes each OpenFAN fan's speed again, because the controller restarts its fans at about 1000 rpm when its 12 V supply went off | Nothing. A slow resume can restart the daemon; the journal says so |
| **The CPU or coolant temperature reaches its limit** | The thermal emergency: every OpenFAN fan and writable motherboard header runs at 100 % until a current reading is back below the release point. GPU fans are left to the card, which protects itself | Find out why: [Fans run at full speed](hardware-troubleshooting.md#fans-run-at-full-speed-regardless-of-profile) |
| **A pump stops turning** | A pump in the active profile that the daemon has seen spinning, and that then reads 0 RPM for 10 seconds, is driven to 100 % for 30 seconds. If it still does not turn, it stays at 100 % | Check the pump and its cable |
| **The CPU temperature sensor stops reporting** | After 5 seconds with no current CPU reading, the fans in your profile are held at 40 % or more; fans no profile controls stay on their own firmware curve. During an emergency, a lost sensor keeps the 100 % ([the full rule](understanding-fan-control.md#what-keeps-your-machine-safe)) | [Sensors missing or fewer than expected](hardware-troubleshooting.md#sensors-missing-or-fewer-than-expected) |
| **Another sensor a curve uses stops updating** | That curve stops, and its fans hold their current speed. They are never lowered because a reading froze. The fan role's card shows *Not controlled* | Check the sensor, or pick another for the curve |
| **A device disappears** (an OpenFAN controller unplugged, a driver unloaded) | The daemon can no longer reach it, so its fans keep whatever the device was last told. A fan role none of whose fans can be reached shows *Not controlled*. When an OpenFAN controller comes back, the daemon writes each fan's speed again; a motherboard chip whose driver comes back needs a daemon restart before its headers return | Reconnect or reload it, then `sudo systemctl restart ventulusd` for a motherboard chip |
| **A profile is invalid** | The daemon refuses to start it, and the profile that was running keeps running; the app shows why. A profile naming a sensor this machine does not have still starts: that fan role is skipped and its fans hold their speed. If the saved profile cannot load at boot, the daemon starts with none, so the BIOS runs the fans and the thermal emergency still acts | Fix the profile and press **Apply** again. The journal says why a profile did not load at boot |
| **A write to a fan fails** | The fan keeps the speed it had, and a thermal emergency cannot raise it either. After three failed writes in a row the **System State** page shows **Fan speed cannot be set**, naming the fan, and the daemon's journal names the error (`hwmon write failed for …`). The card clears once a write lands. A write that succeeds but does not hold is reported instead, as **Fan duty is not holding** | Look in the **Logs** page's **Journal** tab: [A fan's speed shows, but the fan cannot be controlled](hardware-troubleshooting.md#a-fans-speed-shows-but-the-fan-cannot-be-controlled) |

None of this can promise that the hardware obeyed. Each hand-back step gives up after
a few seconds so that the daemon can always exit, and a chip or card that has
stopped accepting writes cannot be given back at all: its fans hold their last speed
until something takes them over. A reboot sets the motherboard's headers up again.

## Changes that need care

Each of these can reduce cooling. Here is the actual risk, what Ventulus does about
it, and what is left to you.

- **Running a fan slowly.** A fan cools more than the sensor its curve reads: the
  chipset, the voltage regulators, drives, a radiator. The app does not let a profile
  take a chassis or OpenFAN fan below 20 %, or a CPU fan or pump below 30 % (70 % for
  a pump on a header in DC mode); a GPU fan may idle at 0 %, because the card protects
  itself. After changing a curve, watch your temperatures under a real load.
- **A pump Ventulus does not know about.** Pump protection (never stopped, the 30 %
  or 70 % floor, the stall response, an Identify that changes its speed instead of
  stopping it) applies only to a header Ventulus knows is a pump: one whose name says
  so, one you gave the pump role, or one you chose in **Configure AIO**. A pump on a
  header with a generic name and no role is treated like a chassis fan, and the 20 %
  minimum can stall it. Give it the role: **Set role… ▸ Pump** on the **Hardware**
  page.
- **Taking a header from the BIOS.** A profile or a fan test switches a header to
  manual mode, and from then on the BIOS's own fan curve no longer runs it. The
  daemon's rules take over, and every stop gives the header back as the daemon found
  it. If another program still held it in manual mode at that moment, it goes back to
  manual mode, not to the BIOS, and the **System State** page shows **Header was
  already in manual mode**. A header your
  profile does not control stays with the BIOS, whose curve reads its own sensor; the
  daemon's 40 % missing-sensor floor does not reach it.
- **Fan tests, Identify and Discover Control Path.** Each changes a header's speed
  while it runs, never takes a pump below its floor, and gives the header back
  afterwards ([Fan Tests § What the daemon guarantees during a test](fan-tests.md#what-the-daemon-guarantees-during-a-test)).
  Run them with the machine idle, and on a chassis fan before a CPU fan or pump.
- **Installing or loading a driver.** The wrong driver can misread a chip, and on some
  Gigabyte boards loading `nct6775` or `w83627ehf` hides a second fan chip until the
  power is cut. An out-of-tree driver is maintained outside the kernel and has to be
  rebuilt for every kernel. Install only the driver the **Hardware** page names
  ([Driver Setup](driver-setup.md)).
- **Kernel parameters.** A wrong kernel command line can stop the machine booting;
  you can remove a parameter for one boot at the boot menu (press `e` on the entry in
  GRUB or systemd-boot). `amdgpu.ppfeaturemask` marks the kernel *tainted* from Linux
  6.13. `acpi_enforce_resources=lax` lets drivers use I/O ports and memory that the
  firmware's own ACPI code may also use
  ([kernel parameters](https://docs.kernel.org/admin-guide/kernel-parameters.html)),
  so use it only for a conflict your kernel log names, and only where the driver has
  no option of its own.

### What this manual does not recommend

Some fixes circulate in forums that this manual leaves out on purpose:

- **Writing to Super-I/O or embedded-controller registers by hand** (`isaset`, or the
  `ec_sys` module with `write_support=1`). Nothing records what was there, so there is
  no undo, and a wrong register can switch off a fan or a protection.
- **Forcing a driver onto a chip it does not recognise** (`force_id` for `it87`,
  `force=1` for `nct6687` on an unlisted chip). Upstream reserves `force_id` for
  testing, and a chip-ID collision under `force=1` has bricked a CPU fan header.
- **Copying module options from another board's guide.** Options describe one board's
  wiring; on yours they can make the driver read the wrong registers. Use the table in
  [Driver Setup § Module parameters](driver-setup.md#module-parameters-you-may-actually-need),
  which says which board each option is for.
- **Running `sensors-detect` on a Gigabyte board.** See
  [About `sensors-detect`](hardware-troubleshooting.md#about-sensors-detect).
- **Turning off a BIOS protection to silence a warning,** such as the CPU fan failure
  warning or a thermal shutdown temperature. Those still work when Ventulus, the
  driver or the machine does not.

## Undo index

Every change the manual describes, and where to take it back:

| What you changed | How to undo it |
|---|---|
| **Installed Ventulus** | Remove the packages; stopping the daemon gives every header back. Some files stay behind on purpose: the daemon's [User Guide § Uninstall](https://github.com/Plan-B-Development/ventulusd/blob/main/docs/USER_GUIDE.md#uninstall) lists them and how to remove them |
| **Started a profile** | **Stop** in the sidebar ([Controls](controls.md#managing-profiles)) |
| **Gave a header a role** | **Set role… ▸ Not set** on its card on the **Hardware** page; a role the hardware gives cannot be removed |
| **Changed the exit minimum, coolant limit or another daemon setting from the app** | [Settings § Daemon Configuration](settings.md#daemon-configuration) |
| **Changed the app's own settings or profiles** | [Settings § Sync & Backup](settings.md#sync--backup) restores an export or the automatic backup |
| **Edited `/etc/ventulus/daemon.toml` or added a systemd drop-in** | Undo the edit, then `sudo systemctl restart ventulusd`; the daemon's [User Guide § Configuration](https://github.com/Plan-B-Development/ventulusd/blob/main/docs/USER_GUIDE.md#configuration) |
| **Installed an out-of-tree driver** (and its option, blacklist and load files) | [Driver Setup § Rollback](driver-setup.md#rollback--undoing-everything) |
| **Set a module option** | Remove the line or the file under `/etc/modprobe.d/`, then reboot ([Driver Setup § Module parameters](driver-setup.md#module-parameters-you-may-actually-need)) |
| **Enrolled the DKMS signing key** | `sudo mokutil --delete /var/lib/dkms/mok.pub`, reboot, and confirm in MOK Manager ([Driver Setup § Secure Boot](driver-setup.md#secure-boot-and-dkms-modules)) |
| **Added a kernel parameter** (`amdgpu.ppfeaturemask`, `acpi_enforce_resources=lax`) | Remove it from the file you added it to, run your bootloader's update command if it has one, and reboot ([Driver Setup § AMD GPU](driver-setup.md#amd-gpu-fan-control-prerequisite-rdna3)) |
| **Turned off the package's Gigabyte guard** (an empty `/etc/modprobe.d/ventulus-superio.conf`) | Delete that file and reboot ([Sensors missing or fewer than expected](hardware-troubleshooting.md#sensors-missing-or-fewer-than-expected)) |
| **Blocked `nct6775` and `w83627ehf` yourself** (`/etc/modprobe.d/ventulus-superio-local.conf`) | Keep it unless the guard covers your board ([Driver Setup § Rollback](driver-setup.md#rollback--undoing-everything) says how to check) |
| **Edited `/etc/modules-load.d/ventulus.conf`** | Restore the line you commented out, then `sudo systemctl restart systemd-modules-load` or reboot. The file's own comments explain the rest |
| **Ran `sensors-detect` and let it save a module list** | Remove the modules you do not want from `/etc/conf.d/lm_sensors` (Arch), `/etc/modules` (Debian, Ubuntu) or `/etc/sysconfig/lm_sensors` (Fedora) |
| **Stopped another fan program** | [Migrating § Going back](migrating.md#going-back) |
| **Changed BIOS fan settings** | In BIOS setup, set Smart Fan, Q-Fan or your board's equivalent back to its default profile ([Driver Setup § BIOS settings](driver-setup.md#step-5--bios-settings-the-half-people-skip)) |

## Getting help

Start with the support bundle: the **Export Support Bundle** button in the footer
shows you one file, then saves or copies it. It holds the app and daemon versions, your
distribution, your kernel and its fan-driver boot parameters, the loaded kernel modules,
the fan drivers DKMS built, Secure Boot and whether the kernel loads only signed
drivers, your board, fan chips and headers, the fan-control services installed and
whether each runs, the daemon's thermal and readiness state, each fan's speed and duty,
each header's control mode, the app's event log and the last 100 lines of the
daemon's journal.
[System Health § Export Support Bundle](diagnostics.md#export-support-bundle) lists
everything in it.

The bundle does not include the following. Add what applies to your problem:

```bash
sudo dmesg | grep -iE 'it87|nct6|w836|f718'       # the fan drivers' kernel messages
```

- other fan programs the bundle does not know (CoreCtrl, your own units and
  scripts), from the commands under
  [Migrating § Step 1](migrating.md#step-1--take-stock);
- what you did, what you expected, and what happened instead.

Read the bundle and anything you add before you share it. The bundle names your
hardware and may name your folders. The full kernel command line, if you add it,
names your disks (`root=UUID=…`); the bundle leaves that part out.

Report Ventulus faults on the project's
[issue tracker](https://github.com/Plan-B-Development/ventulus/issues). A driver fault
belongs with that driver's project: [`frankcrawford/it87`](https://github.com/frankcrawford/it87/issues)
or [`nct6687d`](https://github.com/Fred78290/nct6687d/issues).

---

Previous: [Hardware Troubleshooting](hardware-troubleshooting.md) | Next: [Driver Setup](driver-setup.md) | Back to [Table of Contents](README.md)
