# Driver Setup (Beginner Walkthrough)

This page walks a **new Linux user** from "my motherboard fans don't show up" to "verified working fan headers", one copy-paste step at a time. It also covers the one [kernel parameter](#amd-gpu-fan-control-prerequisite-rdna3) that AMD RDNA3+ GPU fan control needs, and [what to do when Secure Boot blocks a driver](#secure-boot-and-dkms-modules). Where a command differs between distributions, this page gives it for Arch Linux (CachyOS and the other Arch derivatives too), Debian and Ubuntu, and Fedora.

For board-by-board detail, see the [AMD](../docs/21_AMD_Motherboard_Fan_Control_Guide.md) and [Intel](../docs/23_Intel_Motherboard_Fan_Control_Guide.md) fan-control guides; the full chip matrix is [Hardware Compatibility](../docs/19_Hardware_Compatibility.md).

> **⚠ Before you start.** These steps change kernel parameters, driver and module
> configuration, or firmware (UEFI/BIOS) settings. Back up your configuration first:
> an incorrect kernel parameter can stop the system booting. The drivers installed here
> are **third-party, out-of-tree kernel modules** maintained by their upstream projects,
> not by Ventulus. Where this page conflicts with your hardware vendor's or
> distribution's documentation, prefer theirs. Every change has a
> [rollback](#rollback--undoing-everything), and the manual's [notice](README.md)
> applies throughout.

## Step 0 — Do you even need this?

Many boards work out of the box with mainline kernel drivers. Check first:

1. Start the GUI and open the **System State** page.
2. Click **Rescan Hardware** in the footer.
3. Look at the **System Health Overview** summary line and the cards below it.

If it reports your PWM headers with a non-zero **writable** count and no issues, you are done and need no driver work. If it reports *"No hwmon chips detected"*, *"All PWM headers are read-only"*, or a **Hardware Registry** row whose status says **"not loaded — install …"**, continue below.

## Step 1 — Identify your board and chip

The **System State** page's summary line shows what DMI reports (e.g. `Gigabyte Technology Co., Ltd. — X870E AORUS MASTER — BIOS F14c`), and its **Hardware Registry** table lists every detected Super-I/O chip with the driver bound to it. The page is the easiest path because it already cross-references the project's chip knowledge base.

From a terminal, the same facts come from:

```bash
# Board identity
cat /sys/class/dmi/id/board_vendor /sys/class/dmi/id/board_name

# Which hwmon chips the kernel currently exposes
cat /sys/class/hwmon/hwmon*/name

# What the it87 driver saw at probe time (ITE boards)
sudo dmesg | grep -i 'it87'
```

Rule of thumb by vendor (full matrix: [Hardware Compatibility](../docs/19_Hardware_Compatibility.md)):

| Board vendor | Typical chip | Driver you likely need |
|---|---|---|
| Gigabyte (2019+, most AORUS) | ITE IT8686E/IT8688E/IT8689E/IT8696E (+ an IT8792E or IT87952E secondary on dual-chip boards) | `frankcrawford/it87` (out-of-tree) |
| MSI (B550/A520, Intel 600-series and newer) | Nuvoton NCT6687D | `Fred78290/nct6687d` (out-of-tree) |
| MSI (AM4 300/400-series, the original 2019 X570 boards) | Nuvoton NCT6795D / NCT6797D | **none** (mainline `nct6775`). Do **not** install `nct6687d` here |
| ASUS (AM4 500, Intel 600/700) | Nuvoton NCT6798D | usually **none** (mainline `nct6775`) |
| ASUS (AM5, Intel Z890/B860) | Nuvoton NCT6799D (AM5 600) or NCT6701D (AM5 800, Z890/B860), both reported as `nct6799` | usually **none** (mainline `nct6775`) |
| ASUS (AM4 300/400-series, e.g. PRIME X470-PRO) | ITE IT8665E | `frankcrawford/it87` (out-of-tree), because mainline has no IT8665E driver |
| ASRock | Nuvoton NCT67xx, and on many boards an NCT6686D/NCT6683D carrying some or all fans | the NCT67xx needs none; the NCT668x fans are read-only in the kernel driver and need a board-specific out-of-tree driver. See the [ASRock notes](../docs/21_AMD_Motherboard_Fan_Control_Guide.md#asrock) |
| Dell (laptops, and some desktops) | none: the fans are run by the BIOS's System Management Mode, not a Super-I/O chip | **none** (mainline `dell_smm_hwmon`, which appears as `dell_smm`). Software control needs your model on the driver's fan-control list; without it the BIOS stays in charge and can override any speed that is set. Many models give every fan **one shared BIOS switch**, so a profile must control all of their fans or none (see [Controls](controls.md)), and the fans usually have only a few speed steps rather than a smooth range |

> **Don't guess.** Installing the wrong out-of-tree driver can actively harm: the `nct6687`/`nct6775` chip-ID collision has bricked a CPU fan header in the wild. If both are loaded, the **System State** page shows a critical *Driver module collision* condition; deactivate the active profile at once (**Stop** under the sidebar's profile selector, or the tray's **Stop profile control**) and run no fan tests until you have rebooted and it is gone. That stops your curve, but not every write: the daemon still restores each header's original setting once, and only removing the wrong driver (blacklist it, then reboot) stops writes to the chip. Only install a driver the readiness report or the compatibility matrix recommends for your identified chip.

## Step 2 — Prerequisites (DKMS + kernel headers)

Out-of-tree drivers are rebuilt against your kernel by **DKMS**, which needs the **headers for the exact kernel you boot**, plus git and a compiler to build the driver:

```bash
# See which kernel you are running
uname -r

# Arch mainline kernel
sudo pacman -S --needed base-devel git dkms linux-headers

# Arch LTS kernel
sudo pacman -S --needed base-devel git dkms linux-lts-headers

# CachyOS — match your installed kernel flavour
sudo pacman -S --needed base-devel git dkms linux-cachyos-headers
# or: linux-cachyos-bore-headers / linux-cachyos-lts-headers / linux-cachyos-deckify-headers

# Debian and Ubuntu
sudo apt install git build-essential dkms linux-headers-$(uname -r)

# Fedora
sudo dnf install git make gcc dkms kernel-devel-$(uname -r)
```

To confirm the headers match, compare `uname -r` against `pacman -Q | grep -- -headers` (Arch), `dpkg -l 'linux-headers-*'` (Debian, Ubuntu) or `rpm -q kernel-devel` (Fedora). A mismatch (e.g. headers for `linux` while booting `linux-cachyos`) is the single most common reason a DKMS build "succeeds" but the module never loads. On Debian and Ubuntu, the lines above install headers for the running kernel only; so that DKMS can also rebuild the driver for the next kernel, install the headers metapackage that follows your kernel (`linux-headers-amd64` on Debian, `linux-headers-generic` on Ubuntu's standard kernel). If a kernel update is installed but you have not rebooted into it yet, reboot before Step 3: the it87 script builds only for the kernel you are running, so the waiting kernel would boot with the in-kernel driver. If fans disappear after a reboot into a new kernel anyway, `sudo dkms autoinstall` builds the driver for it. (Fedora rebuilds at boot by itself.)

> **CachyOS-LTS / Tumbleweed path quirk:** the it87 DKMS config has a known module-install-path bug on some kernels: the module builds but lands in a directory the kernel does not search ([frankcrawford/it87 issue #94](https://github.com/frankcrawford/it87/issues/94)). If `modprobe` says *module not found* right after a clean DKMS build, run `dkms status` and check where the module was installed versus `/lib/modules/$(uname -r)/`.

## Step 3 — Install the driver

The two drivers are third-party projects: [`frankcrawford/it87`](https://github.com/frankcrawford/it87) for ITE chips (most Gigabyte boards) and [`Fred78290/nct6687d`](https://github.com/Fred78290/nct6687d) for MSI's NCT6687D. Install only the one your board needs. On Arch they are packaged in the AUR; on Debian, Ubuntu and Fedora you build them with each project's own DKMS scripts. The Hardware page's **How to enable** section shows the same steps for the distribution you are running, with copy buttons.

Run every command as your normal user; each one asks for your password where it needs root.

### Arch Linux and CachyOS

Both drivers come from the AUR (the Arch User Repository), which `pacman` does not read. With an AUR helper such as `yay` or `paru` (CachyOS ships both), it is one command:

```bash
# Gigabyte / ITE chips
yay -S it87-dkms-git

# MSI / Nuvoton NCT6687D
yay -S nct6687d-dkms-git
```

#### Without an AUR helper

A plain Arch install has no AUR helper, and you do not need to install one. An AUR package is a build recipe (a `PKGBUILD`); `makepkg` turns it into an ordinary package and installs it with `pacman`. Run these as your normal user, not as root (`makepkg` refuses to run as root and asks for your password when it installs):

```bash
# Fetch the recipe, read it, then build and install it
git clone https://aur.archlinux.org/it87-dkms-git.git
less it87-dkms-git/PKGBUILD
makepkg -si -D it87-dkms-git
```

For an MSI board, use `nct6687d-dkms-git` in place of `it87-dkms-git` on all three lines. `-s` installs what the build needs (including `dkms`) with `pacman`, and `-i` installs the finished package. The tools and kernel headers from Step 2 are still yours to install. Read the `PKGBUILD` before you build it: anyone can publish to the AUR, and the recipe runs on your machine. The [Arch wiki AUR page](https://wiki.archlinux.org/title/Arch_User_Repository) covers the process in full.

Both are `-git` packages: every install or rebuild builds the **current upstream snapshot**. The version number shown on the AUR page is stale `-git` metadata; what installs is upstream HEAD at build time.

### Debian and Ubuntu

```bash
# Gigabyte / ITE chips
git clone https://github.com/frankcrawford/it87
cd it87 && sudo ./dkms-install.sh
```

```bash
# MSI / Nuvoton NCT6687D: builds a .deb package of the driver and installs it
git clone https://github.com/Fred78290/nct6687d
cd nct6687d && make deb && sudo dpkg -i ../nct6687d-dkms_*.deb
```

`make deb` installs the Debian packaging tools it needs (`debhelper`, `dkms`, `dh-dkms`) itself. Keep the cloned folder: it is what you update the driver from.

### Fedora

```bash
# Gigabyte / ITE chips
git clone https://github.com/frankcrawford/it87
cd it87 && sudo ./dkms-install.sh
```

```bash
# MSI / Nuvoton NCT6687D
git clone https://github.com/Fred78290/nct6687d
cd nct6687d && make dkms/install
```

`make dkms/install` calls `sudo` itself, and removes an older install of the driver first. With [RPM Fusion](https://rpmfusion.org/) enabled you can build an akmods package instead: `make akmod` in the `nct6687d` folder (it installs `akmods` and `buildsys-build-rpmfusion`, which come from RPM Fusion). akmods signs with its own key; see [Secure Boot](#secure-boot-and-dkms-modules). Keep the cloned folder: it is what you update the driver from.

### Every distribution: the nct6687d driver needs two more lines

With the `nct6687d` driver, two more things before Step 4:

```bash
# Blacklist the in-kernel nct6683, and unload it if it is already bound
echo 'blacklist nct6683' | sudo tee /etc/modprobe.d/nct6683_blacklist.conf
sudo modprobe -r nct6683
# Load nct6687 at every boot: the daemon package's modules-load file does not list it
echo nct6687 | sudo tee /etc/modules-load.d/nct6687.conf
```

Both drivers can bind the same chip, which garbles readings and makes PWM writes fail, and the in-kernel one also names its device `nct6687` and publishes it read-only. The blacklist keeps it from loading automatically from the next boot; the `modprobe -r` removes it now (if that fails because the module is in use, reboot instead, then skip Step 4's `modprobe`). Without the modules-load file, `nct6687` loads only when you load it by hand, so the fans vanish at the first reboot.

### Updating the driver

A driver built from source picks up upstream fixes only when you rebuild it. That matters, because many historical workarounds are already fixed upstream (for the it87 driver: MMIO on by default since the 2026-03 builds, which also sidesteps the ACPI port conflict on the IT8688E, IT8689E, IT8696E and IT8698E). The it87 driver builds only on kernel **6.4 or newer** (since 2026-08-23), so it cannot build on the 6.1, 5.15 or 5.10 LTS kernels. If you installed the driver months ago and something misbehaves, **rebuilding it is the first remediation, not the last**.

From the folder you cloned in Step 3 (run these from the folder that holds it):

```bash
# Arch, AUR helper: reinstalling rebuilds it
yay -S it87-dkms-git

# Arch, without a helper (nct6687d-dkms-git likewise)
git -C it87-dkms-git pull
makepkg -sif -D it87-dkms-git

# Debian, Ubuntu and Fedora, it87: remove the old build before pulling, as upstream asks
cd it87 && sudo ./dkms-remove.sh && git pull && sudo ./dkms-install.sh
```

```bash
# Debian and Ubuntu, nct6687d
cd nct6687d && git pull && make deb && sudo dpkg -i ../nct6687d-dkms_*.deb
```

```bash
# Fedora, nct6687d
cd nct6687d && git pull && make dkms/install
```

On Arch, the `pull` updates the recipe; `makepkg` fetches the driver's latest source itself, and `-f` rebuilds even when nothing upstream has changed, which is what a reinstall needs. The `.deb` that `make deb` builds is versioned by its build time, so the `*` matches every build so far and `dpkg` installs the newest last.

### After a kernel update

DKMS builds the driver once for each kernel. If that build failed for a new kernel, or the new kernel's headers were not installed, the new kernel boots with its **own** `it87`. On most Gigabyte boards the kernel's own driver cannot drive the main chip, so fan headers disappear after the update. Ventulus spots it: the missing-chip warning says *The it87 driver loaded is the kernel's own*, and the Hardware page's Super-I/O row gives the commands below.

```bash
dkms status               # which kernels the driver is built and installed for
sudo dkms autoinstall     # build it for the running kernel (its headers must be installed)
sudo systemctl reboot
```

If `dkms status` shows the build failed, install the headers for the running kernel (Step 2) and run `sudo dkms autoinstall` again. Ventulus cannot check DKMS for you: the daemon is not allowed to read the DKMS tree, so these commands are yours to run.

### IT8689E: the kernel's own driver, from Linux 7.1

The IT8689E is the one Gigabyte primary chip the kernel's own `it87` drives, from **Linux 7.1**. Fedora 43 to 45, Arch and CachyOS ship 7.1 or later. Debian 13 (6.12) and Ubuntu 26.04 (7.0) do not, so there the out-of-tree driver is still needed. Ventulus reads the kernel you are running and marks the chip accordingly.

On 7.1 or later the out-of-tree driver is optional, but still worth it on most boards: only it publishes the board's Gigabyte layout ID, which [board header names](hardware-troubleshooting.md#board-header-names-from-the-it87-catalogue) need, and only it has the fix for boards where fan writes have no effect ([PR #128](https://github.com/frankcrawford/it87/pull/128)). Whichever driver you run, check a header with **Test PWM Control**.

### it87 v2.0 renames your chips

Builds of the it87 driver made on or after **2026-09-09** (the driver's v2.0 release,
[PR #132](https://github.com/frankcrawford/it87/pull/132)) name Gigabyte chips after the
board's own ID whenever the driver can read it: `it8696_a008090a` instead of `it8696`,
for example.

Ventulus strips that suffix where it reads the chip name, so every fan header, sensor
and voltage keeps its id, and the profiles, fan names, pump roles and cooling devices
that use them carry on working. The built-in header labels (such as the X870E AORUS
MASTER's `SYS_FAN5_PUMP`) still apply, and the dual-chip check on **System State**
still recognises both chips.

One thing does change: an `/etc/sensors.d` file written for the old name stops
matching. `sensors` matches the new name, so a block that starts `chip "it8696-*"` no
longer applies, in `sensors` or in Ventulus. Upstream's per-board configurations use the
new names, and Ventulus reads those.

> **Secondary-chip fan control on dual-Super-I/O Gigabyte boards is bound by board pairing, not fixed for the family.** Some boards work: the X870E AORUS ELITE X3D reports both chips and controls both. On others the secondary can be masked by an ITE eSPI→LPC bridge latched in configuration mode, measured on an X870E AORUS MASTER. **That is recoverable, but not the way you would guess**: reinstalling, `mmio=on` and `force_id` all change nothing. The latch is written by the `nct6775`/`w83627ehf` modules (or `sensors-detect`). Stop those, reboot, and if the chip is still missing, power down at the wall. Follow the ladder in [Hardware Troubleshooting → *Some of my fan headers are missing*](hardware-troubleshooting.md#some-of-my-fan-headers-are-missing--only-5-of-8-show-up).

## Step 4 — Load and verify

```bash
# Load the module now (no reboot needed the first time)
sudo modprobe it87        # Gigabyte/ITE
# or
sudo modprobe nct6687     # MSI

# Did it bind? Your chip name should now appear:
cat /sys/class/hwmon/hwmon*/name

# And lm_sensors should show fan RPMs / temperatures:
sensors
```

(`sensors` comes from the lm-sensors package. If the command is missing, install it: `sudo pacman -S lm_sensors` on Arch, `sudo apt install lm-sensors` on Debian and Ubuntu, `sudo dnf install lm_sensors` on Fedora.)

If `modprobe` fails with *Key was rejected by service*, or with *Operation not permitted* and a lockdown "unsigned module loading is restricted" line in the kernel log, your kernel is refusing the unsigned module. See [Secure Boot and DKMS modules](#secure-boot-and-dkms-modules) below.

Boot-time loading: `ventulusd` (every package format, and its tarball) ships `/etc/modules-load.d/ventulus.conf`, which loads `nct6775`, `it87`, `w83627ehf` and `drivetemp` at boot, so `it87` is handled. `nct6687` is not in it: the `/etc/modules-load.d/nct6687.conf` from Step 3 is what loads it.

Then verify end-to-end in the GUI:

1. **Restart the daemon** so it adopts the new chip's PWM headers: `sudo systemctl restart ventulusd`. (A **Rescan Hardware** click in the global footer page is enough when you only need the chip's *sensors*: fan-control headers are discovered at daemon startup only.)
2. Click **Rescan Hardware** in the global footer, then open **System State**. The **Hardware Registry** should show your chip as **BOUND** and the header count should match what the board physically has.
3. On the **Hardware** page, press **Test Control** on a *non-critical chassis fan* header's card (not CPU/pump). A **"PWM control is working correctly"** result is the finish line; [Fan Tests and Reports](fan-tests.md#test-pwm-control) explains the other results.
4. If the test reports the BIOS reverting control, go to Step 5.

## Secure Boot and DKMS modules

With UEFI **Secure Boot** enabled, the kernels of Debian, Ubuntu and Fedora load only modules signed by a key they trust (on Arch that depends on how you set up Secure Boot). An out-of-tree module is either unsigned or signed with a key the firmware does not know yet, so the install *builds* fine but the module is rejected at **load** time ([Ubuntu wiki: UEFI/SecureBoot/DKMS](https://wiki.ubuntu.com/UEFI/SecureBoot/DKMS)). That is a classic dead end, because `dkms status` says *installed* while `modprobe` fails with one of:

```text
modprobe: ERROR: could not insert 'it87': Key was rejected by service
modprobe: ERROR: could not insert 'it87': Required key not available
modprobe: ERROR: could not insert 'it87': Operation not permitted
Lockdown: modprobe: unsigned module loading is restricted
```

The first comes from module signature enforcement (`module.sig_enforce`), the third from kernel lockdown, with the last line in the kernel log beside it. Distributions turn one of them on when they boot with Secure Boot. Secure Boot alone refuses nothing: an Arch kernel loads unsigned modules with it on.

**Ventulus checks this for you.** The readiness report (**System State** → **Open Full Report**) has a **Module signing** line: Secure Boot, the lockdown level, `module.sig_enforce`, and whether this kernel refuses unsigned drivers. When it does, and a driver your board needs is not loaded, the missing-chip warning and the Hardware page's driver advice say so.

(The "Key was rejected by service" wording in the wild: [Arch forums thread](https://bbs.archlinux.org/viewtopic.php?id=283289). That case was an NVIDIA module, but the kernel emits the same error for any unsigned module.)

Check whether Secure Boot is the cause:

```bash
bootctl status | grep -i "secure boot"   # systemd tool, present on every Arch/CachyOS install
# or
mokutil --sb-state                       # needs the mokutil package
# What actually refuses: [integrity] or [confidentiality] here, or Y below, means signed only
cat /sys/kernel/security/lockdown
cat /sys/module/module/parameters/sig_enforce
```

**On Debian, Ubuntu and Fedora,** DKMS signs the driver as it builds it, and prints the certificate it used (`Public certificate (MOK): …`): `/var/lib/dkms/mok.pub`, or `/var/lib/shim-signed/mok/MOK.der` on Ubuntu. Enroll that file once, then reboot:

```bash
sudo mokutil --import /var/lib/dkms/mok.pub
sudo systemctl reboot
```

(Use the path DKMS printed, if it differs.) `mokutil` asks you to choose a one-time password. As the machine restarts, a blue **MOK Manager** screen appears: choose **Enroll MOK**, confirm, and enter that password. From then on the kernel trusts every module DKMS signs with that key, including the rebuilds after each kernel update. On Fedora with the akmods build instead (`make akmod`), akmods signs with its own key: run `sudo kmodgenca -a`, then enroll `/etc/pki/akmods/certs/public_key.der` the same way.

**On Arch and CachyOS,** or if you would rather not enroll a key, there are two ways out. Read the trade-offs before you pick one:

1. **Disable Secure Boot in firmware setup** (the straightforward path, and the first remediation most distro documentation lists for unsigned modules): reboot into UEFI setup and disable Secure Boot, usually under *Boot* or *Security*. Understand what you are trading away first:
   - Secure Boot exists to block tampered boot components, so disabling it **reduces boot-chain security**.
   - **Dual-booting Windows with BitLocker?** Toggling Secure Boot can make BitLocker demand its **recovery key** on the next Windows boot. [Have your recovery key ready](https://support.microsoft.com/en-us/windows/find-your-bitlocker-recovery-key-6b71ad27-0b89-ea08-f143-056f5ab347d6) *before* changing the setting.
2. **Sign the modules (advanced):** DKMS can automatically sign every module it builds: set `mok_signing_key` / `mok_certificate` in `/etc/dkms/framework.conf` ([dkms README](https://github.com/dkms-project/dkms)) and enroll the certificate with your firmware. Enrollment mechanics (sbctl-managed keys, or shim + `mokutil`) are distribution-specific, so follow [Arch Wiki: Signed kernel modules](https://wiki.archlinux.org/title/Signed_kernel_modules) and, on CachyOS, the [CachyOS Secure Boot guide](https://wiki.cachyos.org/configuration/secure_boot_setup/).

> **CachyOS caveat (re-checked 2026-08-23, still current):** `linux-cachyos` kernels are built with IMA disabled, which prevents MOK certificates from being trusted for module signing: **MOK-signed DKMS modules fail to load even after correct enrollment**. [linux-cachyos #862](https://github.com/CachyOS/linux-cachyos/issues/862) remains **open** (never closed since it was filed in May 2026) and its fix, [PR #863](https://github.com/CachyOS/linux-cachyos/pull/863), remains **open and unmerged**, though it is still active (last touched 2026-08-16). Note the fix *has* landed for the Fedora COPR packaging; it is the **Arch** PKGBUILD, which is what CachyOS ships here, that has not taken it. Until it does, **disabling Secure Boot is the only reliable way** to run these drivers on CachyOS kernels.

## Step 5 — BIOS settings (the half people skip)

A correctly-installed, current driver usually takes each header over from the BIOS on its own. What the BIOS keeps is the fans at boot and whenever the daemon is not controlling them. That leaves one rule for everyone, and the rest is per vendor:

- **Every vendor:** never give a BIOS fan curve a **0% point**. The BIOS curve runs the fans at boot, and whenever the daemon is not controlling them, so a 0% point means stopped fans (pump and CPU fan included) in exactly those moments.
- **Gigabyte (Smart Fan 5/6):** a current it87 driver build usually needs **no BIOS change at all**. For a 4-pin fan, set the header's **FAN Control Mode** to **PWM**. Leave **Fan Speed Control** on a normal curve. *Full Speed* is a fail-safe, not a fix: the firmware runs that fan at 100% whenever it owns it, but on some boards it also locks Linux out of the header ([issue #115](https://github.com/frankcrawford/it87/issues/115)). On IT8689E **Rev 1** boards (e.g. X670E AORUS MASTER), **update the it87 driver first**. The fix in [PR #128](https://github.com/frankcrawford/it87/pull/128) merged on 2026-08-24, and three users reported working IT8689E control the day before, including on **Rev 1** (a Z790 AORUS MASTER, with fan speed measurably tracking duty). More boards have reported working since, some with **no BIOS changes at all**. So update, then **verify with Test PWM Control** rather than assuming. Only on a build older than 2026-08-24 did the driver need the fork's old BIOS stopgap: PWM 40,40,40,40,40,40,100 at temperatures 0,90,90,90,90,90,90, lowering 90 to your BIOS maximum ([issue #96](https://github.com/frankcrawford/it87/issues/96)). Even that only reliably restored the CPU-fan header. ([PR #114](https://github.com/frankcrawford/it87/pull/114), an earlier candidate fix, was rejected on 2026-08-25.)
- **MSI:** no BIOS setting makes the headers writable. If every header reads as read-only, the in-kernel `nct6683` is bound instead of `nct6687d`. Blacklist it (see Step 3). The **Hardware Registry** shows which one is bound: `nct6683 bound (mainline kernel)` is the read-only driver. On B840/B850/B860/X870/X870E/Z890 boards, system fans that ignore writes need the driver options in the table below, not a BIOS change. For 3-pin fans, set the header's fan type to DC.
- **ASUS:** no BIOS setting unlocks the headers either: under `nct6775` they are always writable, and the daemon switches each one to manual itself. In *Q-Fan Control*, match each header's mode to the fan (**DC Mode** for 3-pin, **PWM Mode** for 4-pin). *Q-Fan Tuning* is a one-shot calibration, not a mode switch. On some 800-series boards the firmware has been measured taking a header straight back from manual mode; run **Test PWM Control** to see whether yours does.
- **ASRock:** headers on the NCT67xx chip are always writable under `nct6775`. Headers on an NCT6686D/NCT6683D are read-only in the kernel driver whatever the BIOS says, and need an out-of-tree driver. Set each header's fan type to match the fan (DC for 3-pin, PWM for 4-pin).

## Module parameters you may actually need

Most users on current driver builds need **none** of these. The exceptions, all persisted via a file in `/etc/modprobe.d/` (e.g. `it87.conf`):

| Situation | Parameter | Source |
|---|---|---|
| Dual-chip Gigabyte board, **old (pre-2026-03)** it87 build, secondary chip missing | `options it87 mmio=on` | [issue #70](https://github.com/frankcrawford/it87/issues/70). Current builds default this on; update the driver instead. **On a current build, a missing secondary is not a parameter problem**: it is a blocked Super-I/O that needs `nct6775`/`w83627ehf` kept away, a reboot and, if that is not enough, a full power cut. See [Hardware Troubleshooting](hardware-troubleshooting.md#some-of-my-fan-headers-are-missing--only-5-of-8-show-up) |
| Intel **Z890 / B860** Gigabyte board, it87 build from **2026-09-09 to 2026-10-01**: `modprobe it87` fails with *Invalid argument* after an *H2RAM set_slot … failed* line, or a *Found IT8696E* line with no chip appearing | none: rebuild the it87 driver | Fixed upstream on 2026-10-02 ([PR #140](https://github.com/frankcrawford/it87/pull/140); [#139](https://github.com/frankcrawford/it87/issues/139), [#138](https://github.com/frankcrawford/it87/issues/138)). If you cannot rebuild, `options it87 mmio=off` (plus `ignore_resource_conflict=1` if the bind is then refused) lets it load, but the IT87952E loses its extra headers (SYS_FAN7/8_PUMP on the Z890 AORUS MASTER). Remove the option once updated |
| **IT8665E** board (ASUS AM4 300/400-series such as the PRIME X470-PRO, and X399-era boards like the ROG Zenith Extreme): PWM writes garbled on **builds predating 2026-07-22 only** | `options it87 mmio=off` | [issue #106](https://github.com/frankcrawford/it87/issues/106) is **closed, fixed upstream by [PR #120](https://github.com/frankcrawford/it87/pull/120) (merged 2026-07-22), which removed MMIO for this chip in the driver.** On a current build no parameter is needed; update the driver instead |
| `modprobe it87` fails with *Device or resource busy* (ACPI conflict, e.g. B650 GAMING X AX V2, the X399 AORUS boards) | `options it87 ignore_resource_conflict=1` | [issue #92](https://github.com/frankcrawford/it87/issues/92); X399: [PR #135](https://github.com/frankcrawford/it87/pull/135), [PR #141](https://github.com/frankcrawford/it87/pull/141). Prefer this driver-local option over the system-wide `acpi_enforce_resources=lax` |
| MSI **B840/B850/B860/X870/X870E/Z890** board (it uses the alternate "msi_alt1" register map, and monitoring tools call these boards *NCT6687DR*) whose system fans ignore writes and which is **not** on the driver's auto-allowlist | `options nct6687 fan_config=msi_alt1` | [Fred78290/nct6687d](https://github.com/Fred78290/nct6687d). See the warning below |
| `modprobe nct6687` fails with *Device or resource busy* (ACPI conflict) | `acpi_enforce_resources=lax` **as a kernel parameter** | `nct6687` and `nct6775` expose **no** driver-local `ignore_resource_conflict` equivalent, so unlike it87 the system-wide parameter is the only kernel-side remedy. Use it deliberately |
| Boot log shows *"nct6687: EC base I/O port unconfigured"* or `modprobe` fails with *No such device* | `softdep nct6687 pre: i2c_i801` in `/etc/modprobe.d/nct6687.conf` | upstream README: the EC is not addressable until the SMBus driver has loaded |
| MSI B840/B850/B860/X870/X870E/Z890 system fans accept PWM writes but do not change speed, or writes fail with an I/O error (EIO) | `options nct6687 msi_fan_brute_force=1` **plus** `blacklist nct6683` | upstream marks this BETA and requires the blacklist; without it `nct6683` can bind the same chip and writes fail. It writes the duty into all 7 BIOS curve points (the original curve is saved and restored), for system fans only |

> **Do not force `fan_config=msi_alt1` on an MSI board outside the B840/B850/B860/X870/X870E/Z890 series.** B650, B660, X670, Z690 and Z790 boards use the *default* register mapping and are auto-detected correctly. The chip is the same NCT6687D; only the EC's register layout differs. Forcing alt1 there makes the driver read EC offsets that read zero on those boards, so **every system fan reports 0 RPM** while the CPU fan keeps working. Check which mapping is active with `sudo dmesg | grep 'active fan config'`. That line will also reveal a setting left behind from an earlier attempt.
>
> **Never load `nct6687` with `force=1` on a board whose chip is an NCT679x** (MSI AM4 300/400-series and the original X570 boards). Since [nct6687d PR #174](https://github.com/Fred78290/nct6687d/pull/174), `force=1` attaches to any Nuvoton chip ID from 0xD000 to 0xDFFF. That reopens the chip-ID collision that has bricked a CPU fan header.

Two warnings: never use the it87 `force_id` parameter outside testing (upstream: *"should only be used for testing"*), and never run `sensors-detect` after boot on a Gigabyte board. It can wedge the Super-I/O bridge so a second chip vanishes (the package's guard cannot stop it), and a reboot may not bring it back. Power down at the wall, because the bridge keeps standby power. The recovery is in [Hardware Troubleshooting](hardware-troubleshooting.md#some-of-my-fan-headers-are-missing--only-5-of-8-show-up).

There is also nothing to gain by running it on these boards. As of 2026-08-26 `sensors-detect` has **no entry for device IDs 0x8688, 0x8689, 0x8696 or 0x8698**, so it cannot identify an IT8688E, IT8689E, IT8696E or IT8698E (the primary chip on essentially every modern Gigabyte board), and it has no NCT6686D entry either. On exactly the boards where running it can do harm, it has nothing useful to tell you.

## Rollback — undoing everything

Every change above is reversible:

```bash
# 1. Unload the module
sudo modprobe -r it87          # or: nct6687

# 2. Remove the driver (DKMS uninstalls the module from all kernels). Arch:
sudo pacman -R it87-dkms-git   # or: nct6687d-dkms-git
#    Debian, Ubuntu and Fedora, it87, from the folder you cloned:
#      cd it87 && sudo ./dkms-remove.sh
#    Debian and Ubuntu, nct6687d: sudo apt remove nct6687d-dkms
#    Fedora, nct6687d: cd nct6687d && make dkms/remove   (akmods build: make akmod/remove)

# 3. Remove any module-parameter, blacklist and load files you created
sudo rm -f /etc/modprobe.d/it87.conf /etc/modprobe.d/nct6687.conf \
  /etc/modprobe.d/nct6683_blacklist.conf /etc/modules-load.d/nct6687.conf \
  /etc/modprobe.d/it87-debug.conf

# 4. Reboot to return to the clean pre-driver state
sudo systemctl reboot
```

If you created `/etc/modprobe.d/ventulus-superio-local.conf` while [recovering a missing chip](hardware-troubleshooting.md#some-of-my-fan-headers-are-missing--only-5-of-8-show-up), leave it unless you are sure the package's guard covers your board (`sudo journalctl -b -t ventulus-superio-guard` shows a line per module it declined): removing it lets `nct6775` and `w83627ehf` probe again. BIOS changes are rolled back in BIOS setup (restore Smart Fan / Q-Fan to its default profile). If you use snapshots (e.g. `snapper` / Timeshift on CachyOS), taking one before Step 3 gives you a one-command rollback as well.

## Staying current

- **Kernel updates:** DKMS rebuilds the module automatically when a new kernel + matching headers are installed. If fans disappear right after a kernel update, the usual cause is missing/mismatched headers, so re-check Step 2 (on Debian and Ubuntu, the headers metapackage it names).
- **Driver updates:** an out-of-tree driver picks up upstream fixes only when you *rebuild* it ([Updating the driver](#updating-the-driver)). Do this before troubleshooting any fan-control regression. On a Gigabyte board, a build from 2026-09-09 on renames your chips, which changes nothing in Ventulus: see [it87 v2.0 renames your chips](#it87-v20-renames-your-chips). On an Intel Z890 / B860 Gigabyte board, builds from 2026-09-09 to 2026-10-01 can fail to load; rebuild (see [Module parameters you may actually need](#module-parameters-you-may-actually-need)). (If a current build *fails to compile*, see upstream [issue #108](https://github.com/frankcrawford/it87/issues/108) for a known `-Werror=unused-function` toolchain failure.)

## AMD GPU fan control prerequisite (RDNA3+)

The rest of this page is about motherboard headers; AMD GPU fan control has exactly one prerequisite of its own. RDNA3 and newer cards (RX 7000 / RX 9000 series) only accept fan-curve writes through the PMFW interface, which the kernel locks behind an *overdrive* feature bit. Pre-RDNA3 cards (RX 6000 and older) need none of this.

Check first, either in the GPU row of the **Safety & GPU Limits** card (on the **System State** page), which says whether the bit is set, or from a terminal:

```bash
cat /sys/module/amdgpu/parameters/ppfeaturemask
```

If bit 14 (`0x4000`, `PP_OVERDRIVE_MASK` in the [kernel amdgpu module-parameters documentation](https://docs.kernel.org/gpu/amdgpu/module-parameters.html)) is not set, add this to the kernel command line:

```text
amdgpu.ppfeaturemask=0xfff7ffff
```

That is the kernel's default mask with bit 14 added, the value AMD's engineers give ([drm/amd #5514](https://gitlab.freedesktop.org/drm/amd/-/issues/5514)). Any mask with bit 14 set works, so if you already use `0xffffffff` (common in older guides) you can leave it; it also turns on one feature the kernel leaves off by default, which RX 7000 and RX 9000 cards do not use. If you have already changed the mask for another reason, add `0x4000` to your own value instead, as [CoolerControl documents](https://docs.coolercontrol.org/hardware-support.html). Background: [Hardware Compatibility § ppfeaturemask](../docs/19_Hardware_Compatibility.md#ppfeaturemask).

From Linux 6.13 the kernel logs `amdgpu: Overdrive is enabled, please disable it before reporting any bugs unrelated to overdrive.` at boot and marks itself *tainted* when this bit is set ([commit b472b8d829c1](https://git.kernel.org/torvalds/c/b472b8d829c1562c5597c1f212957b6b2696d40e)). That is expected and does not stop anything working. If you report a kernel bug, say that the parameter is set.

How to add a kernel parameter, per bootloader, with the same steps as `man ventulusd` (see also the [Arch Wiki](https://wiki.archlinux.org/title/Kernel_parameters) and, for Limine, the [CachyOS boot-manager guide](https://wiki.cachyos.org/configuration/boot_manager_configuration/)):

| Bootloader | Edit | Then run |
|---|---|---|
| **GRUB** (Arch) | append to `GRUB_CMDLINE_LINUX_DEFAULT` in `/etc/default/grub` | `sudo grub-mkconfig -o /boot/grub/grub.cfg` |
| **GRUB** (Debian, Ubuntu) | append to `GRUB_CMDLINE_LINUX_DEFAULT` in `/etc/default/grub` | `sudo update-grub` |
| **GRUB** (Fedora) | nothing: `grubby` edits every boot entry for you | `sudo grubby --update-kernel=ALL --args=amdgpu.ppfeaturemask=0xfff7ffff` |
| **systemd-boot** | append to the `options` line of the active entry under `/boot/loader/entries/` | — |
| **rEFInd** | append to the options in `/boot/refind_linux.conf` (or the kernel argument list in `refind.conf`) | — |
| **Limine** (as set up on CachyOS) | append to `KERNEL_CMDLINE` in `/etc/default/limine` | `sudo limine-mkinitcpio` |

On Debian and Ubuntu, a file under `/etc/default/grub.d/` that also sets `GRUB_CMDLINE_LINUX_DEFAULT` replaces the line in `/etc/default/grub`; `grep -r GRUB_CMDLINE_LINUX_DEFAULT /etc/default/` shows every place it is set.

Reboot, confirm the parameter took effect with `cat /proc/cmdline`, then run **Test GPU Fan Control** (on the **System State** page) to verify end-to-end. A wrong kernel command line can prevent the system from booting. The warning at the top of this page applies here in full.

## Where to go next

- [Setup Checklist](setup-checklist.md): the ordered end-to-end setup path this page slots into
- [Hardware Troubleshooting](hardware-troubleshooting.md): from a symptom to its fix, including the dual-chip warning
- [Fan Tests and Reports](fan-tests.md): what each fan test's result means
- [Hardware Compatibility](../docs/19_Hardware_Compatibility.md): full chip/driver matrix with sources
- [AMD Motherboard Fan Control Guide](../docs/21_AMD_Motherboard_Fan_Control_Guide.md) / [Intel Guide](../docs/23_Intel_Motherboard_Fan_Control_Guide.md): vendor-by-vendor depth

---

Previous: [Hardware Troubleshooting](hardware-troubleshooting.md) | Next: [Understanding Motherboard Fan Control](understanding-fan-control.md) | Back to [Table of Contents](README.md)
