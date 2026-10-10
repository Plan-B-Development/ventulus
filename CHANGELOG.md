# Changelog

Ventulus was released as Control-OFC (`control-ofc-gui`) up to 4.3.0; this log starts with the
rename, keeping 4.3.0 as the last release under the old name.

## [Unreleased]

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

## [4.3.0] — 2026-10-09

**Pairs with `control-ofc-daemon` >= v3.0.0**, which the package still requires; control-ofc-daemon 4.3.0 is
the matching release, and memory-module settings follow a renumbered SMBus only with it. Nothing is removed,
and profiles, settings and themes load as before.

### Added

- **Memory temperatures are shown as memory** (DEC-491). DDR5 modules (`spd5118`, kernel 6.11 or later),
  DDR4 modules that carry a sensor (`jc42`, medium confidence: its driver also serves standalone
  thermometers), and the board channels labelled for memory (nct6683 `DIMM n`,
  nct6776–6792 `PCH_DIM0_TEMP`…, nct6793+ `Agent0 Dimm0`…, Dell `SODIMM`) are recognised as memory. The
  Dashboard lists them under a new **Memory** group, and the Overview summary counts them on their own line.
  Each module is named by its bus address, **DIMM 0x51**, **DIMM 0x53**, on every page, picker and alert;
  before, every module showed as `? temp1`. The name does not claim a slot, because the kernel does not
  know which slot an address is in. Demo mode includes a DDR5 pair. Works with any daemon.
- **Memory modules keep their settings when the kernel renumbers the SMBus** (DEC-492). With a daemon
  that names modules by controller, port and address, chart colours, hidden chart lines, the coolant
  override, hidden Overview rows and profile curves saved against the old bus-numbered id follow the
  module on first connect, and the move is noted in the event log. A setting another module could match
  is left alone, including when that module is currently unreadable. Two modules at the same address on
  different SMBus segments are told apart: **DIMM 0x51 (p2)**. A profile with unsaved edits open in
  Controls, or an unpublished draft, is re-keyed but not re-saved, so nothing is published behind your
  back. After downgrading to an older daemon, re-activate the active profile once.

### Changed

- **The curve sensor picker says what a sensor is** instead of the raw wire kind: `Tctl (CPU)`,
  `SYSTIN (board)`, `DIMM 0x51 (memory)`, rather than `(cpu_temp)` / `(mb_temp)`.
- **The default chart never uses a memory module as its motherboard line.** On a machine with only memory
  sensors on the board, that line is left out.

### Fixed

- **A memory module's implausible critical limit no longer shows a permanent "⚠ ALARM".** The daemon reads
  limits once, and an SMBus read can return garbage without an error. A module `crit` at or below 0 °C, or
  below the module's own `max`, is now ignored for the alarm, and the Sensor Detail dialog says so. Every
  other sensor's limit is used as reported.
