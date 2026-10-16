# Getting Started

## What you need

- **x86_64 Linux**: Arch Linux or a distribution built on it such as CachyOS, Debian 13, Ubuntu 26.04 LTS, or Fedora 44 or 45 (see [Installation](#installation), which also lists the distributions that are not supported). Ventulus runs on the distribution's own Python (3.12 or newer), Qt and numpy.
- **ventulusd**, the service that does the hardware work, running under systemd. Installing the `ventulus` package pulls it in.
- A supported fan controller: an OpenFAN controller, motherboard fan headers, or an AMD GPU.

The GUI never accesses hardware directly. All reads and writes go through the daemon's API over a local Unix socket.

### Supported coolers and controllers

The daemon drives hardware only through Linux's own drivers. It never talks to a USB
device directly and does not use `liquidctl`, so what it can reach is what the kernel
exposes.

| Hardware | What Ventulus can do |
|---|---|
| **OpenFAN controller** (USB) | Full control of every channel (see [OpenFAN Controller](openfan-controller.md)) |
| **Motherboard fan headers** (ITE and Nuvoton Super-I/O chips) | Full control on most boards; some need an out-of-tree driver or a BIOS setting first (see [Driver Setup](driver-setup.md)) |
| **Dell laptops and some Dell desktops** (`dell_smm`) | Control on models the kernel driver allows; many share one BIOS switch across every fan (see [Driver Setup](driver-setup.md)) |
| **AMD discrete GPUs** | RX 7000/9000: full control through the firmware fan curve, which needs a one-time kernel setting (see [Driver Setup](driver-setup.md#amd-gpu-fan-control-prerequisite-rdna3)). RX 6000 and older: monitored, and the fan can be tested and reset, but a profile does not drive it: the card's own fan curve stays in charge |
| **Intel Arc and NVIDIA GPUs** | Monitor only: temperature and fan speed. An NVIDIA card of the Turing (RTX 20) generation or newer is seen only through the proprietary driver's opt-in NVML telemetry, not through `nouveau` (see [Hardware Troubleshooting](hardware-troubleshooting.md#nvidia-gpus-are-monitor-only)) |
| **NZXT Kraken X53/X63/X73, Z53/Z63/Z73, Kraken 2023, 2023 Elite and 2024 Elite** (`nzxt-kraken3`; the 2024 Elite needs kernel 7.3 or newer) | Pump and fans controllable, coolant temperature read |
| **NZXT Kraken X42/X52/X62/X72** (`nzxt-kraken2`) | Monitor only: the driver cannot set its speeds |
| **Aquacomputer D5 Next** (`aquacomputer_d5next`) | Pump and fan controllable, coolant temperature read |
| **Aquacomputer High Flow Next and Leakshield** | Coolant temperature read; they drive no fan |
| **Fan controllers:** Corsair Commander Pro, NZXT Smart Device V2 / RGB & Fan Controller, Aquacomputer Octo, Quadro and Aquaero | Fan channels controllable |
| **Any AIO whose pump plugs into a motherboard header** | Controlled as a motherboard header; tell **Configure AIO** which header is the pump so it gets its protection (see [Controls](controls.md#if-your-aio-is-plugged-into-the-motherboard)) |

A cooler with no mainline kernel driver (most USB coolers not listed here) is not
visible to Ventulus. Plugging its pump into a motherboard header, where the cooler
allows it, is the usual way round that.

### Drivers and kernel settings

The package loads the common motherboard sensor drivers for you, so many machines
need nothing more. Two cases do:

- Newer Gigabyte, MSI and some ASRock boards (2022 and later) need an out-of-tree
  driver, built with DKMS from its upstream project (on Arch, from the AUR).
- An AMD RX 7000 or RX 9000 needs the kernel parameter
  `amdgpu.ppfeaturemask=0xfff7ffff` before its fan can be controlled.

You do not have to work this out first. Install, launch Ventulus, and the
**System State** and **Hardware** pages name your chips and say exactly which
driver or setting your machine needs. [Driver Setup](driver-setup.md) has the
copy-paste steps for both cases, including each bootloader and how to undo it
all. The [Setup Checklist](setup-checklist.md) takes you through the whole path in
order, from install to your first profile, and
[Understanding Motherboard Fan Control](understanding-fan-control.md) explains
why each step is needed.

## Installation

Ventulus is packaged for four families of x86_64 Linux, each with a signed
package repository: set one up once, and both packages then upgrade with the rest
of your system. Every command in this section works as written in bash, zsh and
fish (CachyOS's default shell).

| Distribution | Install from | Upgrades with |
| --- | --- | --- |
| Arch Linux, CachyOS, EndeavourOS, Garuda | the [pacman repository](#arch-linux-and-cachyos) | `sudo pacman -Syu` |
| Debian 13, Ubuntu 26.04 LTS | the [APT repository](#debian-13-and-ubuntu-2604) | `sudo apt update && sudo apt upgrade` |
| Fedora 44, Fedora 45 | the [DNF repository](#fedora) | `sudo dnf upgrade` |
| any of the three above, without a repository | the [tarball](#the-tarball) | Settings ▸ [Updates](updates.md) |

[Not supported](#distributions-that-are-not-supported): Manjaro, Debian 12,
Ubuntu 24.04 and the distributions built on it, RHEL and its rebuilds, and
openSUSE Leap.

Every repository is signed with one key. Whichever you use, check that the
fingerprint it shows you is this one:

```text
4AAD6D2DE40D0D10773BF770BC27C5EB2831FCDA
```

### Arch Linux and CachyOS

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

`SigLevel = Required` means pacman refuses any package or database not signed by
that key. The [pacman-repo README](https://github.com/Plan-B-Development/pacman-repo)
covers upgrading and removing it. A machine with no desktop needs only the daemon:
install `ventulusd` instead of `ventulus` in step 3.

#### Or with the bootstrap script

A signed script does the same setup in one step. It first prints what it found
(distribution, CPU architecture, init system) and stops, changing nothing, on a
machine the packages cannot work on: a distribution not built on Arch, Manjaro, a
CPU other than x86_64, a system not running systemd, or one without pacman or
sudo. Otherwise it trusts the
signing key (checking the fingerprint first), adds the repository, installs both
packages and enables the daemon, and it is safe to re-run. Verify its signature
before you run it: that check is what stops a tampered script from installing your
system packages.

Manjaro is not supported, by the script or by hand: the GUI package installs into
the Python version current Arch ships, and Manjaro's can lag behind it.

```bash
curl -fsSLO https://github.com/Plan-B-Development/pacman-repo/releases/download/repo/bootstrap.sh
curl -fsSLO https://github.com/Plan-B-Development/pacman-repo/releases/download/repo/bootstrap.sh.sig
curl -fsSL https://raw.githubusercontent.com/Plan-B-Development/pacman-repo/main/keys/ventulus.gpg | gpg --import
gpg --verify bootstrap.sh.sig bootstrap.sh   # expect 4AAD6D2DE40D0D10773BF770BC27C5EB2831FCDA
less bootstrap.sh                            # read it — it runs commands as root
bash ./bootstrap.sh
```

The install is a full `sudo pacman -Syu` and asks you to confirm the transaction
once, so it may upgrade more than Ventulus.

### Debian 13 and Ubuntu 26.04

One repository serves both.

```bash
# 1. trust the signing key, and check the fingerprint gpg prints
sudo apt install ca-certificates curl gpg
sudo install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://raw.githubusercontent.com/Plan-B-Development/pacman-repo/main/keys/ventulus.gpg \
  | sudo tee /etc/apt/keyrings/ventulus.asc > /dev/null
gpg --show-keys /etc/apt/keyrings/ventulus.asc

# 2. add the repository and install — the daemon comes along as a dependency
printf '%s\n' 'Types: deb' \
  'URIs: https://github.com/Plan-B-Development/pacman-repo/releases/download/repo/' \
  'Suites: ./' \
  'Signed-By: /etc/apt/keyrings/ventulus.asc' \
  | sudo tee /etc/apt/sources.list.d/ventulus.sources
sudo apt update
sudo apt install ventulus
```

Keep the `.asc` name: the key file is armored, and apt expects an armored key file
to end in `.asc`. `Signed-By` limits the key to this repository, and apt refuses
the repository's indexes unless that key signed them. The daemon is enabled and
started as it installs (`systemctl status ventulusd`). A machine with no desktop
needs only `sudo apt install ventulusd`.

For two or three minutes after a new release is published, `apt update` can report
a checksum mismatch ("Hash Sum mismatch" or "File has unexpected size") for this
repository, because GitHub keeps serving a replaced index from its cache for a
while. apt then keeps the package lists it had and changes nothing; run
`sudo apt update` again a few minutes later. The
[pacman-repo README](https://github.com/Plan-B-Development/pacman-repo#debian-and-ubuntu)
covers removing the repository.

### Fedora

Fedora 44 and 45.

```bash
curl -fsSL https://plan-b-development.github.io/pacman-repo/ventulus.repo \
  | sudo tee /etc/yum.repos.d/ventulus.repo
sudo dnf install ventulus
sudo systemctl enable --now ventulusd
```

On the first install, dnf asks to import the signing key and prints its
fingerprint: check it against the one above. dnf then checks the signature of the
repository's metadata and of every package. Fedora leaves a newly installed
service disabled, so the `systemctl enable --now` line is needed; without it
Ventulus opens to a "Disconnected" screen. A machine with no desktop needs only
`sudo dnf install ventulusd`.

The repository is built per Fedora release, so after a Fedora upgrade it serves
packages only once a build for the new release is published. Until then dnf
skips it with a warning and leaves Ventulus as it is; everything else upgrades as
usual. An older `ventulus.repo`, one without the line `skip_if_unavailable=True`,
stops every dnf command instead: fetch it again with the first command above.
dnf reuses the repository's metadata for up to six
hours: if it reports a missing package or a checksum error right after a new
Ventulus release, `sudo dnf upgrade --refresh` fetches it again.

### The tarball

Each release also carries a tarball of each component, for a Debian 13,
Ubuntu 26.04 or Fedora 44 or 45 machine where you would rather not add a repository.
`ventulusd` installs to the same paths as its packages (`/usr/bin`,
`/usr/lib/systemd/system`, `/etc/ventulus`), and Ventulus under `/usr/local`.
Ventulus runs on the distribution's own Python, Qt and numpy, so their packages
come first: `install.sh --deps` prints the `apt` or `dnf` command that installs
them, and `install.sh` installs nothing while one is missing. Each installer
refuses if a package manager already owns that component.

This uses the [GitHub CLI](https://cli.github.com/) (`gh`, packaged by all three
distributions) to download each release and check its
[Sigstore](https://www.sigstore.dev/) build attestation, which proves the file was
built by the project's release workflow:

```bash
# 1. download each release's tarball and checksum list, and check both
gh release download --repo Plan-B-Development/ventulusd --dir ventulusd --pattern '*.tar.gz' --pattern SHA256SUMS
gh release download --repo Plan-B-Development/ventulus --dir ventulus --pattern '*.tar.gz' --pattern SHA256SUMS
gh attestation verify ventulusd/ventulusd-*.tar.gz --repo Plan-B-Development/ventulusd
gh attestation verify ventulus/ventulus-*.tar.gz --repo Plan-B-Development/ventulus

# 2. the daemon
cd ventulusd
sha256sum -c --ignore-missing SHA256SUMS
tar xf ventulusd-*-x86_64.tar.gz
sudo ./ventulusd-*-x86_64/install.sh
sudo systemctl enable --now ventulusd
cd ..

# 3. the app: install what it needs, then the app
cd ventulus
sha256sum -c --ignore-missing SHA256SUMS
tar xf ventulus-*-noarch.tar.gz
./ventulus-*-noarch/install.sh --deps   # prints a command: run it
sudo ./ventulus-*-noarch/install.sh
cd ..
```

A fresh daemon install is left disabled, which is why step 2 enables it. To
upgrade, let Settings ▸ [Updates](updates.md) download and check the new tarball
and give you the line that installs it, or repeat these steps with the new
release: `install.sh` upgrades an earlier tarball install in place, keeps a
configuration file you edited (writing the new default beside it as `.new`), and
restarts a running daemon. To remove them:

```bash
sudo /usr/local/lib/ventulus/uninstall
sudo /usr/lib/ventulus/uninstall
```

The daemon's uninstaller stops it first, so every fan header is given back, and
keeps an edited configuration file and the daemon's state in `/var/lib/ventulus`.

### One-off install from a release

To install without setting up a repository, download the packages attached to
each release. They are the same builds the repositories serve, each with a Sigstore
build attestation you can check first. On Arch:

```bash
gh release download --repo Plan-B-Development/ventulusd --pattern '*.pkg.tar.zst'
gh release download --repo Plan-B-Development/ventulus    --pattern '*.pkg.tar.zst'
gh attestation verify ./ventulusd-*.pkg.tar.zst --repo Plan-B-Development/ventulusd
gh attestation verify ./ventulus-*.pkg.tar.zst  --repo Plan-B-Development/ventulus
sudo pacman -U ./ventulusd-*.pkg.tar.zst ./ventulus-*.pkg.tar.zst
sudo systemctl enable --now ventulusd
```

On Debian 13 and Ubuntu 26.04, download `--pattern '*.deb'` and install with
`sudo apt install ./ventulusd_*_amd64.deb ./ventulus_*_all.deb`. On Fedora,
download `--pattern '*.rpm'` and install with
`sudo dnf install ./ventulusd-*.x86_64.rpm ./ventulus-*.fcN.noarch.rpm`, where N
is your Fedora release (`rpm -E %fedora` prints it), then
`sudo systemctl enable --now ventulusd`. Upgrading then means repeating the
downloads, which is the chore the repositories exist to remove. Settings ▸
[Updates](updates.md) can tell you when a new release is out.

### Build the packages yourself

On Arch, to avoid trusting a prebuilt binary, build both packages from their
`PKGBUILD`s. Build the daemon first, because the GUI package depends on it:

```bash
git clone https://github.com/Plan-B-Development/ventulusd.git
makepkg -si -D ventulusd/packaging
git clone https://github.com/Plan-B-Development/ventulus.git
makepkg -si -D ventulus/packaging
sudo systemctl enable --now ventulusd
```

`makepkg` builds the tagged release from its source tarball, not the checkout you
cloned. Each `PKGBUILD`'s `sha256sums` is `SKIP` rather than a pinned hash, so no
`updpkgsums` step is needed. It cannot be a real hash: the tarball GitHub generates
for a tag contains that `PKGBUILD`, so writing a sum into it changes the archive the
sum pins. `makepkg` therefore trusts the HTTPS fetch from the repository's own tag.
For an input that is pinned and verifiable, use the release packages above and check
their Sigstore attestations.

The `.deb`, `.rpm` and tarball are built by `packaging/linux/build.sh` in each
repository, as the release does; the daemon's
[`daemon/README.md`](https://github.com/Plan-B-Development/ventulusd/blob/main/daemon/README.md#debian-ubuntu-fedora-and-the-tarball)
shows how.

### Running from a source checkout

To run the GUI from a checkout, for development, see
[CONTRIBUTING](https://github.com/Plan-B-Development/ventulus/blob/main/CONTRIBUTING.md#setup).
A checkout does not include the daemon; install `ventulusd` as above.

### Distributions that are not supported

Manjaro, Debian 12, Ubuntu 24.04 LTS and the distributions built on it (Linux
Mint 22, Pop!_OS 24.04), RHEL, AlmaLinux and Rocky Linux 9 and 10, and openSUSE
Leap 16 get no package. Each lacks something Ventulus needs from the
distribution: a PySide6 package, numpy 2 or newer, or a pyqtgraph package.
Manjaro has those, but the GUI package installs into the Python version current
Arch ships, and Manjaro's can lag behind it.

Ventulus does not bundle its own Python and Qt to get round this: that would be
several hundred megabytes, and their security fixes would then have to come from
this project instead of from your distribution.

## First launch

```bash
ventulus
```

On first launch, Ventulus will:

1. Attempt to connect to the daemon at `/run/ventulus/ventulus.sock` (`ventulus --socket <path>` points it elsewhere, for a daemon started with a non-default socket)
2. If the daemon is reachable, fetch hardware capabilities and begin polling
3. If the daemon is not reachable, show a "Disconnected" state (or enter demo mode if configured)
4. Open the **Dashboard** page

If it stays **Disconnected**, check that the daemon is running
(`systemctl is-active ventulusd` should print `active`) and that its socket exists
(`ls -la /run/ventulus/ventulus.sock`). The daemon's
[User Guide](https://github.com/Plan-B-Development/ventulusd/blob/main/docs/USER_GUIDE.md#troubleshooting)
covers a daemon that will not start.

Applying a profile hands it to the daemon, which saves your choice: it keeps
running after you close Ventulus and comes back after a reboot. The
[Setup Checklist](setup-checklist.md) ends with your first one.

### Demo mode

If you want to explore the interface without hardware or a running daemon:

```bash
ventulus --demo
```

Demo mode generates synthetic sensor temperatures and fan speeds. You can create profiles, edit curves and explore the UI, but not everything works as it does against a real daemon: the PWM Test Report will not start, hardware advisories and some checks are skipped, and Import Config and the profiles and themes folder settings are unavailable. **System State** and the Hardware page's **Voltages** table show a synthetic Gigabyte X870E AORUS MASTER, and a support bundle exported in demo carries those synthetic readings. **Profiles you create or edit in demo are not saved**: they last until demo ends. The top ribbon and the status banner read *Demo — simulated* where they would show the daemon connection, a **DEMO** badge appears in the status banner, and the footer's mode reads *Demo mode*, so you always know when synthetic data is being shown.

You can also enable "Start in demo mode when daemon is unavailable" in Settings so the GUI falls back to demo automatically.

### Only one window

Launching Ventulus while it is already running brings the existing window to
the front rather than opening a second copy. This applies however you start it:
the system tray, the application menu, or a terminal.

Demo mode is treated separately, so `ventulus --demo` still opens its own
window even if a normal Ventulus is already running.

On Wayland the compositor decides whether a window may jump to the front. Usually
it does; occasionally it will flag the task-bar entry as needing attention
instead of raising the window. Clicking that entry brings it up.

### The system tray

If you are on KDE Plasma, a Ventulus icon appears in your system tray. It is
installed with the daemon and starts when you log in.

- **Left click**: open Ventulus.
- **Right click**: see which daemon version is running, switch profiles, stop
  profile control, or open Ventulus.

The tray never controls fans itself; it asks the daemon, exactly as this
application does. Closing it changes nothing about cooling.

To turn it off: **System Settings → Autostart**. For anything more, see
`man ventulus-tray`.

## The status bars

Three strips frame every page:

| Strip | What it shows |
|-------|---------------|
| **Top ribbon** (every page) | The daemon's connection state with a status light (*Demo — simulated* in demo mode), the daemon's uptime, a thermal pill (both blank while disconnected), and **Alerts** with a count. Click it to jump to the **Logs** page, the single surface that lists them |
| **Status banner** (under the ribbon, on every page except the Dashboard, which has its own status strip) | Connection (green "Connected", yellow "Degraded" or red "Disconnected"; "Demo — simulated" in demo mode), the active profile (or "No profile"), the number of warnings (not clickable; use **Alerts**), and a **DEMO** badge in demo mode |
| **Footer** (every page) | How long ago the last poll arrived, the mode, the thermal state (click it for the detail), a hardware-readiness chip, a health light, **Rescan Hardware** and **Export Support Bundle**. The mode is "Automatic" (the daemon runs your fans), "Read-only" (the daemon is not connected; it clears on the next successful poll) or "Demo mode" |

Two banners can appear across the top of the window when the GUI and the daemon do not fit together:

- **"Daemon upgrade required"**: the daemon is too old for this GUI to control, so the GUI stands down: **Apply**, **Stop** and **Manual** are off until you upgrade `ventulusd`.
- **"This GUI is older than the daemon supports"**: the daemon declares a minimum GUI version above this one. Fan control is unaffected (the daemon drives the fans itself), but some screens may not show everything the daemon can do. Upgrade `ventulus`.

### Keyboard shortcuts

| Where | Keys |
|-------|------|
| **Controls** page | `Ctrl+S` saves the profile; `Esc` closes the curve editor while it has focus |
| Curve editor | `Ctrl+Z` / `Ctrl+Shift+Z` undo and redo; `Delete` or `Backspace` removes the selected point |
| **Logs** page (list focused) | `/` jumps to the search box; `f` toggles follow; `Esc` closes the inspector |
| Dashboard **Sensors** panel | `F2` renames the selected fan |

> If the daemon's API version does not match the version this GUI was built for (an out-of-lockstep package upgrade), the Dashboard shows a warning banner asking you to align the `ventulusd` and `ventulus` package versions. This is non-fatal (the GUI keeps working), but some features may misbehave until the versions match.

## Navigation

The left sidebar provides access to all of the application's pages:

| Page | Purpose |
|------|---------|
| **Dashboard** | At-a-glance monitoring: temperatures, fan speeds, charts |
| **Overview** | Daemon health, device discovery, and live sensor and fan status |
| **Controls** | Profile management, fan grouping, curve editing |
| **System State** | The health report: chip and driver detection, BIOS interference, thermal and GPU limits, and advanced fan and GPU tests |
| **Hardware** | The daemon's readiness checklist, your coolers and every PWM header (**Cooling Hardware**), the fan tests and the **PWM Test Report** (**Hardware Diagnostics**), and the Super-I/O architecture |
| **Settings** | Application preferences and backup/restore |
| **Theme** | Fonts, sizes, and the colour-token editor |
| **Logs** | Event log and current alerts (the support bundle is exported from the footer) |

An **About** button at the bottom of the sidebar shows the Ventulus and `ventulusd` versions and credit information, and has a **Check for updates** button (see [Updates](updates.md)):

![About dialog](https://raw.githubusercontent.com/Plan-B-Development/ventulus/main/screenshots/auto/09_about_dialog.png)

---

Next: [Setup Checklist](setup-checklist.md)
