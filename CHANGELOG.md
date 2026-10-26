# Changelog

Ventulus was released as Control-OFC (`control-ofc-gui`) up to 4.3.0; this log starts with the
rename. Version numbers carry on from Control-OFC.

## [Unreleased]

### Added

- **System State names other fan-control software.** The Interference Monitor lists the
  fancontrol, CoolerControl, fan2go, thinkfan and LACT services that are running or start at
  boot, a `fancontrol` started by hand, and one that was killed without putting its fans back
  (`/run/fancontrol.pid` left over), with a button to the migration guide. It re-reads them
  each time you open the page or press **Refresh**, so you can check that a program you
  stopped is gone. The app reads only systemd's unit states and that PID file, never a fan.
  The support bundle carries the same states under `system.fan_control_software`.
- **You see the support bundle before it is saved, and can copy it instead.** **Export Support
  Bundle** now builds the file in the background and shows it whole; **Save…** writes exactly
  that text, **Copy** puts it on the clipboard, and **Close** writes nothing. Previously the
  app asked where to save first and wrote the file unseen.
- **The support bundle answers a triager's first questions.** It now carries your distribution
  (name and release from `/etc/os-release`), the fan drivers `dkms status` lists and the
  kernels they are built for (other DKMS modules are counted, not named), Secure Boot and the
  kernel's signed-drivers verdict, each motherboard header with its label, writability and
  role, and the daemon's thermal state, emergency causes, pump stalls, cooling advisories,
  readiness summary, unreadable sensors and undriven controls. A control's name is your own
  text, so only its id is included.
- **System State says when a fan's speed cannot be set.** A **Fan speed cannot be set** card
  names a motherboard or OpenFAN fan whose last three writes failed, so it is not at the speed
  Ventulus chose and a thermal emergency cannot raise it; the daemon's journal names the error.
  It clears once a write lands. Until now the failure showed only in the journal. Needs
  ventulusd 5.4.0 or later.
- **System State says when a header was already in manual mode as Ventulus took it.** A
  **Header was already in manual mode** card names each header something else held in manual
  mode when the daemon first took it, usually another fan program. Ventulus gives every header
  back as it found it, so a stop leaves that header in manual mode instead of returning it to
  the BIOS; the card says to stop the other program and reboot. Needs ventulusd 5.4.0 or
  later.
- **The support bundle carries each header's control mode** (`pwm_enable`), and both flags
  above, so you no longer need to add the mode by hand.

### Fixed

- **The in-app Secure Boot advice now says that enrolling a key needs the shim boot loader.**
  The Hardware page's driver steps, the missing-chip warning and the readiness report told
  you to enroll the DKMS key with `mokutil` without saying that the MOK Manager screen comes
  from shim. Debian, Ubuntu and Fedora boot through shim with Secure Boot on; a machine set up
  with `sbctl` alone does not, and a key enrolled in the firmware that way does not count for
  drivers. The missing-chip warning links to the manual's Secure Boot section for that case.

## [5.4.1] — 2026-10-22

Pairs with `ventulusd` >= v3.0.0, which the package requires; ventulusd 5.3.1 is the current daemon
release and drops the false ACPI conflict reports and nct6687/nct6686 RPM thresholds on its side.
The ACPI card is hidden here with any daemon.

### Fixed

- **ASUS boards using `asus_wmi_sensors` are no longer told a BIOS update is the fix for WMI
  fan stops.** The app and docs said a BIOS with WMI method version 2 or later should fix
  fans stopping or sticking. The driver only loads on such a BIOS, so it could not help, and
  the kernel documentation queued for 7.4 now says only that a more recent BIOS "might help".
  The guidance keeps the kernel's soak-test advice.
- **"Device or resource busy" from `modprobe nct6687` is no longer read as an ACPI
  conflict first.** nct6687d builds from 2026-10-18 reserve the same I/O ports as the
  in-kernel `nct6683`, so the usual cause is `nct6683` still holding the chip. The driver
  setup guide now has you check for and unload it before reaching for
  `acpi_enforce_resources=lax`.
