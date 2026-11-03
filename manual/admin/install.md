# Installing Ventulus

Ventulus is three packages. Which you install depends on the machine:

| Package | What it is | Needs a desktop |
|---|---|---|
| `ventulusd` | The service that reads sensors and drives every fan, as root, under systemd. It also carries `ventulus-tray`, the KDE tray icon, which starts only where `ventulus` is installed | No |
| `ventulus-diag` | The [diagnostic command](diagnostics-cli.md) for the tests that drive fans on purpose, and the Python code the app is built on. Python and httpx only, no Qt | No |
| `ventulus` | The desktop app. Depends on `ventulusd` and on `ventulus-diag` of its own version, so installing it brings both | Yes |

A desktop machine installs `ventulus`. A machine with no desktop installs
`ventulusd`, and `ventulus-diag` if you want the diagnostic tests there
([below](#a-machine-with-no-desktop)).

## What you need

- **x86_64 Linux** on a supported distribution: Arch Linux or one built on it
  (CachyOS, EndeavourOS, Garuda), Debian 13, Ubuntu 26.04 LTS, or Fedora 44 or 45
  ([not supported](#distributions-that-are-not-supported)).
- **systemd.** The daemon runs as a systemd service, and its hand-back after every
  stop is part of the unit.
- **`sudo`** to install. Nothing afterwards needs it: the app and `ventulus-diag`
  run as your own user, and no group membership is needed
  ([Permissions and Security](security.md)).
- The app runs on the distribution's own Python (3.12 or newer), Qt and numpy,
  which the packages pull in.

## Choose an install method

Ventulus is packaged for four families of x86_64 Linux, each with a signed
package repository: set one up once, and both packages then upgrade with the rest
of your system. Every command in this section works as written in bash, zsh and
fish (CachyOS's default shell).

| Distribution | Install from | Upgrades with |
| --- | --- | --- |
| Arch Linux, CachyOS, EndeavourOS, Garuda | the [pacman repository](#arch-linux-and-cachyos) | `sudo pacman -Syu` |
| Debian 13, Ubuntu 26.04 LTS | the [APT repository](#debian-13-and-ubuntu-2604) | `sudo apt update && sudo apt upgrade` |
| Fedora 44, Fedora 45 | the [DNF repository](#fedora) | `sudo dnf upgrade` |
| any of the three above, without a repository | the [tarball](#the-tarball) | Settings ▸ [Updates](../updates.md) |

[Not supported](#distributions-that-are-not-supported): Manjaro, Debian 12,
Ubuntu 24.04 and the distributions built on it, RHEL and its rebuilds, and
openSUSE Leap.

Every repository is signed with one key. Whichever you use, check that the
fingerprint it shows you is this one:

```text
4AAD6D2DE40D0D10773BF770BC27C5EB2831FCDA
```

## Arch Linux and CachyOS

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
covers removing it. For a machine with no desktop, see
[A machine with no desktop](#a-machine-with-no-desktop).

### Or with the bootstrap script

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

## Debian 13 and Ubuntu 26.04

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
started as it installs (`systemctl status ventulusd`). For a machine with no
desktop, see [A machine with no desktop](#a-machine-with-no-desktop).

For two or three minutes after a new release is published, `apt update` can report
a checksum mismatch ("Hash Sum mismatch" or "File has unexpected size") for this
repository, because GitHub keeps serving a replaced index from its cache for a
while. apt then keeps the package lists it had and changes nothing; run
`sudo apt update` again a few minutes later. The
[pacman-repo README](https://github.com/Plan-B-Development/pacman-repo#debian-and-ubuntu)
covers removing the repository.

## Fedora

Fedora 44 and 45.

```bash
curl -fsSL https://plan-b-development.github.io/pacman-repo/ventulus.repo \
  | sudo tee /etc/yum.repos.d/ventulus.repo
sudo dnf install ventulus
sudo systemctl enable --now ventulusd
```

On the first install, dnf asks to import the signing key and prints its
fingerprint: check it against the one above. The line before it,
`repomd.xml GPG signature verification error: Signing key not found`, only
means the key is not imported yet. dnf then checks the signature of the
repository's metadata and of every package. Fedora leaves a newly installed
service disabled, so the `systemctl enable --now` line is needed; without it
Ventulus opens to a "Disconnected" screen. For a machine with no desktop, see
[A machine with no desktop](#a-machine-with-no-desktop); for what happens after a
Fedora release upgrade, see [Upgrading § Fedora](upgrade.md#fedora).

## The tarball

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

A fresh daemon install is left disabled, which is why step 2 enables it.
[Upgrading § The tarball](upgrade.md#the-tarball) and
[Uninstalling](uninstall.md) cover the rest of its life.

## One-off install from a release

To install without setting up a repository, download the packages attached to
each release. They are the same builds the repositories serve, each with a Sigstore
build attestation you can check first. The GUI's release carries two packages,
`ventulus` and `ventulus-diag`, which it depends on; checking the release's
attested `SHA256SUMS` covers both. On Arch:

```bash
gh release download --repo Plan-B-Development/ventulusd --dir ventulusd --pattern '*.pkg.tar.zst' --pattern SHA256SUMS
gh release download --repo Plan-B-Development/ventulus  --dir ventulus  --pattern '*.pkg.tar.zst' --pattern SHA256SUMS
gh attestation verify ventulusd/SHA256SUMS --repo Plan-B-Development/ventulusd
gh attestation verify ventulus/SHA256SUMS  --repo Plan-B-Development/ventulus
cd ventulusd && sha256sum -c --ignore-missing SHA256SUMS && cd ..
cd ventulus && sha256sum -c --ignore-missing SHA256SUMS && cd ..
sudo pacman -U ventulusd/*.pkg.tar.zst ventulus/*.pkg.tar.zst
sudo systemctl enable --now ventulusd
```

On Debian 13 and Ubuntu 26.04, download `--pattern '*.deb'` and install with
`sudo apt install ./ventulusd_*_amd64.deb ./ventulus_*_all.deb ./ventulus-diag_*_all.deb`. On Fedora,
download `--pattern '*.rpm'` and install with
`sudo dnf install ./ventulusd-*.x86_64.rpm ./ventulus-*.fcN.noarch.rpm` (the
pattern takes `ventulus-diag`, which the GUI needs, too), where N
is your Fedora release (`rpm -E %fedora` prints it), then
`sudo systemctl enable --now ventulusd`. Upgrading then means repeating the
downloads, which is the chore the repositories exist to remove
([Upgrading](upgrade.md#one-off-installs-from-a-release)).

## Build the packages yourself

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

## Running from a source checkout

To run the GUI from a checkout, for development, see
[CONTRIBUTING](https://github.com/Plan-B-Development/ventulus/blob/main/CONTRIBUTING.md#setup).
A checkout does not include the daemon; install `ventulusd` as above. To build or
run the daemon yourself, see its
[`daemon/README.md`](https://github.com/Plan-B-Development/ventulusd/blob/main/daemon/README.md):
install a package rather than copying the binary in by hand (see
[What the packages set up](#what-the-packages-set-up)).

## Distributions that are not supported

Manjaro, Debian 12, Ubuntu 24.04 LTS and the distributions built on it (Linux
Mint 22, Pop!_OS 24.04), RHEL, AlmaLinux and Rocky Linux 9 and 10, and openSUSE
Leap 16 get no package. Each lacks something Ventulus needs from the
distribution: a PySide6 package, numpy 2 or newer, or a pyqtgraph package.
Manjaro has those, but the GUI package installs into the Python version current
Arch ships, and Manjaro's can lag behind it.

Ventulus does not bundle its own Python and Qt to get round this: that would be
several hundred megabytes, and their security fixes would then have to come from
this project instead of from your distribution.

## After installing

The commands above leave `ventulusd` enabled and running
(`systemctl is-active ventulusd` prints `active`), so it starts at every boot.
Before you open Ventulus:

**Reboot, or load the sensor drivers now.** The daemon package lists the common
motherboard sensor drivers (`nct6775`, `it87` and `w83627ehf`) and the SATA drive
temperature driver (`drivetemp`) in `/etc/modules-load.d/ventulus.conf`, which
systemd reads as the machine starts. No package loads them as it installs, so until
the next boot your motherboard's fans and temperatures can be missing. To skip the
reboot, load them and then restart the daemon, which looks for fan headers only as
it starts:

```bash
sudo systemctl restart systemd-modules-load
sudo systemctl restart ventulusd
```

On most machines other than Gigabyte boards, the first command says that the job
failed, and from then on `systemctl --failed` lists `systemd-modules-load.service`
after every boot. That is a fault in the package, not in your system, and it stops
nothing from loading: `nct6775` or `w83627ehf` found no chip on your board, and the
package's Super-I/O guard, which loads those two, reports that as an error. Every
other module still loads, including the drivers that match your board. To see which
of the package's drivers loaded:

```bash
lsmod | grep -E '^(nct6775|it87|w83627ehf|drivetemp) '
```

**You do not need to log out.** Ventulus reaches the daemon through a socket that
every local user can open, so there is no group to join. On KDE Plasma, the system
tray icon starts at your next login.

You do not need `lm_sensors`, DKMS or an out-of-tree driver to start. Open
Ventulus and let it show you what your kernel already exposes: the **System State**
and **Hardware** pages name a driver or setting only when your hardware needs one.
The [Setup Checklist](../setup-checklist.md) takes it from there, and
[Getting Started § First launch](../getting-started.md#first-launch) says what
the app does when it opens.

## A machine with no desktop

The daemon needs no desktop, and neither does `ventulus-diag`; only the app does.

| Install from | Daemon only | Daemon and the diagnostic tests |
|---|---|---|
| pacman | `sudo pacman -Syu ventulusd` | `sudo pacman -Syu ventulusd ventulus-diag` |
| APT | `sudo apt install ventulusd` | `sudo apt install ventulusd ventulus-diag` |
| DNF | `sudo dnf install ventulusd` | `sudo dnf install ventulusd ventulus-diag` |
| the tarball | step 2 [above](#the-tarball) | step 2, then step 3 with `--cli-only`: `install.sh --deps --cli-only` prints the shorter list of what it needs, and `sudo ./ventulus-*-noarch/install.sh --cli-only` installs it |

On Arch and Fedora, enable the daemon afterwards (`sudo systemctl enable --now
ventulusd`); on Debian and Ubuntu it starts as it installs. Without the app,
profiles, roles and settings are managed through the daemon's API or its
configuration file: see the daemon's
[User Guide](https://github.com/Plan-B-Development/ventulusd/blob/main/docs/USER_GUIDE.md).
The tray icon does not start where `ventulus` is not installed.

## What the packages set up

Every format installs the same files for the daemon:

- the service, `ventulusd.service`, with `ventulus-restore-auto`, which runs after
  every stop and gives each fan header back to what it was doing before the daemon
  took it, even after a crash or a kill;
- a system-sleep hook, so a suspend and resume does not trip the service's hang
  check;
- `/etc/modules-load.d/ventulus.conf`, which loads the common motherboard sensor
  drivers at boot, and the Super-I/O guard for Gigabyte boards
  ([Drivers](drivers.md));
- `/etc/ventulus/daemon.toml`, the configuration, and an example profile;
- examples, as documentation only, of a udev rule and of the opt-in systemd
  drop-ins, under `/usr/share/doc/ventulusd/`.

Do not install the daemon by copying its binary and unit file in by hand: none of
the above comes with them.

Each format starts the service its own way:

| Format | A new install |
|---|---|
| APT (Debian, Ubuntu) | enabled and started as it installs |
| pacman (Arch) | left disabled: `sudo systemctl enable --now ventulusd` |
| DNF (Fedora) | left disabled: `sudo systemctl enable --now ventulusd` |
| the tarball | left disabled: `sudo systemctl enable --now ventulusd` |

What an upgrade does to a running daemon is in [Upgrading](upgrade.md).

Installing changes no fan. Fan control starts only when you apply a profile (or
run a test). Until then the BIOS runs the fans as before, and only the daemon's
thermal emergency can act ([Service](service.md)).

---

Back to [Administration](README.md)
