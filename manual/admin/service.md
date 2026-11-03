# The Service

`ventulusd` is a systemd service that runs as root. It reads every temperature
sensor and, while a profile is active, works out each fan's speed from that
profile once a second and writes it, whether or not the app is open. With no
profile active it writes nothing to a fan, and only its safety rules can act: the
thermal emergency, which runs every fan it can reach at 100 %, among them. It is the
only program that writes fan speeds; the app, the tray and `ventulus-diag` ask it
over a local socket. One runs per machine.

The details of the unit (start and stop timeouts, the watchdog, the restart
back-off, the sleep hook) are in the daemon's
[User Guide § Running the service](https://github.com/Plan-B-Development/ventulusd/blob/main/docs/USER_GUIDE.md#running-the-service),
and every configuration key in its
[§ Configuration](https://github.com/Plan-B-Development/ventulusd/blob/main/docs/USER_GUIDE.md#configuration).

## Everyday commands

```bash
systemctl status ventulusd                     # running, and since when
journalctl -u ventulusd -b                     # this boot's log
sudo systemctl restart ventulusd               # stop, give the fans back, start again
sudo systemctl enable --now ventulusd          # start now and at every boot
curl --unix-socket /run/ventulus/ventulus.sock http://localhost/status   # is it answering?
ventulus-diag status                           # the same, readably, with the thermal state
```

Restart the daemon after loading a motherboard fan driver: it looks for fan headers
only as it starts, so a header whose driver arrived later is not driven until then.

## What starting and stopping do to your fans

- **Start.** The daemon finds the hardware, loads the profile you last applied, and
  starts driving the fans that profile names. Headers no profile names stay with the
  BIOS.
- **Stop** (`systemctl stop` or `restart`, a reboot, an uninstall). Every motherboard
  header and GPU fan curve the daemon took goes back to exactly what it was doing
  before, usually the BIOS's fan control; OpenFAN fans, which have nothing to go back
  to, stay at their last speed or the exit minimum, whichever is higher. This runs
  in the daemon as it exits and again from systemd afterwards.
- **A crash, a kill or a hang.** systemd runs the same hand-back for the headers and
  GPU fans, then restarts the daemon after 3 seconds, backing off to once a minute
  while it keeps failing. It never gives up.

[Safety and Recovery](safety-and-recovery.md#what-happens-when) has the full table,
including suspend and resume, a lost sensor and a device that disappears.

## Where its settings live

| File | What it holds | Who writes it |
|---|---|---|
| `/etc/ventulus/daemon.toml` | Startup configuration: the OpenFAN port, the poll interval, the socket, the exit minimum, the coolant limit, the opt-in features | You. The daemon never rewrites it, and an upgrade keeps your edits |
| `/var/lib/ventulus/runtime.toml` | Settings changed through the app or the API, and your header roles. A value here wins over the same key in `daemon.toml` | The daemon. Do not edit or delete it by hand; back it up with `daemon.toml`, or a restore loses your pump roles |
| `/var/lib/ventulus/` | The saved active profile, the profile store and diagnostic records. Readable by root only | The daemon |
| `/etc/ventulus/profiles/` | Profiles you add by hand | You |
| `/etc/systemd/system/ventulusd.service.d/` | Drop-ins: `sudo systemctl edit ventulusd` writes one | You |

After editing `daemon.toml`, `sudo systemctl reload ventulusd` applies the profile
search directories, the exit minimum and the coolant limit at once; every other key
needs `sudo systemctl restart ventulusd`. The opt-in features that need a drop-in as well as a setting
(the Super-I/O port probe, NVIDIA telemetry, writing OpenFAN firmware) are in
[Permissions and Security § Opt-in features](security.md#opt-in-features).

## The tray icon

The daemon package also installs `ventulus-tray`, a KDE Plasma tray icon that
starts at login where the app is installed. It shows the daemon's state and
switches profiles; it never controls a fan, and closing it changes nothing about
cooling. Turn it off in **System Settings ▸ Autostart**. Details:
[User Guide § The system tray](https://github.com/Plan-B-Development/ventulusd/blob/main/docs/USER_GUIDE.md#the-system-tray)
and `man ventulus-tray`.

## When the service misbehaves

### It does not start

`systemctl status ventulusd` and `journalctl -u ventulusd -b` say why. The usual
causes are a bad edit to `daemon.toml`, which the journal names, and another
`ventulusd` already running, which exits with status 75 and *another ventulusd is
already running*.

### It keeps restarting

The journal shows each failure. `Watchdog timeout` means the control loop stopped
completing its once-a-second tick for 15 seconds; a slow resume from suspend can
cause one. Anything else is a fault worth reporting
([Logs and Bug Reports](logs-and-bug-reports.md)).

### The app cannot reach it

See [Hardware Troubleshooting § The app cannot reach the daemon](../hardware-troubleshooting.md#the-app-cannot-reach-the-daemon).

### The profile does not come back after a reboot

- A `--profile` or `OPENFAN_PROFILE` in a drop-in wins over the profile you applied
  in the app: `systemctl cat ventulusd` shows every drop-in in effect.
- `sudo cat /var/lib/ventulus/daemon_state.json` shows the saved choice.
- The journal says why a profile did not load at startup. If it could not load, the
  daemon starts with none, so the BIOS runs the fans and the thermal emergency still
  acts.

---

Back to [Administration](README.md)