- **The *ACPI I/O port conflict* card is gone; it could only ever be a false alarm.** The
  daemon built it from `/proc/ioports`, where the kernel never lists the ACPI regions that
  cause a real conflict, so it missed every real one and could fire on harmless firmware
  ranges, sometimes with it87 advice on an MSI or ASRock Nuvoton board. The System State page,
  the readiness report and the Hardware page's Super-I/O notes no longer show it, even with an
  older daemon (an older daemon's *ACPI claims a Super-I/O chip's I/O ports* readiness item
  still lists until the daemon is updated to 5.3.1; ignore it). To check for a real conflict, run
  `sudo dmesg | grep -i "conflicts with OpRegion"`; the hardware docs and manual now say so.
- Hardware docs: the X670E AORUS MASTER and X870E AORUS MASTER X3D carry SYS_FAN7_PUMP and
  SYS_FAN8_PUMP on an ITE IT5701 controller (seen on Windows; no Linux report yet), and the
  `asus_ec_sensors` board counts now cite kernel 7.3 rather than its release candidates.

## [5.4.0] — 2026-10-19

Pairs with `ventulusd` >= v3.0.0, which the package requires; ventulusd 5.3.0 is the current daemon
release, and the board names, the Board layout panel and the module-signing and expected-chip
warnings below need it. With an older daemon those parts stay hidden.

### Added

- **Gigabyte fan headers and temperatures show their board names.** With a daemon that reads
  the board's firmware layout (ventulusd 5.3.0) on a Gigabyte board running the out-of-tree
  it87 driver, a header the driver leaves as `pwm1` is named from the it87 project's Gigabyte
  configurations: `CPU_FAN`, `SYS_FAN5_PUMP`. Temperatures get names the same way (`VRM MOS`,
  `PCIEX16`). Your own name, the driver's label, `/etc/sensors.d` and
  Ventulus's checked board table still come first. The header's card and its details say the name
  came from the board catalogue and is not verified on your board.
- **A board name that says CPU or pump counts.** It becomes the header's name in a profile, so a
  `CPU_FAN`, `CPU_OPT` or `…_PUMP` header gets the 30 % minimum in a fan role, and the daemon
  protects a `…_PUMP` header as a pump. A role you assign can add to that, never take it away.
  The minimum badge also shows the floor for a header saved under its old `pwmN` name, which the
  daemon now holds at 30 %.
- **Board layout panel on the Hardware page.** It shows the layout code, whether the it87 project
  lists your board model for it, how many channels it named, the catalogue's source, and every name
  with its chip channel. An `EC_TEMP` temperature notes that it reads only with a probe fitted.
- **A catalogue-named supply rail far from nominal says so.** A `+12V`, `+5V` or `+3.3V` rail
  reading more than 10 % off is marked "reading out of range" in the Voltages table. Display only.
- **The missing-chip warning covers more Gigabyte boards.** With ventulusd 5.3.0, a board
  that Ventulus's own list does not include is checked against the chips its firmware layout
  expects. The warning appears once, says when the layout was the source, and the Board layout
  panel shows which expected chips were found.
- **The warning names a kernel that refuses unsigned drivers.** When the daemon reports that
  your kernel loads only signed modules and the out-of-tree it87 is not running, the warning
  and its readiness condition say so, with *Key was rejected by service* / *Operation not
  permitted* and the MOK enrolment. The full report gains a **Module signing** line.

### Changed

- **"Not used by this board" is now "Not mapped for this board"** in the Voltages table: the
  board's layout does not map the input, which does not mean nothing is connected.
- **The kernel's own it87 gets its likely cause.** When the it87 loaded is the kernel's own and
  cannot drive the missing chip, the warning says a kernel update the out-of-tree DKMS build did
  not follow is the usual cause, with `dkms status` and `sudo dkms autoinstall`, instead of the
  power-off ladder. The Hardware page's driver steps add a *Rebuild* block for it.
- **IT8689E advice follows your kernel.** On Linux 7.1 or later the chip reads as supported by
  the kernel's own driver, and the out-of-tree driver as optional (it adds the board layout ID
  that board names need, and the fixes for boards where fan writes have no effect). Debian 13
  and Ubuntu 26.04 keep the out-of-tree advice.
- **The Secure Boot note in the driver steps names both refusals:** *Key was rejected by
  service*, and *Operation not permitted* under lockdown.

## [5.3.1] — 2026-10-17

