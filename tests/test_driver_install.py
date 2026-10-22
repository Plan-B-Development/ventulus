"""DEC-499 phase 1 (`XD-1`): driver guidance that is right on every distribution.

Out-of-tree drivers are named by upstream project everywhere; install steps are
chosen by the machine's distribution family, read from os-release; AUR package
names appear only in the Arch branch of `knowledge/driver_install.py`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ventulus.api.models import (
    BoardInfo,
    HardwareDiagnosticsResult,
    HwmonChipInfo,
    HwmonDiagnostics,
    KernelModuleInfo,
    SuperIoChip,
    SuperIoRecommendation,
    SuperIoReport,
    ThermalSafetyInfo,
)
from ventulus.knowledge import driver_install
from ventulus.knowledge.driver_install import (
    OUT_OF_TREE_DRIVERS,
    InstallFamily,
    detect_install_family,
    family_from_os_release,
    install_family,
    install_guide,
    package_hint,
    set_install_family,
    update_hint,
)
from ventulus.services.duty_drift import NO_DRIFT
from ventulus.services.hardware_view import build_superio_panel
from ventulus.ui.hwmon_guidance import dual_chip_warning_html, format_driver_status
from ventulus.ui.widgets.readiness_report import detect_readiness_problems

#: What an AUR reference looks like: a `-dkms-git` package or the word itself.
_AUR = re.compile(r"-dkms-git|\bAUR\b")
_NON_ARCH = (InstallFamily.DEBIAN, InstallFamily.FEDORA, InstallFamily.OTHER)
_SRC = Path(__file__).resolve().parent.parent / "src" / "ventulus"


def _guide_text(guide) -> str:
    return "\n".join(
        (
            guide.title,
            *guide.install,
            *guide.update,
            *guide.after,
            *guide.install_notes,
            *guide.notes,
        )
    )


# ── Family detection ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("text", "family"),
    [
        ('NAME="Arch Linux"\nID=arch\n', InstallFamily.ARCH),
        ('ID=cachyos\nID_LIKE="arch"\n', InstallFamily.ARCH),
        ("ID=manjaro\nID_LIKE=arch\n", InstallFamily.ARCH),
        ('ID=debian\nVERSION_ID="13"\n', InstallFamily.DEBIAN),
        ("ID=ubuntu\nID_LIKE=debian\n", InstallFamily.DEBIAN),
        ('ID=linuxmint\nID_LIKE="ubuntu debian"\n', InstallFamily.DEBIAN),
        ("ID=fedora\nVERSION_ID=44\n", InstallFamily.FEDORA),
        ("ID='almalinux'\nID_LIKE='rhel centos fedora'\n", InstallFamily.FEDORA),
        ('ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n', InstallFamily.OTHER),
        ("ID=gentoo\n", InstallFamily.OTHER),
        ("# no fields at all\n", InstallFamily.OTHER),
        ("", InstallFamily.OTHER),
    ],
)
def test_family_from_os_release(text, family):
    assert family_from_os_release(text) is family


def test_id_wins_over_id_like():
    # A distribution names its closest relative first; its own ID is closer still.
    assert family_from_os_release("ID=ubuntu\nID_LIKE=arch\n") is InstallFamily.DEBIAN


def test_detect_reads_etc_first_then_usr_lib(tmp_path):
    etc, usr = tmp_path / "etc-os-release", tmp_path / "usr-os-release"
    no_ostree = tmp_path / "ostree-booted"
    usr.write_text("ID=fedora\n")
    assert detect_install_family((etc, usr), no_ostree) is InstallFamily.FEDORA
    etc.write_text("ID=debian\n")
    assert detect_install_family((etc, usr), no_ostree) is InstallFamily.DEBIAN


def test_detect_without_os_release_is_other(tmp_path):
    missing = (tmp_path / "a", tmp_path / "b")
    assert detect_install_family(missing, tmp_path / "ostree-booted") is InstallFamily.OTHER


def test_image_based_system_gets_the_generic_steps(tmp_path):
    os_release = tmp_path / "os-release"
    os_release.write_text('ID=bazzite\nID_LIKE="fedora"\n')
    marker = tmp_path / "ostree-booted"
    assert detect_install_family((os_release,), marker) is InstallFamily.FEDORA
    marker.touch()
    assert detect_install_family((os_release,), marker) is InstallFamily.OTHER


def test_family_is_detected_once_and_can_be_reset(monkeypatch):
    calls: list[int] = []

    def fake_detect():
        calls.append(1)
        return InstallFamily.FEDORA

    monkeypatch.setattr(driver_install, "detect_install_family", fake_detect)
    set_install_family(None)
    assert install_family() is InstallFamily.FEDORA
    assert install_family() is InstallFamily.FEDORA
    assert calls == [1]
    set_install_family(InstallFamily.ARCH)
    assert install_family() is InstallFamily.ARCH
    assert calls == [1]


# ── AUR names live in the Arch branch only ──────────────────────────────────


@pytest.mark.parametrize("module", sorted(OUT_OF_TREE_DRIVERS))
def test_arch_branch_names_the_aur_package(module):
    guide = install_guide(module, InstallFamily.ARCH)
    assert guide is not None
    assert _AUR.search(_guide_text(guide))
    assert "(AUR)" in package_hint(module, InstallFamily.ARCH)
    assert _AUR.search(update_hint(module, InstallFamily.ARCH))


@pytest.mark.parametrize("family", _NON_ARCH)
@pytest.mark.parametrize("module", sorted(OUT_OF_TREE_DRIVERS))
def test_no_aur_name_outside_the_arch_branch(module, family):
    guide = install_guide(module, family)
    assert guide is not None
    project = OUT_OF_TREE_DRIVERS[module].project
    for text in (_guide_text(guide), package_hint(module, family), update_hint(module, family)):
        assert project in text or OUT_OF_TREE_DRIVERS[module].url in text
        assert not _AUR.search(text), text


def test_no_gui_source_names_an_aur_package_outside_driver_install():
    """The sweep half: guidance text anywhere else in the GUI is static, so the
    source is the population. Enumerated, not listed, so a new module is covered."""
    files = sorted(_SRC.rglob("*.py"))
    assert len(files) > 100  # precondition: the walk found the package
    offenders = [
        f"{path.relative_to(_SRC)}:{n}"
        for path in files
        if path.name != "driver_install.py"
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if _AUR.search(line)
    ]
    assert offenders == []


# ── Steps per family ────────────────────────────────────────────────────────


def test_it87_uses_upstreams_dkms_script_off_arch():
    for family in _NON_ARCH:
        guide = install_guide("it87", family)
        assert guide.install[-1] == "cd it87 && sudo ./dkms-install.sh"
        assert "git clone https://github.com/frankcrawford/it87" in guide.install
        # Upstream: remove before pulling, or the old module may not be removed.
        update = guide.update_text
        assert update.index("dkms-remove.sh") < update.index("git pull")
        assert update.index("git pull") < update.index("dkms-install.sh")
        assert guide.after == ()


def test_prerequisites_follow_the_family():
    assert install_guide("it87", InstallFamily.DEBIAN).install[0].startswith("sudo apt install")
    assert install_guide("it87", InstallFamily.FEDORA).install[0].startswith("sudo dnf install")
    other = install_guide("it87", InstallFamily.OTHER)
    assert other.install[0].startswith("git clone")
    assert any("package names depend on your distribution" in n for n in other.install_notes)


@pytest.mark.parametrize("module", sorted(OUT_OF_TREE_DRIVERS))
def test_debian_family_is_told_how_the_driver_follows_kernel_updates(module):
    # A real Ubuntu 26.04 install booted a pending kernel without the it87 build.
    notes = " ".join(install_guide(module, InstallFamily.DEBIAN).install_notes)
    assert "linux-headers-amd64" in notes
    assert "linux-headers-generic" in notes
    assert "sudo dkms autoinstall" in notes
    # The note is the Debian family's alone (Fedora's dkms.service rebuilds at boot).
    for family in (InstallFamily.FEDORA, InstallFamily.ARCH, InstallFamily.OTHER):
        guide = install_guide(module, family)
        assert not any("dkms autoinstall" in n for n in (*guide.install_notes, *guide.notes))


def test_nct6687_debian_builds_upstreams_deb():
    guide = install_guide("nct6687", InstallFamily.DEBIAN)
    assert "make deb" in guide.install[-1]
    assert "dpkg -i ../nct6687d-dkms_*.deb" in guide.install[-1]


def test_nct6687_fedora_leads_with_dkms_and_offers_akmod():
    guide = install_guide("nct6687", InstallFamily.FEDORA)
    assert guide.install[-1] == "cd nct6687d && make dkms/install"
    akmod = [n for n in guide.install_notes if "make akmod" in n]
    assert len(akmod) == 1
    assert "RPM Fusion" in akmod[0]
    assert "kmodgenca" in akmod[0]
    assert "/etc/pki/akmods/certs/public_key.der" in akmod[0]
    # The akmod alternative is nct6687d's, and Fedora's only.
    it87 = install_guide("it87", InstallFamily.FEDORA)
    debian = install_guide("nct6687", InstallFamily.DEBIAN)
    assert not any("akmod" in n for n in (*it87.install_notes, *it87.notes))
    assert not any("akmod" in n for n in (*debian.install_notes, *debian.notes))


@pytest.mark.parametrize("family", list(InstallFamily))
def test_nct6687_blacklists_nct6683_and_loads_at_boot_everywhere(family):
    guide = install_guide("nct6687", family)
    assert any("blacklist nct6683" in line for line in guide.after)
    assert any("/etc/modules-load.d/nct6687.conf" in line for line in guide.after)
    assert guide.install_text.endswith("\n".join(guide.after))
    assert not any("reboot" in line for line in guide.after), "pasting must not reboot"


def test_secure_boot_note_on_every_non_arch_family():
    for family in _NON_ARCH:
        for module in OUT_OF_TREE_DRIVERS:
            notes = " ".join(install_guide(module, family).notes)
            assert "Secure Boot" in notes
            assert "mokutil --import" in notes
            assert "/var/lib/dkms/mok.pub" in notes
            assert "/var/lib/shim-signed/mok/MOK.der" in notes
    # Arch kernels do not tie module signing to Secure Boot; no note there.
    assert not any("Secure Boot" in n for n in install_guide("it87", InstallFamily.ARCH).notes)


def test_in_kernel_module_has_no_guide():
    assert install_guide("nct6775", InstallFamily.DEBIAN) is None
    assert package_hint("nct6775", InstallFamily.ARCH) == "the out-of-tree nct6775 driver"


def test_default_family_is_this_process():
    set_install_family(InstallFamily.FEDORA)
    assert install_guide("it87").family is InstallFamily.FEDORA
    assert package_hint("it87") == package_hint("it87", InstallFamily.FEDORA)


# ── Wiring: every surface that tells the user to install or update ─────────


def test_driver_status_line_follows_the_family():
    set_install_family(InstallFamily.ARCH)
    assert format_driver_status("it8688", loaded=False) == (
        "it87 not loaded — install it87-dkms-git (AUR)"
    )
    set_install_family(InstallFamily.DEBIAN)
    debian = format_driver_status("it8688", loaded=False)
    assert debian == "it87 not loaded — install the frankcrawford/it87 driver (DKMS)"
    assert format_driver_status("nct6687", loaded=True) == (
        "nct6687 loaded (out-of-tree: Fred78290/nct6687d)"
    )


def test_dual_chip_warning_follows_the_family():
    args = ("X870E AORUS MASTER", ["it8696", "it87952"], ["it8696"])
    set_install_family(InstallFamily.ARCH)
    arch = dual_chip_warning_html(*args)
    assert "it87-dkms-git" in arch
    set_install_family(InstallFamily.FEDORA)
    fedora = dual_chip_warning_html(*args)
    assert "frankcrawford/it87" in fedora
    assert not _AUR.search(fedora)


def _diag(**kw) -> HardwareDiagnosticsResult:
    return HardwareDiagnosticsResult(
        hwmon=HwmonDiagnostics(
            chips_detected=[HwmonChipInfo(chip_name="it8696", header_count=5)],
            total_headers=5,
            writable_headers=5,
            enable_revert_counts={"hwmon:it8696:x:pwm1": 3},
        ),
        board=BoardInfo(vendor="Gigabyte Technology Co., Ltd.", name="X870E AORUS MASTER"),
        kernel_modules=[KernelModuleInfo(name="it87", loaded=True, in_mainline=False)],
        thermal_safety=ThermalSafetyInfo(state="normal", cpu_sensor_found=True),
        expected_chips=["it8696", "it87952"],
        **kw,
    )


def test_readiness_fixes_follow_the_family():
    set_install_family(InstallFamily.ARCH)
    arch = {p["key"]: p["fix"] for p in detect_readiness_problems(_diag(), duty_drift=NO_DRIFT)}
    set_install_family(InstallFamily.DEBIAN)
    deb = {p["key"]: p["fix"] for p in detect_readiness_problems(_diag(), duty_drift=NO_DRIFT)}
    assert {"dual_chip", "bios_revert"} <= arch.keys()
    for key in ("dual_chip", "bios_revert"):
        assert "it87-dkms-git" in arch[key], key
        assert "frankcrawford/it87" in deb[key], key
        assert not _AUR.search(deb[key]), key


def _chip(module: str, in_mainline: bool, **kw) -> SuperIoChip:
    return SuperIoChip(
        chip_name="it8696" if module == "it87" else "nct6687",
        vendor="ite" if module == "it87" else "nuvoton",
        expected_module=module,
        hwmon_present=False,
        recommendation=SuperIoRecommendation(
            module=module, in_mainline=in_mainline, load_hint="prose", reason="r"
        ),
        **kw,
    )


def _row(module: str, *, in_mainline: bool = False, module_loaded: bool = False):
    chip = _chip(module, in_mainline=in_mainline, module_loaded=module_loaded)
    return build_superio_panel(SuperIoReport(arch_supported=True, chips=[chip])).rows[0]


def test_hardware_row_carries_this_familys_steps():
    set_install_family(InstallFamily.FEDORA)
    row = _row("nct6687")
    guide = install_guide("nct6687", InstallFamily.FEDORA)
    assert [b.key for b in row.command_blocks] == ["Install", "Update"]
    install, update = row.command_blocks
    assert install.title == "Install Fred78290/nct6687d on Fedora:"
    assert install.commands == guide.install_text
    assert "make dkms/install" in install.commands
    assert update.commands == guide.update_text
    assert row.install_notes == (*guide.install_notes, *guide.notes)


def test_loaded_it87_leads_with_the_update():
    """Contract review, XD-1: the daemon recommends for a loaded driver that
    bound nothing, and says reinstalling the same build changes nothing.
    A loaded it87 may still be the in-kernel one, so the install block stays,
    second and labelled for that case. DEC-500: between them, the rebuild for
    the running kernel — the in-kernel one is loaded after a kernel update
    whose DKMS build did not follow, which a first install does not fix."""
    set_install_family(InstallFamily.DEBIAN)
    assert [b.key for b in _row("it87").command_blocks] == ["Install", "Update"]  # contrast
    update, rebuild, install = _row("it87", module_loaded=True).command_blocks
    assert (update.key, rebuild.key, install.key) == ("Update", "Rebuild", "Install")
    assert update.title == "Already running frankcrawford/it87? Update it:"
    assert rebuild.commands == "dkms status\nsudo dkms autoinstall"
    assert rebuild.commands == install_guide("it87", InstallFamily.DEBIAN).rebuild_text
    assert "kernel update" in rebuild.title
    assert install.title.startswith("Still on the in-kernel it87? ")


def test_loaded_nct6687_gets_only_the_update():
    # The kernel has no nct6687 of its own: a loaded one is the out-of-tree build.
    set_install_family(InstallFamily.FEDORA)
    guide = install_guide("nct6687", InstallFamily.FEDORA)
    row = _row("nct6687", module_loaded=True)
    assert [b.key for b in row.command_blocks] == ["Update"]
    assert row.command_blocks[0].commands == guide.update_text
    assert guide.install_notes  # precondition: there are install-only notes to drop
    assert row.install_notes == guide.notes


def test_hardware_row_has_no_steps_for_an_in_kernel_driver():
    row = _row("it87", in_mainline=True)
    assert row.has_recommendation
    assert (row.command_blocks, row.install_notes) == ((), ())
