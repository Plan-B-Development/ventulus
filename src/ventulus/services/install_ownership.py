"""How the GUI and the daemon were installed (DEC-499 decision 4).

The update check hands each component to whatever installed it, so it has to
know that, and it asks rather than guesses: the package manager that owns the
file (``pacman -Qqo``, ``dpkg-query -S``, ``rpm -qf``), or the tarball's install
list. The distribution's name is never used: an Arch machine can have ``rpm``
installed, and a tarball can sit on Fedora. The GUI and the daemon are answered
separately, since they need not have come the same way.

Every query is read-only and runs with a fixed argument list, no shell and a
timeout. :data:`READ_ONLY_QUERIES` lists the only programs this module runs, and
the tests hold every call to it. Qt-free.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

#: The tarballs' install lists (GUI ``packaging/linux/install.sh``, daemon
#: ``packaging/linux/install.sh`` in ventulusd): ``<sha256> <mode> <path>`` lines.
GUI_TARBALL_MANIFEST = Path("/usr/local/lib/ventulus/tarball-manifest")
DAEMON_TARBALL_MANIFEST = Path("/usr/lib/ventulus/tarball-manifest")
#: Where every daemon package puts the binary.
DAEMON_BINARY = Path("/usr/bin/ventulusd")

#: The repositories pacman-repo serves (its README's configuration lines).
PACMAN_REPO_NAME = "ventulus"
APT_SOURCE_MARKER = "plan-b-development/pacman-repo"
DNF_REPO_MARKER = "plan-b-development.github.io/pacman-repo"

QUERY_TIMEOUT_S = 10.0
#: Repository configuration files are small; this bounds a pathological one.
_MAX_CONFIG_BYTES = 1024 * 1024
_MAX_CONFIG_FILES = 256

#: The programs and leading arguments this module ever runs.
READ_ONLY_QUERIES: tuple[tuple[str, ...], ...] = (
    ("pacman", "-Qqo"),
    ("dpkg-query", "-S"),
    ("rpm", "-qf", "--queryformat", "%{NAME}\\n"),
    ("pacman-conf", "--repo-list"),
)


class InstallMethod(StrEnum):
    PACMAN = "pacman"
    DEB = "deb"
    RPM = "rpm"
    TARBALL = "tarball"
    #: A source checkout, or a pip install: the version is all there is to say.
    SOURCE = "source"
    #: Nothing could be found out (no daemon binary, or a query failed).
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Ownership:
    method: InstallMethod
    #: Whether the package manager already reads this project's repository.
    #: Meaningful for pacman, deb and rpm only.
    repository_configured: bool = False


#: ``run(argv) -> (exit status, stdout)``; raises OSError or TimeoutExpired.
Runner = Callable[[Sequence[str]], tuple[int, str]]


def run_query(argv: Sequence[str]) -> tuple[int, str]:
    """Run one read-only query, as :data:`Runner`."""
    if not any(tuple(argv[: len(prefix)]) == prefix for prefix in READ_ONLY_QUERIES):
        raise ValueError(f"not a read-only ownership query: {argv!r}")
    proc = subprocess.run(
        list(argv),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=QUERY_TIMEOUT_S,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"},
        check=False,
    )
    return proc.returncode, proc.stdout


@dataclass(frozen=True)
class Probe:
    """Where to look; the tests point every field at a scratch tree."""

    run: Runner = run_query
    which: Callable[[str], str | None] = shutil.which
    gui_tarball_manifest: Path = GUI_TARBALL_MANIFEST
    daemon_tarball_manifest: Path = DAEMON_TARBALL_MANIFEST
    etc: Path = Path("/etc")


def gui_module_file() -> Path:
    """A file of the running GUI that every package format installs."""
    import ventulus

    return Path(ventulus.__file__).resolve()


def gui_ownership(module_file: Path, *, app_version: str, probe: Probe | None = None) -> Ownership:
    """How the running GUI was installed.

    ``dev`` is the version of a checkout that was never installed
    (``constants.APP_VERSION``): a source install, whatever owns its files.
    """
    if app_version == "dev":
        return Ownership(InstallMethod.SOURCE)
    probe = probe or Probe()
    found = _owner(module_file, "ventulus", probe.gui_tarball_manifest, probe)
    # Installed, but by none of the four formats: pip, a virtual environment.
    return found if found.method is not InstallMethod.UNKNOWN else Ownership(InstallMethod.SOURCE)


def daemon_ownership(binary: Path = DAEMON_BINARY, *, probe: Probe | None = None) -> Ownership:
    """How the daemon at *binary* was installed; UNKNOWN when it is not there."""
    probe = probe or Probe()
    try:
        if not binary.is_file():
            return Ownership(InstallMethod.UNKNOWN)
    except OSError:
        return Ownership(InstallMethod.UNKNOWN)
    found = _owner(binary, "ventulusd", probe.daemon_tarball_manifest, probe)
    # A file at the packages' path that nothing owns is a hand-copied build.
    return found if found.method is not InstallMethod.UNKNOWN else Ownership(InstallMethod.SOURCE)


def _owner(path: Path, package: str, tarball_manifest: Path, probe: Probe) -> Ownership:
    """A package manager's claim first: a tarball install list left behind when a
    package replaced the tarball install must not outrank the real owner."""
    queries: tuple[tuple[InstallMethod, str, list[str]], ...] = (
        (InstallMethod.PACMAN, "pacman", ["pacman", "-Qqo", str(path)]),
        (InstallMethod.DEB, "dpkg-query", ["dpkg-query", "-S", str(path)]),
        (InstallMethod.RPM, "rpm", ["rpm", "-qf", "--queryformat", "%{NAME}\\n", str(path)]),
    )
    for method, program, argv in queries:
        if probe.which(program) is None:
            continue
        try:
            code, out = probe.run(argv)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if code != 0:
            continue
        if _owned_by(method, out, package):
            return Ownership(method, _repository_configured(method, probe))
    if _tarball_lists(tarball_manifest, path):
        return Ownership(InstallMethod.TARBALL)
    return Ownership(InstallMethod.UNKNOWN)


def _owned_by(method: InstallMethod, out: str, package: str) -> bool:
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    if method is InstallMethod.DEB:
        # "ventulus: /usr/share/ventulus/ventulus/__init__.py"; a diversion
        # line names two packages and is not ownership.
        owners = {line.split(":", 1)[0].strip() for line in lines if ": " in line}
        return owners == {package}
    # pacman -Qqo and rpm -qf print the package name alone.
    return lines == [package]


def _tarball_lists(manifest: Path, path: Path) -> bool:
    try:
        with manifest.open("rb") as f:
            raw = f.read(_MAX_CONFIG_BYTES + 1)
    except OSError:
        return False
    if len(raw) > _MAX_CONFIG_BYTES:
        return False
    want = str(path)
    for line in raw.decode("utf-8", "replace").splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3 and parts[2] == want:
            return True
    return False


def _repository_configured(method: InstallMethod, probe: Probe) -> bool:
    if method is InstallMethod.PACMAN:
        if probe.which("pacman-conf") is None:
            return False
        try:
            code, out = probe.run(["pacman-conf", "--repo-list"])
        except (OSError, subprocess.TimeoutExpired):
            return False
        return code == 0 and PACMAN_REPO_NAME in {line.strip() for line in out.splitlines()}
    if method is InstallMethod.DEB:
        apt = probe.etc / "apt"
        files = [apt / "sources.list", *_listing(apt / "sources.list.d")]
        return _any_mentions(files, APT_SOURCE_MARKER)
    if method is InstallMethod.RPM:
        return _any_mentions(_listing(probe.etc / "yum.repos.d"), DNF_REPO_MARKER)
    return False


def _listing(directory: Path) -> list[Path]:
    try:
        return sorted(directory.iterdir())[:_MAX_CONFIG_FILES]
    except OSError:
        return []


def _any_mentions(files: list[Path], marker: str) -> bool:
    for path in files:
        try:
            if not path.is_file():
                continue
            with path.open("rb") as f:
                text = f.read(_MAX_CONFIG_BYTES).decode("utf-8", "replace").lower()
        except OSError:
            continue
        for line in text.splitlines():
            stripped = line.strip()
            # A commented-out source is not a configured one.
            if stripped and not stripped.startswith("#") and marker in stripped:
                return True
    return False