Pairs with `ventulusd` >= v3.0.0, which the package requires; ventulusd 5.2.0 is the current daemon release.

### Fixed

- **Driver steps on Debian and Ubuntu now cover kernel updates.** The Hardware page's install
  steps and the Driver Setup guide say to install the headers metapackage, to reboot into a kernel
  update that is waiting before building the driver, and that `sudo dkms autoinstall` rebuilds it
  if fans disappear after a new kernel. On a real Ubuntu 26.04 install, the it87 driver was built
  only for the running kernel, and the waiting kernel booted with the in-kernel driver instead.
- **Docs checked on real Debian 13, Ubuntu 26.04 and Fedora 44/45 installs.** The initramfs check
  in Hardware Troubleshooting now runs `lsinitramfs` with `sudo` (Ubuntu's initramfs is readable
  only by root); Driver Setup notes that a file under `/etc/default/grub.d/` can override the
  kernel command line in `/etc/default/grub`; Getting Started explains dnf's "Signing key not
  found" line on a first install.

## [5.3.0] — 2026-10-16

Pairs with `ventulusd` >= v3.0.0, which the package requires; ventulusd 5.2.0 is the current daemon release.
A Ventulus `.rpm` for Fedora 45.

### Added

- **Fedora 45.** Each Release now carries a Ventulus `.rpm` for Fedora 45
  (`ventulus-X-1.fc45.noarch.rpm`, on its Python 3.15) beside the Fedora 44 one, and the DNF
  repository serves both releases. The update check offers each machine the build for its own
  Fedora release.

## [5.2.0] — 2026-10-16

Pairs with `ventulusd` >= v3.0.0, which the package requires; ventulusd 5.2.0 is the current daemon release.
Packages for Debian, Ubuntu and Fedora and a tarball, an opt-in signed update check, and driver guidance for every
supported distribution.

### Added

- **Packages for Debian 13, Ubuntu 26.04 and Fedora 44, and a tarball.** Each Release now carries
  `ventulus_X-1_all.deb`, `ventulus-X-1.fc44.noarch.rpm` and `ventulus-X-noarch.tar.gz` beside the
  Arch package, with a `SHA256SUMS` file and a build attestation for every asset. They run on the
  distribution's own Python, Qt and numpy, and need `ventulusd` 3.0.0 or newer. The tarball
  installs under `/usr/local`, first checks that the system has everything Ventulus needs
  (`./install.sh --deps` prints the command that installs it), and is removed with
  `sudo /usr/local/lib/ventulus/uninstall`.
- **An update check, off unless you ask for it.** Settings ▸ Updates has a "Check for updates" button
  and a switch for a daily check, which is off by default; About shows both versions and the same
  button. Nothing is sent until you check. A check fetches release information signed by the
  repository key and refuses anything it cannot verify. It compares Ventulus and ventulusd
  separately and says how to upgrade each the way it was installed: with pacman, apt or dnf, or, for
  the tarball, a download it checks against the signed SHA-256 before keeping, plus the commands that
  install it. Ventulus never runs a privileged command itself.

### Fixed

- **The install commands work in fish, CachyOS's default shell.** The documented steps used a heredoc,
  a `NAME=value` line and a bracketed `(cd … && makepkg -si)`, all parse errors in fish. They are now
  one set of commands that works as written in bash, zsh and fish, and a test parses every command
  block in the README and the manual in all three.
- **Screen readers say what a drop-down sets on Qt 6.10 and older.** A drop-down with no visible label
  beside it, such as the theme picker or the log source filter, was announced only by its current
  value on Qt before 6.11 (Debian 13, Ubuntu 26.04). It is now announced by what it sets on every
  Qt version.

### Changed

- **The bootstrap install script checks the machine before it changes anything.** It prints the
  distribution, CPU architecture and init system it found, and stops with nothing changed on a
  distribution not built on Arch, on Manjaro, on a CPU other than x86_64, or without systemd.
- **Driver Setup explains how to install `it87-dkms-git` or `nct6687d-dkms-git` without an AUR
  helper**, with `git clone` and `makepkg`, and how to rebuild it later the same way.
