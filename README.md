# Ventulus

*Formerly Control-OFC (`control-ofc-gui`).*

**Latest release:** v5.4.0 — 2026-10-19. Pairs with `ventulusd` ≥ v3.0.0; version numbers carry on from Control-OFC. Individual features gate on newer daemons and say so in the app when one is missing.

Ventulus is a fan control app for Linux desktops. You decide how each group of fans
should respond to temperature; a background service, [`ventulusd`](https://github.com/Plan-B-Development/ventulusd),
runs those curves and keeps the machine safe whether or not the app is open. This
repository is the desktop app, `ventulus`.

![Dashboard](https://raw.githubusercontent.com/Plan-B-Development/ventulus/main/screenshots/auto/01_dashboard.png)

## What it does

- **Fan curves and profiles.** Seven curve types, from a simple ramp to a mix of
  several sensors or one group of fans following another, grouped into profiles
  you switch between: a quiet one for the evening, a louder one for games.
- **One place for every fan.** An OpenFAN controller, the fan headers on your
  motherboard, and the fan on an AMD RX 7000 or RX 9000 card. NVIDIA and Intel Arc
  fans are shown but cannot be driven.
- **Liquid coolers.** **Configure AIO** sets up a pump and its radiator fans in
  one step, and makes sure the pump is never stopped or run below its safe speed.
- **Finds out what your hardware needs.** The **System State** and **Hardware**
  pages name your board's fan chips, the driver each one needs, and whether fan
  control actually works.
- **Tests your fans.** Fan identification, per-header control tests, and a
  **PWM Test Report** that measures how every fan responds.
- **Demo mode** (`ventulus --demo`) shows the whole app with simulated hardware.

## Supported hardware

| Hardware | Support |
|---|---|
| OpenFAN controller (USB) | Full control |
| Motherboard fan headers | Full control on most boards; newer Gigabyte, MSI and some ASRock boards need a driver installed first |
| AMD GPU fans, RX 7000 / RX 9000 | Full control after a one-time kernel setting |
| AMD GPU fans, RX 6000 and older | Monitored; the fan can be tested and reset |
| Liquid coolers with a Linux driver (NZXT Kraken, Aquacomputer) | Pump and fans where the driver allows it, plus coolant temperature |
| NVIDIA and Intel Arc GPU fans | Monitor only |

[Getting Started](manual/getting-started.md#supported-coolers-and-controllers) lists
coolers model by model, and the [Hardware Compatibility](docs/19_Hardware_Compatibility.md)
guide covers chips and boards.

## Install

Ventulus is packaged for x86_64 Linux in signed repositories. Add the one for
your distribution once, and both packages then upgrade with the rest of your
system. The commands work as written in bash, zsh and fish.

| Distribution | Upgrades with |
| --- | --- |
| Arch Linux, CachyOS, EndeavourOS, Garuda | `sudo pacman -Syu` |
| Debian 13, Ubuntu 26.04 LTS | `sudo apt update && sudo apt upgrade` |
| Fedora 44, Fedora 45 | `sudo dnf upgrade` |

Every repository is signed by the key with fingerprint
`4AAD6D2DE40D0D10773BF770BC27C5EB2831FCDA`; check that it is the one your
package manager or `gpg` shows you.

**Arch Linux and CachyOS:**

```bash
# 1. trust the signing key
curl -fsSL https://raw.githubusercontent.com/Plan-B-Development/pacman-repo/main/keys/ventulus.gpg \
  | sudo pacman-key --add -
sudo pacman-key --lsign-key 4AAD6D2DE40D0D10773BF770BC27C5EB2831FCDA

# 2. add the repository — adds nothing if a [ventulus] block is already there
grep -q '^\[ventulus\]' /etc/pacman.conf || printf '%s\n' '' '[ventulus]' \
  'SigLevel = Required' \
  'Server = https://github.com/Plan-B-Development/pacman-repo/releases/download/repo' \
  | sudo tee -a /etc/pacman.conf

# 3. install — the daemon comes along as a dependency
sudo pacman -Syu ventulus
sudo systemctl enable --now ventulusd
```

**Debian 13 and Ubuntu 26.04:**

```bash
sudo apt install ca-certificates curl gpg
sudo install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://raw.githubusercontent.com/Plan-B-Development/pacman-repo/main/keys/ventulus.gpg \
  | sudo tee /etc/apt/keyrings/ventulus.asc > /dev/null
gpg --show-keys /etc/apt/keyrings/ventulus.asc
printf '%s\n' 'Types: deb' \
  'URIs: https://github.com/Plan-B-Development/pacman-repo/releases/download/repo/' \
  'Suites: ./' \
  'Signed-By: /etc/apt/keyrings/ventulus.asc' \
  | sudo tee /etc/apt/sources.list.d/ventulus.sources
sudo apt update
sudo apt install ventulus   # the daemon starts as it installs
```

**Fedora 44 and 45:**

```bash
curl -fsSL https://plan-b-development.github.io/pacman-repo/ventulus.repo \
  | sudo tee /etc/yum.repos.d/ventulus.repo
sudo dnf install ventulus
sudo systemctl enable --now ventulusd
```

[Getting Started](manual/getting-started.md#installation) also has a signed
bootstrap script for Arch, a tarball for Debian, Ubuntu and Fedora without a
repository, one-off installs from a release, building the packages yourself,
and the distributions that are not supported (among them Manjaro, Debian 12 and
Ubuntu 24.04). Ventulus can also tell you when a new release is out: the
[update check](manual/updates.md) is off until you turn it on or press
**Check for updates**.

## Quick start

1. Check the daemon is running: `systemctl is-active ventulusd`.
2. Start the app: `ventulus`.
3. Follow the [Setup Checklist](manual/setup-checklist.md). It checks your sensors,
   tells you whether your board needs a driver, confirms that fan control works,
   and ends with your first profile.

## How it fits together

The app never touches hardware. It talks only to `ventulusd`, through an HTTP API
on the Unix socket `/run/ventulus/ventulus.sock`. The daemon evaluates the active
profile once a second, writes every fan, and owns thermal safety, so closing or
crashing the app changes nothing about cooling. The app is where you edit
profiles, see what the daemon reports, and run tests through it. Its only other
connection is the opt-in update check, which fetches signed release information
from the project's GitHub Pages site; the daemon never connects to the network.

## Documentation

**User manual** ([contents](manual/README.md)):
[Getting Started](manual/getting-started.md) ·
[Setup Checklist](manual/setup-checklist.md) ·
[Understanding Motherboard Fan Control](manual/understanding-fan-control.md) ·
[Driver Setup](manual/driver-setup.md) ·
[Updates](manual/updates.md) ·
[OpenFAN Controller](manual/openfan-controller.md) ·
[Hardware Troubleshooting](manual/hardware-troubleshooting.md)

**Hardware reference:**

- [Hardware Compatibility](docs/19_Hardware_Compatibility.md): chips, drivers and boards
- [Sensor Interpretation Guide](docs/20_Sensor_Interpretation_Guide.md): what each sensor name means and which to trust
- [AMD Motherboard Fan Control Guide](docs/21_AMD_Motherboard_Fan_Control_Guide.md) and
  [Intel Motherboard Fan Control Guide](docs/23_Intel_Motherboard_Fan_Control_Guide.md): vendor-by-vendor notes
- [AMD Sensor Interpretation Deep Dive](docs/22_AMD_Sensor_Interpretation_Deep_Dive.md): Tctl, Tdie, edge and junction
- [Cooling Hardware Readiness Guide](docs/24_Cooling_Hardware_Readiness_Guide.md): what each item on the Hardware page's readiness checklist means, and how to fix it

**Daemon:** the [ventulusd README](https://github.com/Plan-B-Development/ventulusd) and
its [User Guide](https://github.com/Plan-B-Development/ventulusd/blob/main/docs/USER_GUIDE.md)
(configuration, the service, safety, troubleshooting).

**For contributors:** [CONTRIBUTING](https://github.com/Plan-B-Development/ventulus/blob/main/CONTRIBUTING.md) ·
[API contract](https://github.com/Plan-B-Development/ventulus/blob/main/docs/08_API_Integration_Contract.md) ·
[GPU support rules](https://github.com/Plan-B-Development/ventulus/blob/main/docs/25_GPU_Support_Rules.md) ·
[Changelog](CHANGELOG.md) ·
[Security policy](https://github.com/Plan-B-Development/ventulus/blob/main/SECURITY.md)

## License

MIT. Third-party notices are in [NOTICE.md](https://github.com/Plan-B-Development/ventulus/blob/main/NOTICE.md).
