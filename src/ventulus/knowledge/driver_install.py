"""How to install an out-of-tree Super-I/O driver, per distribution family (DEC-499).

Two fan-control drivers live outside the kernel: frankcrawford/it87 (ITE chips,
most Gigabyte boards) and Fred78290/nct6687d (MSI's NCT6687D). Guidance
everywhere else names them by those upstream projects. How to *install* one
depends on the distribution, and this module is the one place that knows.

AUR package names belong to the Arch branch here and nowhere else in the GUI
(``tests/test_driver_install.py`` pins both halves). Before DEC-499 every
guidance string said ``it87-dkms-git (AUR)``, a package a Debian or Fedora user
cannot install — DEC-239 made fixing that a precondition of any non-Arch package.

The family comes from os-release (``ID``, then ``ID_LIKE`` in order), read on the
GUI's own machine. The daemon is on the same machine (a local socket), so the
answer is the daemon's too and no wire field is needed. The family decides only
which commands are shown; nothing here runs anything.

Stdlib only, like the rest of ``knowledge/``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class InstallFamily(StrEnum):
    ARCH = "arch"
    DEBIAN = "debian"  # Debian, Ubuntu and their derivatives
    FEDORA = "fedora"
    OTHER = "other"  # anything else, and image-based systems


_FAMILY_LABELS: dict[InstallFamily, str] = {
    InstallFamily.ARCH: "Arch Linux",
    InstallFamily.DEBIAN: "Debian / Ubuntu",
    InstallFamily.FEDORA: "Fedora",
    InstallFamily.OTHER: "your distribution",
}

#: os-release ``ID`` / ``ID_LIKE`` tokens that name a family. CachyOS, Manjaro
#: and EndeavourOS say ``ID_LIKE=arch``; Mint and Pop!_OS say ``ubuntu``; RHEL
#: and its rebuilds list ``fedora``.
_FAMILY_BY_ID: dict[str, InstallFamily] = {
    "arch": InstallFamily.ARCH,
    "debian": InstallFamily.DEBIAN,
    "ubuntu": InstallFamily.DEBIAN,
    "fedora": InstallFamily.FEDORA,
}

#: os-release(5): ``/etc/os-release`` wins, ``/usr/lib/os-release`` is the fallback.
_OS_RELEASE_PATHS: tuple[Path, ...] = (Path("/etc/os-release"), Path("/usr/lib/os-release"))

#: Present on image-based systems (Fedora Atomic, Bazzite, …). Their ``/usr`` is
#: read-only, so neither ``dnf install`` nor DKMS works as written below; they get
#: the generic steps, which say so.
_OSTREE_MARKER = Path("/run/ostree-booted")


def family_label(family: InstallFamily) -> str:
    return _FAMILY_LABELS[family]


def parse_os_release(text: str) -> dict[str, str]:
    """``KEY=value`` pairs from os-release text, with one level of quotes removed."""
    fields: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        fields[key.strip()] = value
    return fields


def family_from_os_release(text: str) -> InstallFamily:
    """The family os-release text describes: ``ID`` first, then ``ID_LIKE`` in
    the order it lists them (closest first, per os-release(5))."""
    fields = parse_os_release(text)
    for token in (fields.get("ID", ""), *fields.get("ID_LIKE", "").split()):
        family = _FAMILY_BY_ID.get(token.lower())
        if family is not None:
            return family
    return InstallFamily.OTHER


def detect_install_family(
    paths: tuple[Path, ...] = _OS_RELEASE_PATHS, ostree_marker: Path = _OSTREE_MARKER
) -> InstallFamily:
    """Read this machine's family; ``OTHER`` when nothing can be read."""
    if ostree_marker.exists():
        return InstallFamily.OTHER
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        return family_from_os_release(text)
    return InstallFamily.OTHER


#: The process-wide answer. Detected on first use; `set_install_family` pins it
#: (tests start every test on ``OTHER``, see ``tests/conftest.py``).
_family: InstallFamily | None = None


def install_family() -> InstallFamily:
    """This machine's install family, detected once per process."""
    global _family
    if _family is None:
        _family = detect_install_family()
    return _family


def set_install_family(family: InstallFamily | None) -> None:
    """Pin the family, or pass ``None`` to detect it again on the next call."""
    global _family
    _family = family


@dataclass(frozen=True)
class OutOfTreeDriver:
    module: str  # the kernel module name, e.g. "it87"
    project: str  # upstream, as guidance names it
    url: str
    clone_dir: str  # the directory `git clone <url>` creates
    #: The kernel ships a module of the same name (mainline has an it87, but no
    #: nct6687), so a loaded module of this name may still be the in-kernel one.
    in_kernel_namesake: bool


