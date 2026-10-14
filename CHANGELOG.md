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
