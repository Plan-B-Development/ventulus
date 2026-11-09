# Logs and Bug Reports

Where Ventulus records what happened, what to collect when something goes wrong,
and where to report it.

## The daemon's journal

The daemon logs to the systemd journal. The app shows the same under **Logs ▸
System Journal**.

```bash
journalctl -u ventulusd -b                          # this boot
journalctl -u ventulusd -f                          # follow it live
journalctl -u ventulusd -b | grep 'hardware diagnostic'   # every test started, and the daemon's answer
journalctl -b -t ventulus-superio-guard             # each driver the Gigabyte guard declined
journalctl -b -u systemd-modules-load               # the same at boot where SELinux blocks it (Fedora)
journalctl -k -b | grep -iE 'it87|nct6|w836'        # the fan drivers' kernel messages
```

**Every request that starts a test which changes fan speeds** (a PWM verify,
characterisation, control-path discovery, the stall probe, OpenFAN calibration, a
GPU fan test, a validation session, or a Super-I/O port probe) is logged when it
arrives, with the user id and process id of the program that sent it, and again
with the daemon's answer. That is how a fan that changed speed during a test is told
apart from the profile's own control, whether the test came from the app, from
`ventulus-diag` or from a script. The ids name the caller; they grant nothing.

The daemon's own state is also readable without the app:
`ventulus-diag status`, or
`curl --unix-socket /run/ventulus/ventulus.sock http://localhost/diagnostics/hardware`.
The daemon's
[User Guide § Troubleshooting](https://github.com/Plan-B-Development/ventulusd/blob/main/docs/USER_GUIDE.md#troubleshooting)
explains each condition it reports there.

## The app's own log

The **Logs** page lists what the app did this session (connections, profile changes,
alerts) and keeps it in memory only: it is gone when the app closes, apart from what
the support bundle saved ([System Health § Logs page](../diagnostics.md#logs-page)).

## The support bundle

On a machine with the app, start with the support bundle: the **Export Support Bundle** button in the footer
shows you one file, then saves or copies it. It holds the app and daemon versions, your
distribution, your kernel and its fan-driver boot parameters, the loaded kernel modules,
the fan drivers DKMS built, Secure Boot and whether the kernel loads only signed
drivers, your board, fan chips and headers, the fan-control services installed and
whether each runs, the daemon's thermal and readiness state, each fan's speed and duty,
each header's control mode, the app's event log and the last 100 lines of the
daemon's journal.
[System Health § Export Support Bundle](../diagnostics.md#export-support-bundle) lists
everything in it.

The bundle does not include the following. Add what applies to your problem
([what else to include](#what-to-include)):

```bash
sudo dmesg | grep -iE 'it87|nct6|w836|f718'       # the fan drivers' kernel messages
```

- other fan programs the bundle does not know (CoreCtrl, your own units and
  scripts), from the commands under
  [Migrating § Step 1](../migrating.md#step-1--take-stock);
- what you did, what you expected, and what happened instead.

Read the bundle and anything you add before you share it. The bundle names your
hardware and may name your folders. The full kernel command line, if you add it,
names your disks (`root=UUID=…`); the bundle leaves that part out.

On a machine with no desktop there is no bundle. Collect `journalctl -u ventulusd -b`,
`ventulus-diag status`, `ventulus-diag headers`, the
`/diagnostics/hardware` reply above, `uname -r`, your distribution and the package
versions (`ventulusd --version`).

## What to include

- What you did, what you expected, and what happened instead.
- The support bundle, or the commands above on a machine without the app.
- For a fan that behaves oddly, a PWM Test Report:
  `ventulus-diag report run`, then
  `ventulus-diag report export REPORT --format markdown -o report.md`
  ([Diagnostic Command](diagnostics-cli.md)).
- Whether it started after an upgrade, a kernel update or a BIOS change.

## Where to report

| The fault is in | Report it to |
|---|---|
| The app or `ventulus-diag`: a page, a setting, a wrong message, the support bundle | [Ventulus issues](https://github.com/Plan-B-Development/ventulus/issues) |
| The daemon: fan control, a safety rule, a crash, the service, the tray, the packages' install and removal | [ventulusd issues](https://github.com/Plan-B-Development/ventulusd/issues) |
| An out-of-tree fan driver | its own project: [`frankcrawford/it87`](https://github.com/frankcrawford/it87/issues) or [`nct6687d`](https://github.com/Fred78290/nct6687d/issues) |
| A security vulnerability | privately, as each project's security policy says: [app](https://github.com/Plan-B-Development/ventulus/blob/main/SECURITY.md), [daemon](https://github.com/Plan-B-Development/ventulusd/blob/main/SECURITY.md). Not on the issue tracker |

---

Back to [Administration](README.md)
