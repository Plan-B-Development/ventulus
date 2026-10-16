"""DEC-499: how each component was installed comes from package queries, not the distro."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ventulus.services import install_ownership
from ventulus.services.install_ownership import (
    READ_ONLY_QUERIES,
    InstallMethod,
    Ownership,
    Probe,
    daemon_ownership,
    gui_ownership,
    run_query,
)

MODULE = Path("/usr/share/ventulus/ventulus/__init__.py")


class FakeSystem:
    """Package managers that answer from a table, and record every call."""

    def __init__(self, tools=("pacman", "pacman-conf", "dpkg-query", "rpm"), answers=None):
        self.tools = set(tools)
        self.answers: dict[str, tuple[int, str] | BaseException] = answers or {}
        self.calls: list[list[str]] = []

    def which(self, name: str) -> str | None:
        return f"/usr/bin/{name}" if name in self.tools else None

    def run(self, argv):
        argv = list(argv)
        assert any(tuple(argv[: len(p)]) == p for p in READ_ONLY_QUERIES), argv
        self.calls.append(argv)
        answer = self.answers.get(argv[0], (1, ""))
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def probe(self, tmp_path: Path) -> Probe:
        return Probe(
            run=self.run,
            which=self.which,
            gui_tarball_manifest=tmp_path / "gui-manifest",
            daemon_tarball_manifest=tmp_path / "daemon-manifest",
            etc=tmp_path / "etc",
        )


def _daemon_binary(tmp_path: Path) -> Path:
    binary = tmp_path / "usr-bin-ventulusd"
    binary.write_bytes(b"\x7fELF")
    return binary


def test_a_checkout_is_a_source_install_whatever_owns_its_files(tmp_path):
    fake = FakeSystem(answers={"pacman": (0, "ventulus\n")})
    got = gui_ownership(MODULE, app_version="dev", probe=fake.probe(tmp_path))
    assert got == Ownership(InstallMethod.SOURCE)
    assert fake.calls == []


def test_pacman_ownership_and_its_repository(tmp_path):
    fake = FakeSystem(
        answers={"pacman": (0, "ventulus\n"), "pacman-conf": (0, "core\nextra\nventulus\n")}
    )
    got = gui_ownership(MODULE, app_version="5.1.0", probe=fake.probe(tmp_path))
    assert got == Ownership(InstallMethod.PACMAN, repository_configured=True)
    assert ["pacman", "-Qqo", str(MODULE)] in fake.calls


def test_pacman_without_the_repository(tmp_path):
    fake = FakeSystem(answers={"pacman": (0, "ventulus\n"), "pacman-conf": (0, "core\nextra\n")})
    got = gui_ownership(MODULE, app_version="5.1.0", probe=fake.probe(tmp_path))
    assert got == Ownership(InstallMethod.PACMAN, repository_configured=False)


def test_dpkg_ownership_and_the_apt_source(tmp_path):
    sources = tmp_path / "etc" / "apt" / "sources.list.d"
    sources.mkdir(parents=True)
    fake = FakeSystem(answers={"dpkg-query": (0, f"ventulus: {MODULE}\n")})
    got = gui_ownership(MODULE, app_version="5.1.0", probe=fake.probe(tmp_path))
    assert got == Ownership(InstallMethod.DEB, repository_configured=False)
    (sources / "ventulus.sources").write_text(
        "Types: deb\n"
        "URIs: https://github.com/Plan-B-Development/pacman-repo/releases/download/repo\n"
        "Suites: ./\n"
    )
    got = gui_ownership(MODULE, app_version="5.1.0", probe=fake.probe(tmp_path))
    assert got == Ownership(InstallMethod.DEB, repository_configured=True)


def test_a_commented_out_apt_source_is_not_configured(tmp_path):
    apt = tmp_path / "etc" / "apt"
    apt.mkdir(parents=True)
    (apt / "sources.list").write_text(
        "# deb https://github.com/Plan-B-Development/pacman-repo/releases/download/repo ./\n"
    )
    fake = FakeSystem(answers={"dpkg-query": (0, f"ventulus: {MODULE}\n")})
    got = gui_ownership(MODULE, app_version="5.1.0", probe=fake.probe(tmp_path))
    assert got.repository_configured is False


def test_rpm_ownership_and_the_dnf_repository(tmp_path):
    repos = tmp_path / "etc" / "yum.repos.d"
    repos.mkdir(parents=True)
    (repos / "fedora.repo").write_text("[fedora]\nbaseurl=https://example.org/fedora\n")
    fake = FakeSystem(tools=("rpm",), answers={"rpm": (0, "ventulusd\n")})
    binary = _daemon_binary(tmp_path)
    got = daemon_ownership(binary, probe=fake.probe(tmp_path))
    assert got == Ownership(InstallMethod.RPM, repository_configured=False)
    (repos / "ventulus.repo").write_text(
        "[ventulus]\nbaseurl=https://plan-b-development.github.io/pacman-repo/rpm/fedora/"
        "$releasever/$basearch/\n"
    )
    got = daemon_ownership(binary, probe=fake.probe(tmp_path))
    assert got == Ownership(InstallMethod.RPM, repository_configured=True)


def test_the_tarball_install_list(tmp_path):
    binary = _daemon_binary(tmp_path)
    (tmp_path / "daemon-manifest").write_text(f"{'0' * 64} 755 {binary}\n")
    fake = FakeSystem()
    got = daemon_ownership(binary, probe=fake.probe(tmp_path))
    assert got == Ownership(InstallMethod.TARBALL)


def test_a_package_outranks_a_tarball_list_left_behind(tmp_path):
    """The tarball was installed, then the .deb over it without uninstalling."""
    binary = _daemon_binary(tmp_path)
    (tmp_path / "daemon-manifest").write_text(f"{'0' * 64} 755 {binary}\n")
    fake = FakeSystem(tools=("dpkg-query",), answers={"dpkg-query": (0, f"ventulusd: {binary}\n")})
    got = daemon_ownership(binary, probe=fake.probe(tmp_path))
    assert got.method is InstallMethod.DEB


def test_a_tarball_list_that_does_not_name_the_file_is_not_ownership(tmp_path):
    binary = _daemon_binary(tmp_path)
    (tmp_path / "daemon-manifest").write_text(f"{'0' * 64} 755 /usr/bin/other\n")
    got = daemon_ownership(binary, probe=FakeSystem().probe(tmp_path))
    assert got.method is not InstallMethod.TARBALL


def test_the_distribution_does_not_decide(tmp_path):
    """rpm installed on a pacman system: whichever owns the file answers."""
    fake = FakeSystem(answers={"pacman": (1, ""), "dpkg-query": (1, ""), "rpm": (0, "ventulus\n")})
    got = gui_ownership(MODULE, app_version="5.1.0", probe=fake.probe(tmp_path))
    assert got.method is InstallMethod.RPM


def test_gui_and_daemon_are_answered_separately(tmp_path):
    binary = _daemon_binary(tmp_path)
    (tmp_path / "daemon-manifest").write_text(f"{'0' * 64} 755 {binary}\n")
    fake = FakeSystem(answers={"pacman": (0, "ventulus\n"), "pacman-conf": (0, "ventulus\n")})
    probe = fake.probe(tmp_path)
    assert gui_ownership(MODULE, app_version="5.1.0", probe=probe).method is InstallMethod.PACMAN
    assert daemon_ownership(binary, probe=probe).method is InstallMethod.TARBALL


@pytest.mark.parametrize(
    "answer",
    [
        (0, "control-ofc-gui\n"),  # another package owns the file
        (0, ""),
        (0, "ventulus\nventulus-extra\n"),
    ],
)
def test_ownership_by_another_package_is_not_ownership(tmp_path, answer):
    fake = FakeSystem(tools=("pacman",), answers={"pacman": answer})
    got = gui_ownership(MODULE, app_version="5.1.0", probe=fake.probe(tmp_path))
    assert got == Ownership(InstallMethod.SOURCE)


def test_a_dpkg_diversion_is_not_ownership(tmp_path):
    fake = FakeSystem(
        tools=("dpkg-query",),
        answers={"dpkg-query": (0, f"diversion by other from: {MODULE}\nventulus: {MODULE}\n")},
    )
    got = gui_ownership(MODULE, app_version="5.1.0", probe=fake.probe(tmp_path))
    assert got.method is not InstallMethod.DEB


@pytest.mark.parametrize("failure", [OSError("gone"), subprocess.TimeoutExpired(["pacman"], 10)])
def test_a_failing_query_falls_through_to_the_next_manager(tmp_path, failure):
    fake = FakeSystem(answers={"pacman": failure, "dpkg-query": (0, f"ventulus: {MODULE}\n")})
    got = gui_ownership(MODULE, app_version="5.1.0", probe=fake.probe(tmp_path))
    assert got.method is InstallMethod.DEB


def test_no_daemon_binary_is_unknown(tmp_path):
    fake = FakeSystem(answers={"pacman": (0, "ventulusd\n")})
    got = daemon_ownership(tmp_path / "missing", probe=fake.probe(tmp_path))
    assert got == Ownership(InstallMethod.UNKNOWN)
    assert fake.calls == []


def test_an_unowned_daemon_binary_is_a_source_build(tmp_path):
    got = daemon_ownership(_daemon_binary(tmp_path), probe=FakeSystem().probe(tmp_path))
    assert got == Ownership(InstallMethod.SOURCE)


@pytest.mark.parametrize(
    "argv",
    [
        ["pacman", "-Syu"],
        ["pacman", "-S", "ventulus"],
        ["rpm", "-e", "ventulus"],
        ["dpkg", "-i", "x.deb"],
        ["sudo", "pacman", "-Qqo", "/x"],
        ["sh", "-c", "pacman -Qqo /x"],
    ],
)
def test_run_query_refuses_anything_but_a_read_only_query(argv):
    with pytest.raises(ValueError, match="read-only"):
        run_query(argv)


def test_every_query_this_module_builds_is_read_only(tmp_path):
    """Every argv the probes produce passes the same gate as run_query."""
    fake = FakeSystem(
        answers={
            "pacman": (1, ""),
            "dpkg-query": (1, ""),
            "rpm": (1, ""),
            "pacman-conf": (0, "ventulus\n"),
        }
    )
    probe = fake.probe(tmp_path)
    gui_ownership(MODULE, app_version="5.1.0", probe=probe)
    daemon_ownership(_daemon_binary(tmp_path), probe=probe)
    install_ownership._repository_configured(InstallMethod.PACMAN, probe)
    programs = {call[0] for call in fake.calls}
    assert programs == {"pacman", "dpkg-query", "rpm", "pacman-conf"}