OUT_OF_TREE_DRIVERS: dict[str, OutOfTreeDriver] = {
    "it87": OutOfTreeDriver(
        "it87", "frankcrawford/it87", "https://github.com/frankcrawford/it87", "it87", True
    ),
    "nct6687": OutOfTreeDriver(
        "nct6687",
        "Fred78290/nct6687d",
        "https://github.com/Fred78290/nct6687d",
        "nct6687d",
        False,
    ),
}


@dataclass(frozen=True)
class InstallGuide:
    """Copyable steps for one driver on one family. Every line is a shell
    command that also works in fish."""

    family: InstallFamily
    driver: OutOfTreeDriver
    install: tuple[str, ...]  # a first install, in order
    update: tuple[str, ...]  # bring an install made this way up to date
    after: tuple[str, ...] = ()  # once, after the first install
    install_notes: tuple[str, ...] = ()  # about the first install only
    notes: tuple[str, ...] = ()  # about installing and updating alike

    @property
    def title(self) -> str:
        return f"Install {self.driver.project} on {family_label(self.family)}"

    @property
    def install_text(self) -> str:
        return "\n".join((*self.install, *self.after))

    @property
    def update_text(self) -> str:
        return "\n".join(self.update)


# ── Arch: the AUR packages (the only place they are named) ──────────────────

_AUR_PACKAGES: dict[str, str] = {"it87": "it87-dkms-git", "nct6687": "nct6687d-dkms-git"}


def _arch_guide(driver: OutOfTreeDriver) -> InstallGuide:
    pkg = _AUR_PACKAGES[driver.module]
    return InstallGuide(
        family=InstallFamily.ARCH,
        driver=driver,
        install=(
            "sudo pacman -S --needed base-devel git dkms linux-headers",
            f"git clone https://aur.archlinux.org/{pkg}.git",
            f"makepkg -si -D {pkg}",
        ),
        update=(f"git -C {pkg} pull", f"makepkg -sif -D {pkg}"),
        after=_after_install(driver),
        install_notes=(
            *_after_install_notes(driver),
            "linux-headers matches the stock kernel: install the headers for the "
            "kernel you boot instead (linux-lts-headers, linux-cachyos-headers, …).",
        ),
        notes=(
            f"{pkg} is an AUR package. With an AUR helper it is one command, "
            f"yay -S {pkg}, and reinstalling it updates the driver.",
        ),
    )


def _arch_package_hint(driver: OutOfTreeDriver) -> str:
    return f"{_AUR_PACKAGES[driver.module]} (AUR)"


def _arch_update_hint(driver: OutOfTreeDriver) -> str:
    return f"reinstall the {_AUR_PACKAGES[driver.module]} AUR package"


# ── Every other family: upstream's own build, with DKMS ──────────────────────

_PREREQUISITES: dict[InstallFamily, str] = {
    InstallFamily.DEBIAN: "sudo apt install git build-essential dkms linux-headers-$(uname -r)",
    InstallFamily.FEDORA: "sudo dnf install git make gcc dkms kernel-devel-$(uname -r)",
}

# Measured on Debian 13 and Ubuntu 26.04 (2026-10-17): it87's dkms-install.sh
# builds for the running kernel only, so a kernel installed but not yet booted
# came up with the in-kernel it87. Debian's dkms hooks rebuild on a later kernel
# or headers install; nothing rebuilds at boot (Fedora's dkms.service does).
_DEBIAN_KERNEL_NOTE = (
    "Kernel updates: also install the headers metapackage (linux-headers-amd64 on "
    "Debian, linux-headers-generic on Ubuntu) so DKMS rebuilds the driver for every "
    "new kernel. If a kernel update is installed but not yet booted, reboot before "
    "you build: the build may cover only the kernel you are running. Fans gone after "
    "a reboot into a new kernel? 'sudo dkms autoinstall' builds the driver for it."
)

_OTHER_PREREQUISITES_NOTE = (
    "First install git, make, a C compiler, dkms and the headers for the kernel you "
    "are running; the package names depend on your distribution. On an image-based "
    "system (Fedora Atomic, Bazzite and the like) DKMS cannot install into /usr: "
    "follow your distribution's guidance for kernel modules instead."
)

# DKMS chooses the key in `prepare_mok` (dkms-project/dkms): Ubuntu's
# shim-signed MOK, else /var/lib/dkms/mok.pub, and prints the one it used.
_SECURE_BOOT_NOTE = (
    "Secure Boot: when 'mokutil --sb-state' says it is enabled, the kernel loads only "
    "signed modules, and an unsigned driver fails with 'Key was rejected by service'. "
    "DKMS signs the driver as it builds it and prints the certificate it used "
    "('Public certificate (MOK): …' — /var/lib/dkms/mok.pub, or "
    "/var/lib/shim-signed/mok/MOK.der on Ubuntu). Enrol that file once with "
    "'sudo mokutil --import <file>', choose a one-time password, reboot, and pick "
    "'Enroll MOK' in the blue MOK Manager screen."
)