- **Driver guidance is right on any distribution.** The out-of-tree drivers are named by their
  upstream projects, `frankcrawford/it87` and `Fred78290/nct6687d`, instead of their Arch packages.
  Where the GUI tells you to install or update one, it gives the steps for the distribution it runs
  on: the AUR package on Arch and its derivatives, upstream's DKMS build on Debian, Ubuntu and Fedora
  (on Fedora, `make akmod` too for nct6687d if RPM Fusion is enabled), and upstream's generic steps
  elsewhere. The Hardware page's **How to enable** section lists those commands with copy buttons,
  and how to sign the driver when Secure Boot is on.
- **The manual covers Debian, Ubuntu and Fedora.** Getting Started has the install steps for each
  supported distribution (the APT and DNF repositories, the tarball, one-off release installs) and
  lists the distributions that are not supported and why. Driver Setup and Hardware Troubleshooting
  give the driver prerequisites, build, update, Secure Boot and removal steps for each, and the
  kernel-parameter step for GRUB on Debian, Ubuntu and Fedora. The hardware reference guides name
  the out-of-tree drivers by their upstream projects. A new [Updates](manual/updates.md) page
  explains the update check: what it sends and to whom, what it trusts, and what it tells you to do
  for each way of installing.
- **pyqtgraph 0.13.7 is enough.** The minimum drops from 0.14 to 0.13.7, the version Debian 13
  ships. The test suite now also runs on the Python, Qt and numpy packages of Debian 13,
  Ubuntu 26.04 and Fedora 44.

## [5.1.0] — 2026-10-15

Pairs with `ventulusd` >= v3.0.0, which the package requires; ventulusd 5.1.0 is the current daemon release.
Board, driver and GPU guidance brought up to date, and Intel Arc temperatures named by their kernel labels.

### Changed

