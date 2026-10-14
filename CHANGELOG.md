# Changelog

Ventulus was released as Control-OFC (`control-ofc-gui`) up to 4.3.0; this log starts with the
rename. Version numbers carry on from Control-OFC.

## [Unreleased]

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
