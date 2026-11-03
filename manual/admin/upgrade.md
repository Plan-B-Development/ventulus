# Upgrading

Ventulus upgrades with the rest of your system once its repository is set up
([Installing](install.md)):

| Installed from | Upgrade with |
|---|---|
| the pacman repository | `sudo pacman -Syu` |
| the APT repository | `sudo apt update && sudo apt upgrade` |
| the DNF repository | `sudo dnf upgrade` |
| the tarball | Settings ▸ [Updates](../updates.md), or [by hand](#the-tarball) |
| release files | [by hand](#one-off-installs-from-a-release) |

Compatibility between the app and the daemon is checked when the app connects, not
by version number: a feature the running daemon does not offer is greyed out with
the reason, and a daemon too old to run profiles at all gets a banner asking you to
upgrade it. Upgrade both together and neither comes up.

## What an upgrade does to the daemon

An upgrade replaces the daemon's files, but the running daemon carries on until it
is restarted, and each format decides that differently:

| Format | After an upgrade |
|---|---|
| APT (Debian, Ubuntu) | restarts the daemon |
| DNF (Fedora) | restarts the daemon if it was running |
| the tarball's `install.sh` | restarts the daemon if it was running |
| pacman (Arch) | does not restart it, and prints `sudo systemctl restart ventulusd` for you to run |

A restart is an ordinary systemd stop and start. The stop gives every motherboard
header and GPU fan back to what it was doing before the daemon took it, the start
loads your saved profile again, and for the few seconds in between the BIOS runs
the motherboard fans ([Service](service.md)). An edited configuration file is kept;
the new default is written beside it (`.pacnew`, `.rpmnew` or `.new`; apt asks
which to keep).

Restart the app after upgrading it; it does not replace itself while it runs.

## The diagnostic command is its own package

The tests that drive fans on purpose now run from `ventulus-diag`, a separate
package that the app depends on. `pacman -Syu`, `apt upgrade` and
`dnf upgrade` bring it in with the app; there is nothing to do. If you install from
[release files](#one-off-installs-from-a-release), download and install both
`ventulus` and `ventulus-diag`. The app no longer runs the PWM Test Report,
characterisation, control-path discovery or the recording sessions; your saved
reports stay where they were and open with `ventulus-diag report list`
([Diagnostic command](diagnostics-cli.md)).

## Fedora

The repository is built per Fedora release, so after a Fedora upgrade it serves
packages only once a build for the new release is published. Until then dnf skips
it with a warning and leaves Ventulus as it is; everything else upgrades as usual.
An older `ventulus.repo`, one without the line `skip_if_unavailable=True`, stops
every dnf command instead: fetch it again with the command in
[Installing § Fedora](install.md#fedora). dnf reuses the repository's metadata for
up to six hours: if it reports a missing package or a checksum error right after a
new Ventulus release, `sudo dnf upgrade --refresh` fetches it again.

## Debian and Ubuntu

For two or three minutes after a new release is published, `apt update` can report
a checksum mismatch for this repository; run it again a few minutes later
([Installing § Debian 13 and Ubuntu 26.04](install.md#debian-13-and-ubuntu-2604)).

## The tarball

Let Settings ▸ [Updates](../updates.md) download and check the new tarball and give
you the line that installs it, or repeat the steps in
[Installing § The tarball](install.md#the-tarball) with the new release.
`install.sh` upgrades an earlier tarball install in place, keeps a configuration
file you edited (writing the new default beside it as `.new`), and restarts a
running daemon.

## One-off installs from a release

Upgrading means repeating the downloads in
[Installing § One-off install from a release](install.md#one-off-install-from-a-release),
which is the chore the repositories exist to remove. Settings ▸
[Updates](../updates.md) can tell you when a new release is out.

## Upgrading from Control-OFC

Ventulus was called Control-OFC up to version 4.3.0, packaged for Arch only. On
`sudo pacman -Syu` the new packages replace the old ones and carry your setup
across; nothing needs doing by hand.

- **The daemon.** `ventulusd` replaces `control-ofc-daemon`. Configuration you
  edited comes across from `/etc/control-ofc` (`daemon.toml`, profiles, the
  `modules-load.d` file, the Super-I/O guard's off switch and service drop-ins);
  the packaged defaults are kept beside it as `.pacnew`. At its first start the
  daemon imports `/var/lib/control-ofc` once: header roles (so a pump keeps its
  floor), the active profile and the stored profiles. It never overwrites what
  `ventulusd` already has. If the old daemon was running, `ventulusd` is enabled
  and started at the end of the transaction; an old daemon still running is
  stopped first and its fans given back.
- **The app.** `ventulus` replaces `control-ofc-gui`. At its first start it copies
  `~/.config/control-ofc` (settings, profiles, themes) and
  `~/.local/share/control-ofc` (saved PWM Test Reports) to `~/.config/ventulus`
  and `~/.local/share/ventulus`, all or nothing, and points saved folder settings
  at the new places. Reports saved by Control-OFC still open.
- **Old clients.** For the 5.x series `/run/control-ofc/control-ofc.sock` links to
  the new socket, so a 4.x client keeps working, and the daemon refuses to start
  while something else still serves on that old path. A tray you switched off in
  autostart stays off.

The old directories are left in place. Once you are satisfied, remove them:

```bash
sudo rm -rf /etc/control-ofc /var/lib/control-ofc
rm -rf ~/.config/control-ofc ~/.local/share/control-ofc
```

## Switching from another fan program

That is a different job, with its own page:
[Migrating from Another Fan Program](../migrating.md).

---

Back to [Administration](README.md)