- **Gigabyte Intel Z890 / B860 boards: a failed driver build is diagnosed as one.**
  `it87-dkms-git` builds from 2026-09-09 to 2026-10-01 can fail to load on these boards ("Invalid
  argument" after an "H2RAM set_slot … failed" line) or find a chip and register nothing, a driver
  bug fixed upstream on 2026-10-02. The missing-chip warning, the board notes, the Hardware
  Troubleshooting manual and the Intel guide now say to rebuild the driver first, instead of sending
  you round the bridge-latch recovery. They no longer say MMIO fixes chip detection: it reaches the
  second chip's extra headers, and keeps clear of ACPI conflicts only on the IT8688E, IT8689E,
  IT8696E and IT8698E.
- **ASRock X870E Taichi: both pump headers are named.** The board notes now say the board has two
  pump headers, AIO_PUMP and W_PUMP, and that W_PUMP sits on the channel the `nct6687d` driver calls
  "CPU Fan". A pump there gets the CPU floor but not the pump protections until you give it the
  pump role. This mapping comes from another tool's board map and has not been measured on Linux,
  so Ventulus does not rename the header.
- **Board and driver lists brought up to date (checked 2026-10-15).** The compatibility, AMD and
  Intel guides and the in-app notes add the 2026 Gigabyte AM5 boards and the TRX50 boards, ASRock's
  B850/X870 Riptide, Pro-A and Challenger, B860 and H810 boards from their manuals, and the Z890
  Taichi OCF's different second chip. They correct the "every AM5 Steel Legend has an NCT6686D"
  rule (the B850M Steel Legend WiFi has an NCT6796D-S). They also add the two newer boards in
  `asrock-nct6683`'s list, the X399 boards' need for `ignore_resource_conflict=1`, the it87 driver's
  kernel 6.4 minimum, and the MSI EZ Conn header that `nct6687d` does not expose. Some BIOS advice
  for ASRock NCT6686D boards contradicted the read-only kernel driver; it now applies only to the
  out-of-tree drivers.
- **GPU advice brought up to date (checked 2026-10-15).**
  - AMD: the recommended kernel parameter is now `amdgpu.ppfeaturemask=0xfff7ffff`, the kernel's
    default mask with the OverDrive bit added and the value AMD's engineers give; any mask with
    that bit set still works, so a `0xffffffff` you already use can stay. The guidance also says
    that from Linux 6.13 the kernel logs "Overdrive is enabled" and marks itself tainted when the
    bit is set, which is expected.
  - AMD RX 9000: the GPU fan test's "did not respond" advice and the guides say the firmware can
    keep the fan stopped below about 50 °C hotspot even with zero-RPM idle off, and that some
    RX 9070 XTs read 0 RPM while the fan spins, so test under load first. Fan curves on these
    cards want Linux 6.18.32, 7.0.9, 7.1 or later.
  - AMD RX 5000/6000: the guidance no longer says resume from suspend hands the fan back to the
    card; only a GPU reset does.
  - Intel Arc: B-series temperatures are now recognised by the labels the kernel gives them
    (`pkg`, `vram` and so on), so the package temperature is shown as the package instead of
    "Intel GPU temperature (pkg)". The guides say no mainline kernel can set an Arc fan yet,
    that Intel's patches adding it are still under review, and that on a patched kernel the
    Arc fan must not be added to a profile.
  - NVIDIA: the guides say `nouveau` publishes no sensors on Turing (RTX 20) and newer cards,
    so those are seen only through the opt-in NVML telemetry, and that Maxwell, Pascal and
    Volta owners on Arch need `nvidia-580xx-utils`. The duty and RPM that NVML reports are now
    described as NVIDIA's *intended* fan speed, not a measurement: a blocked fan still shows it.

## [5.0.1] — 2026-10-14

Pairs with `ventulusd` >= v3.0.0, which the package requires; ventulusd 5.0.0 is the current daemon release.
A fix release: no new features.

### Fixed

- **Discarding unsaved profile edits now discards them.** Choosing **Discard** when switching
  profiles only cleared the "Unsaved changes" chip: the edits stayed in memory, came back with no
  chip when you returned to the profile, and **Apply** saved them and ran them on your fans. Discard
  now restores the last saved version, as **Revert** does. **New Profile** and **Duplicate Profile**
  ask first too, and Duplicate copies the saved version. An activation of another profile from
  elsewhere discards the edits and says so. **Apply** on the edited profile clears the chip, since
  it saves them first, even when the daemon then refuses to run it.
- **Rename Profile no longer saves your edits silently.** A rename saves the whole profile, so with
  edits pending it now asks first, then clears the chip and reapplies an active profile like
  **Save**. It used to save them and leave the chip and **Revert** pointing at edits already on
  disk, while an active profile kept running its old curves.
- **A curve's sensor is never changed behind your back.** The curve editor re-read its sensor list
  every second and copied the selected row into the open curve. A curve bound to a sensor the list
  did not show (one the daemon was not reporting, or one not eligible to drive a curve) was quietly
  re-bound to another sensor, and the next save kept it. The selector now shows such a sensor,
  marked "(unavailable)" or "(not offered as a curve source)", and the curve keeps it until you
  choose. The Linear/Trigger dialog behaves the same
  way and no longer offers ineligible sensors. New curves start on the first sensor in the list.
- **Edit Members keeps each member's settings, and Discard undoes it.** Members you kept lost a GPU
  fan's **Allow zero-RPM idle** setting, and a member change stayed even if you then chose
  **Discard** in the fan role dialog. The dialog now also shows the edited member list.
- A Sync curve can no longer be saved without a fan role to mirror, which the daemon refuses.
- Demo mode: a card's **Manual** pin no longer keeps driving the simulated fans after the card is
  rebuilt by a save or a profile change.
- **Starting with no daemon no longer shows "Thermal OK".** The footer showed a green thermal chip
  built from no data, and the "Daemon disconnected — retrying..." banner never appeared, for as
  long as the daemon stayed down. The thermal chips now stay hidden until a poll succeeds, and the
  banner appears as soon as one fails.
- **Disconnects no longer leave stale health on screen.** The Overview's **Daemon Health** card
  kept its green status, uptime and override countdown, and the top ribbon kept the daemon's last
  uptime. Both now go blank, and the card reads **disconnected**.
- **The System Health full report shows the live thermal state.** It read the state fetched when
  the page loaded, so it could say "thermal safety normal" beside a Safety card showing an
  emergency or a disconnect.
- **Settings re-reads the daemon's configuration.** It was read once per session, so the
  "restart required" note stayed after you restarted the daemon, and one failed read after a change
  disabled the card until the app restarted. It is now read on each visit and when the daemon
  restarts or reconnects. **Exit minimum** and **Coolant limit** no longer stay greyed out as
  "daemon too old" when Settings opened before the daemon's capabilities arrived.
- **System State's "Test fan control" now waits its turn and shows what it is doing.** The button
  under **Board notes** could start a test of every writable header in the middle of a PWM Test
  Report, or on top of a test already running, and everything it reported went to the collapsed
  **Advanced actions** section, so a click seemed to do nothing. It is now unavailable while another
  test or a report runs, like **Verify All Writable**, and shows its progress and result below it.
- **A test's window shows a test that is still running.** Closing **Calibrate OpenFan Channel** with
  **Keep running** and reopening it showed "Ready to start." with no way to cancel the walk or see its
  result. **Characterise** and **Discover Control Path** behaved the same, and closed mid-run without
  asking. All three now show a running test (with **Cancel run**) or the most recent result when
  they open, and wait, naming the header, while another header's test of the same kind runs.
  Characterise and Discover ask before closing mid-run, and a stop chosen on closing that fails is
  reported instead of lost.
- **Restore GPU Fan to Automatic** no longer becomes clickable again while a restore is running.
- **A cooling-device card's Characterise Pump and Start Validation** are disabled, with the reason,
  when the pump's header is missing or read-only, when the daemon has no validation sessions, and
  while a header test runs. Before, they opened nothing or a window whose **Start** could only be
  refused.
- **Unapplied theme edits no longer leak into the app.** After **Apply Theme Globally**, every
  later edit in the theme editor also changed the theme the app had applied, so the chart and other
  views painted colours you had not applied beside ones you had. The app now gets its own copy.
- **The Theme page follows changes made in Settings.** A moved themes folder left the picker on the
  old paths (and **Load** failed with no message), themes brought in by **Import Config** did not
  appear, and an imported card size was written back over on the next **Apply**. The page now
  re-reads these each time you open it, and a theme file that has gone is reported, not loaded.
- **Theme Export includes your font and base size**, as Save and Apply already did.
- **Importing a theme asks before replacing one.** The Theme page's **Import…** and the themes in
  **Import Config** replaced a theme file of the same name without a word; they now ask, as
  profile import does.
- **Reset colours reaches the chart.** **Reset colours** and **Remove** (settings for missing
  hardware) changed only the saved setting, so the Dashboard chart and the Sensors panel kept the
  old colours until restart. The memory-module id migration had the same gap. All three now
  repaint at once.
- **Chart series keep their colour across launches.** A series' default colour was picked by a
  hash that changes every time the app starts, so CPU could be blue today and orange tomorrow.
  This release moves each series to a fixed colour once; colours you picked are unchanged.
- The Sensors panel's colour swatches now follow a theme switch, as the chart lines already did.
- **Fan Wizard: Finish keeps what you typed on the Review page.** Labels edited in the review table
  were thrown away, because they were saved before the table was read back. Finish also no longer
  saves a label for a fan you deselected after labelling it.
- **Fan Wizard: "Fan restored" only when the daemon confirmed it.** A restore the daemon refused
  was still reported as done. The wizard now says the restore was not confirmed, and that the daemon
  restores the fan by itself when the test's hold expires.
- **Fan Wizard: the intro page keeps up.** Its status and **Next** button were set once, so a daemon
  that connected after the wizard opened left **Next** disabled, and one that dropped left it
  reading "Ready". Both now follow the connection. A hot CPU now shows as a warning instead of
  "Cannot proceed", since **Next** stays available and each fan test checks the temperature itself.
- Fan Wizard: **Skip** comes back when you return to the Identify step after the last fan, and
  status colours now change with the message (a refusal no longer stays red on the next success).
- **PWM Test Report: a failed save is not hidden.** The "could not be saved" message was replaced by
  the next status line straight away, and the finished report could say "Saved to" a file from an
  earlier run, or an earlier checkpoint of this one. The run status now keeps the error until a save
  succeeds, and the report says it was not saved (and where an earlier copy is, if there is one).
- **The Sensor detail dialog stays current.** Its value, age, freshness, trend, session range and
  headroom to critical showed the reading from when the dialog opened. They now sit in a strip at
  the top that updates every second and says when the daemon stops reporting the sensor; the
  report below it no longer re-renders, so scrolling and selected text are left alone.
- Dialogs and right-click menus no longer pile up in memory. Every one-shot dialog (About, the
  Alert Centre, the Fan Wizard, role pickers, colour pickers, message boxes and the Hardware page's
  run dialogs) and every right-click menu was kept, hidden, until Ventulus quit. A kept Alert
  Centre also kept rebuilding itself on every alert change.
- **Against a daemon too old to control (before 2.0), Apply and Stop are off.** The "Daemon upgrade
  required" banner said the GUI had stood down, but the sidebar and Dashboard **Apply** and **Stop**
  still sent the request, as did saving the running profile (which re-applies it) and the PWM Test
  Report's **Re-apply profile**. They are now greyed or refused with the reason, and the banner names the daemon
  version now running instead of the first one seen, as does the "GUI is older" banner its floor.
- **A dialog no longer applies its changes to a profile you have left.** If another profile was
  activated (from the Dashboard, the tray or another client) while a fan role, curve, rename,
  Configure AIO or Dedicate GPU dialog was open, its changes went into the profile no longer on
  screen, unseen until a later **Apply** ran them. They are now dropped, and the status chip says so.
- **Removing a pump role you assigned no longer warns about protection the header keeps.** A header
  whose own label (`PUMP`, `AIO_PUMP`…) or cooler channel tells the daemon it drives a pump stays
  protected whatever its role, so the "Remove pump protection?" question is not asked for it.
- **Export Support Bundle no longer freezes the window, and says how it went.** It ran `lsmod` and
  two `journalctl` reads on the GUI thread, then said nothing unless it failed, and a failure only
  reached the Logs feed. It now runs in the background and a banner says where the file went (unless
  a warning such as a disconnect is already showing), or why it was not written.
- A refused **Apply**'s reason comes back after the daemon reconnects, instead of being replaced
  by "Connected to daemon"; a reason you dismissed, or one overtaken by a profile change since,
  stays down.
- Demo mode: the status banner and Dashboard name the profile demo runs instead of "No profile".
- Logs: **Clear Logs** also clears the time-filter label; a **Follow** paused by scrolling now
  reads as off, so one click resumes it; **Open Hardware** opens the Hardware page, not System
  State.
- Dashboard: a hwmon or OpenFAN fault the daemon no longer reports leaves its chip on the next poll
  rather than up to five minutes later, and **Dismiss** on the hwmon and API-version banners lasts
  until their message changes.
- Overview: the "N hidden sensors" row expands on a single click, or **Enter**, as it says.
- Settings in demo mode: **Reset colours**, **Reset all sizes** and chart-series **Run again** say
  they were not saved, since demo keeps those settings for the session only.
- Controls: a curve card's "Used by" and a role card's curve name follow role and curve edits
  straight away; renaming a curve no longer releases **Manual** overrides you are holding; the
  curve editor's floor follows role changes made while it is open.
- Hardware: the OpenFAN channel outcome line goes away once that channel's role changes elsewhere.
- Accessibility: the Dashboard chart is no longer an unnamed Tab stop, and each Sensors panel row's
  menu (right-click, <kbd>Menu</kbd> or <kbd>Shift</kbd>+<kbd>F10</kbd>) offers **Change colour…**,
  so a series colour can be set without the mouse. The panel no longer re-applies every series'
  visibility on each poll.

## [5.0.0] — 2026-10-10

Pairs with `ventulusd` >= v3.0.0, which the package requires; ventulusd 5.0.0 is the matching release.
The first release under the new name. No change to fan control, profiles or settings.

### Changed

- **Control-OFC is now Ventulus.** The package and command are `ventulus` (was `control-ofc-gui`), the
  Python package is `ventulus`, the desktop entry and icon are `ventulus`, settings live in
  `~/.config/ventulus/` and the cache in `~/.cache/ventulus/`. The GUI talks to `ventulusd` on
  `/run/ventulus/ventulus.sock` and checks `ventulusd.service`. Nothing about fan control changes.
- **Upgrading from Control-OFC carries your files across** (DEC-493). `ventulus` replaces `control-ofc-gui`
  on `pacman -Syu`. At its first start the GUI copies `~/.config/control-ofc` (settings, profiles,
  themes) and `~/.local/share/control-ofc` (saved PWM Test Reports) to their new folders, all or
  nothing, pointing saved folder settings at the new locations; the old folders are left in place.
  Reports saved by Control-OFC still open.