# Fred78290/nct6687d's `make akmod` runs `dnf install akmods
# buildsys-build-rpmfusion`, and the second package exists only in RPM Fusion.
_AKMOD_NOTE = (
    "With RPM Fusion enabled you can build an akmods package instead: 'make akmod' in "
    "the nct6687d folder (it installs akmods and buildsys-build-rpmfusion, which come "
    "from RPM Fusion). akmods signs with its own key: run 'sudo kmodgenca -a', then "
    "'sudo mokutil --import /etc/pki/akmods/certs/public_key.der'."
)


def _after_install(driver: OutOfTreeDriver) -> tuple[str, ...]:
    """Steps every family needs once the module is installed. nct6687d's packages
    neither blacklist the in-kernel nct6683 (which binds the same chip read-only)
    nor load nct6687 at boot; the daemon package's modules-load file covers it87."""
    if driver.module != "nct6687":
        return ()
    return (
        "echo 'blacklist nct6683' | sudo tee /etc/modprobe.d/nct6683_blacklist.conf",
        "echo nct6687 | sudo tee /etc/modules-load.d/nct6687.conf",
    )


def _after_install_notes(driver: OutOfTreeDriver) -> tuple[str, ...]:
    if driver.module != "nct6687":
        return ()
    return (
        "The last two lines keep the in-kernel nct6683 from binding the chip "
        "read-only and load nct6687 at every boot. Reboot afterwards.",
    )


def _upstream_steps(
    driver: OutOfTreeDriver, family: InstallFamily
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(build-and-install, update) for one family, from the upstream README."""
    d = driver.clone_dir
    if driver.module == "it87":
        # README: "run sudo ./dkms-remove.sh before updating local git repo.
        # Otherwise old module may not be removed." dkms-install.sh ends with
        # `modprobe it87`.
        return (
            (f"cd {d} && sudo ./dkms-install.sh",),
            (f"cd {d} && sudo ./dkms-remove.sh && git pull && sudo ./dkms-install.sh",),
        )
    if family is InstallFamily.DEBIAN:
        # `make deb` installs debhelper, dkms and dh-dkms itself. The package
        # version is a timestamp, so the glob installs the newest build last.
        deb = f"sudo dpkg -i ../{d}-dkms_*.deb"
        return (
            (f"cd {d} && make deb && {deb}",),
            (f"cd {d} && git pull && make deb && {deb}",),
        )
    # `make dkms/install` calls sudo itself and removes an older nct6687d/1 first.
    return ((f"cd {d} && make dkms/install",), (f"cd {d} && git pull && make dkms/install",))


def install_guide(module: str, family: InstallFamily | None = None) -> InstallGuide | None:
    """Install steps for an out-of-tree *module* on *family* (default: this
    machine's), or ``None`` for a module that needs no out-of-tree driver."""
    driver = OUT_OF_TREE_DRIVERS.get(module)
    if driver is None:
        return None
    family = install_family() if family is None else family
    if family is InstallFamily.ARCH:
        return _arch_guide(driver)
    build, update = _upstream_steps(driver, family)
    prerequisite = _PREREQUISITES.get(family)
    install_notes: list[str] = [*_after_install_notes(driver)]
    if not prerequisite:
        install_notes.insert(0, _OTHER_PREREQUISITES_NOTE)
    if family is InstallFamily.DEBIAN:
        install_notes.append(_DEBIAN_KERNEL_NOTE)
    if family is InstallFamily.FEDORA and driver.module == "nct6687":
        install_notes.append(_AKMOD_NOTE)
    return InstallGuide(
        family=family,
        driver=driver,
        install=(
            *((prerequisite,) if prerequisite else ()),
            f"git clone {driver.url}",
            *build,
        ),
        update=update,
        after=_after_install(driver),
        install_notes=tuple(install_notes),
        notes=(_SECURE_BOOT_NOTE,),
    )


def package_hint(module: str, family: InstallFamily | None = None) -> str:
    """What to install, as a phrase that reads after "install …"."""
    driver = OUT_OF_TREE_DRIVERS.get(module)
    if driver is None:
        return f"the out-of-tree {module} driver"
    family = install_family() if family is None else family
    if family is InstallFamily.ARCH:
        return _arch_package_hint(driver)
    return f"the {driver.project} driver (DKMS)"


def update_hint(module: str, family: InstallFamily | None = None) -> str:
    """How to bring an installed driver up to date, as a short imperative phrase."""
    driver = OUT_OF_TREE_DRIVERS.get(module)
    if driver is None:
        return f"rebuild the out-of-tree {module} driver from current source"
    family = install_family() if family is None else family
    if family is InstallFamily.ARCH:
        return _arch_update_hint(driver)
    return f"rebuild {driver.project} from its current source"
