# Uninstalling

Remove the app and the daemon separately; each leaves some files behind on
purpose, listed below. Removing the daemon stops it first, so every fan header it
took is given back.

## Removing the app

The daemon and `ventulus-diag` came in as the app's dependencies, so some package
managers remove them with it. Removing the daemon hands every fan back to the BIOS.

```bash
sudo pacman -R ventulus                  # Arch: the app only
sudo apt remove ventulus                 # Debian, Ubuntu: the app only, until the next apt autoremove
sudo dnf remove ventulus                 # Fedora: also removes ventulusd and ventulus-diag if they came in with the app
sudo /usr/local/lib/ventulus/uninstall   # the tarball: the app and ventulus-diag; ventulusd is separate
```

**To keep the daemon, `ventulus-diag`, or both** (on a machine that is losing its
desktop, say), mark them as wanted before you remove the app:

| Format | Keep them |
|---|---|
| pacman | `sudo pacman -D --asexplicit ventulusd ventulus-diag`. Without it, `pacman -R ventulus` keeps them but leaves them as orphans, which `pacman -Rs` or an orphan clean-up removes |
| APT | `sudo apt-mark manual ventulusd ventulus-diag`. Without it, they stay only until the next `apt autoremove` |
| DNF | `sudo dnf mark user ventulusd ventulus-diag` |
| the tarball | the daemon is a separate install and stays. For `ventulus-diag`, uninstall, then install again with `--cli-only` ([Installing § A machine with no desktop](install.md#a-machine-with-no-desktop)) |

**What stays behind.** Removing a package never touches your home directory:

| Folder | What it holds |
|---|---|
| `~/.config/ventulus/` | Your settings, profiles, themes and settings backups |
| `~/.local/share/ventulus/reports/` | Saved PWM Test Reports |
| `~/.cache/ventulus/` | Theme images, the update check's state, checked firmware copies. Safe to delete at any time |
| `~/.config/control-ofc/`, `~/.local/share/control-ofc/` | Left from Control-OFC, if you upgraded from it ([Upgrading](upgrade.md#upgrading-from-control-ofc)) |

Profiles you applied also live in the daemon, which keeps running them after the
app is gone. To stop fan control too, apply no profile (or **Stop** in the app)
before removing it, or remove the daemon.

```bash
rm -rf ~/.config/ventulus ~/.local/share/ventulus ~/.cache/ventulus
```

## Removing the daemon

```bash
sudo pacman -R ventulusd                 # Arch
sudo apt remove ventulusd                # Debian, Ubuntu
sudo dnf remove ventulusd                # Fedora
sudo /usr/lib/ventulus/uninstall         # the tarball
```

Each one stops and disables the service before it removes anything (the
tarball's uninstaller refuses to remove anything while the daemon is still
running). Stopping the daemon gives every motherboard fan header it took back to
what it was doing before, usually its BIOS fan mode, both in-process as it exits
and again through `ExecStopPost`. OpenFAN channels and headers with no mode
switch are left at their last speed or the exit minimum, whichever is higher
([Service](service.md#what-starting-and-stopping-do-to-your-fans)).

What stays behind:

- `/var/lib/ventulus/`, the daemon's state, on every format: `runtime.toml` (your
  header roles and API-set settings), the saved active profile, the profile store
  and diagnostic records;
- configuration under `/etc` (`/etc/ventulus/daemon.toml`,
  `/etc/ventulus/profiles/quiet.json`, `/etc/modules-load.d/ventulus.conf`, and on
  Debian, Ubuntu, Fedora and the tarball also the tray's autostart entry
  `/etc/xdg/autostart/ventulus-tray.desktop`): pacman keeps an edited file with a
  `.pacsave` suffix, dnf with `.rpmsave`, and the tarball's uninstaller keeps it
  under its own name; `apt remove` keeps every one of them, edited or not, and
  `apt purge ventulusd` deletes them. Any profile you added under
  `/etc/ventulus/profiles/` stays too;
- anything you installed by hand: a udev rule in `/etc/udev/rules.d/`, or a
  drop-in under `/etc/systemd/system/ventulusd.service.d/` (the
  [opt-in features](security.md#opt-in-features) install theirs there).

Remove those by hand if you no longer want them:

```bash
sudo rm -rf /var/lib/ventulus/ /etc/ventulus/
sudo rm -f /etc/udev/rules.d/99-ventulus.rules && sudo udevadm control --reload-rules
sudo rm -rf /etc/systemd/system/ventulusd.service.d/ && sudo systemctl daemon-reload
```

## What else you may have changed

- **Out-of-tree drivers** stay installed, because they are not part of Ventulus and
  other programs use them too: [Driver Setup § Rollback](../driver-setup.md#rollback--undoing-everything).
- **Kernel parameters, module options and BIOS settings:** the
  [undo index](safety-and-recovery.md#undo-index) lists each one.
- **The package repository:** the
  [pacman-repo README](https://github.com/Plan-B-Development/pacman-repo) covers
  removing it from pacman, APT and DNF.

---

Back to [Administration](README.md)
