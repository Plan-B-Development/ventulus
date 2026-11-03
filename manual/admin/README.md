# Administration

Installing, running, securing, troubleshooting and removing Ventulus. This section
is the one place for that guidance: each topic below has exactly one page that owns
it, and every other page, README and man page links there instead of repeating it.
If two pages ever disagree, the owner is right and the other is a bug to report.

For using the app (profiles, curves, the pages), see the
[User Manual](../README.md).

| Topic | Owner |
|---|---|
| What to install, on which distribution; a machine with no desktop; what the packages set up | [Installing](install.md) |
| Upgrades, what an upgrade does to the running daemon, upgrading from Control-OFC | [Upgrading](upgrade.md) |
| The `ventulusd` service: everyday commands, what start and stop do to your fans, where its settings live, the tray, a service that misbehaves | [The Service](service.md) |
| Who can do what; the open socket; device access; the opt-in features that widen the daemon's access; network use | [Permissions and Security](security.md) |
| What the packages load, the Gigabyte Super-I/O guard, ACPI conflicts, out-of-tree driver notes, `sensors-detect`, other fan software | [Drivers and Other Fan Software](drivers.md) |
| Installing an out-of-tree driver step by step, Secure Boot, BIOS settings, the AMD GPU kernel parameter | [Driver Setup](../driver-setup.md) |
| Switching from fancontrol, CoolerControl, fan2go or another program, and going back | [Migrating from Another Fan Program](../migrating.md) |
| `ventulus-diag`: running the PWM Test Report, characterisation, discovery and recording sessions safely; stopping one; after an interrupted test | [Diagnostic Command](diagnostics-cli.md) |
| What happens when something fails, hand-back, changes that need care, undoing every change | [Safety and Recovery](safety-and-recovery.md) |
| The journal, the support bundle, what to include in a report and where to send it | [Logs and Bug Reports](logs-and-bug-reports.md) |
| A symptom, from the daemon unreachable to fans at full speed | [Hardware Troubleshooting](../hardware-troubleshooting.md) |
| What Ventulus cannot do | [Known Limits](known-limits.md) |
| Removing the app or the daemon, and what each leaves behind | [Uninstalling](uninstall.md) |

Reference material the pages above link into:

- the daemon's [User Guide](https://github.com/Plan-B-Development/ventulusd/blob/main/docs/USER_GUIDE.md):
  every configuration key, the service unit's settings, the safety rules in full,
  and scripting the daemon's API;
- `man ventulusd`, `man ventulus-tray`, `man ventulus-diag` and `man ventulus`:
  options, files, environment and exit status;
- [Hardware Compatibility](../../docs/19_Hardware_Compatibility.md) and the vendor
  guides: chip by chip and board by board;
- the [API contract](https://github.com/Plan-B-Development/ventulus/blob/main/docs/08_API_Integration_Contract.md), for script and client
  authors.

---

Back to the [User Manual](../README.md)
