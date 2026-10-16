# Changelog

Ventulus was released as Control-OFC (`control-ofc-gui`) up to 4.3.0; this log starts with the
rename. Version numbers carry on from Control-OFC.

## [Unreleased]

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
