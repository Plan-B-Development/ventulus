"""The Debian/Ubuntu, Fedora and tarball packages of the GUI (DEC-499, XD-4).

Run for real where that needs no root: ``packaging/linux/stage.sh`` (their one
file list) against the PKGBUILD's ``package()``, the tarball ``build.sh``
assembles, its ``install.sh`` and uninstaller under ``--root``, and the
prerequisite check the tarball runs. Installing each package on its
distribution and starting it against the released daemon is
``.github/ci/package-smoke.sh``, which ci.yml runs per format and distribution;
the last tests here hold that job, release.yml and the dependency lists to
their shape.
"""

from __future__ import annotations

import ast
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
VERSION = PYPROJECT["project"]["version"]
FLAVOURS = ("deb", "rpm", "tarball")
#: stage.sh's parts and the package each is (DEC-503).
PARTS = {"cli": "ventulus-diag", "gui": "ventulus"}

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux packaging")


def _run(args: list[str], cwd: Path = REPO, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, **kw)


def _ok(proc: subprocess.CompletedProcess, what: str) -> None:
    assert proc.returncode == 0, f"{what} failed ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}"


def _tree(root: Path) -> dict[str, int]:
    """Every regular file under *root*, as its path on the target system → mode."""
    return {
        "/" + str(p.relative_to(root)): p.stat().st_mode & 0o7777
        for p in root.rglob("*")
        if p.is_file() and not p.is_symlink()
    }


def _wheel(path: Path, version: str) -> Path:
    """A wheel of this checkout's real ``ventulus`` package, as ``build`` makes it:
    the package and a .dist-info whose requirements are pyproject.toml's."""
    whl = path / f"ventulus-{version}-py3-none-any.whl"
    dist = f"ventulus-{version}.dist-info"
    requires = "".join(f"Requires-Dist: {d}\n" for d in PYPROJECT["project"]["dependencies"])
    with zipfile.ZipFile(whl, "w") as zf:
        for f in sorted((REPO / "src" / "ventulus").rglob("*")):
            if f.is_file() and "__pycache__" not in f.parts:
                zf.write(f, str(f.relative_to(REPO / "src")))
        zf.writestr(
            f"{dist}/METADATA",
            f"Metadata-Version: 2.4\nName: ventulus\nVersion: {version}\n{requires}"
            'Provides-Extra: dev\nRequires-Dist: pytest>=8.0; extra == "dev"\n',
        )
        zf.writestr(
            f"{dist}/WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
        )
        zf.writestr(
            f"{dist}/entry_points.txt",
            "[console_scripts]\nventulus = ventulus.main:main\n"
            "ventulus-diag = ventulus.diag.cli:main\n",
        )
        zf.writestr(f"{dist}/top_level.txt", "ventulus\n")
        zf.writestr(f"{dist}/RECORD", "")
    return whl


def _man(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "ventulus.1").write_text(".TH VENTULUS 1\n")
    (path / "ventulus-diag.1").write_text(".TH VENTULUS-DIAG 1\n")
    return path


def _libdir(flavour: str, stage: Path) -> Path:
    """Where *flavour* puts the modules, inside the staged tree."""
    if flavour == "rpm":
        found = list(stage.glob("usr/lib/python3.*/site-packages"))
        assert len(found) == 1, found
        return found[0]
    return stage / {"deb": "usr/share/ventulus", "tarball": "usr/local/lib/ventulus"}[flavour]


def _stage(tmp_path: Path, flavour: str, part: str = "cli", version: str = VERSION) -> Path:
    dest = tmp_path / f"stage-{part}"
    proc = _run(
        [
            "bash",
            "packaging/linux/stage.sh",
            flavour,
            part,
            str(_wheel(tmp_path, version)),
            str(_man(tmp_path / "man")),
            str(dest),
        ]
    )
    _ok(proc, f"stage.sh {flavour} {part}")
    return dest


def _pkgbuild_files(tmp_path: Path, package: str) -> dict[str, int]:
    """What ``packaging/PKGBUILD``'s ``package_<package>()`` installs, with modes:
    the function itself, run with ``install`` recorded and the wheel install skipped.

    It runs in a scratch directory, never the checkout: the stub reads no file,
    so only the two directories whose globs package() expands are copied there.
    A new glob over anything else stays unexpanded and fails the comparison."""
    pkgver = re.search(r"^pkgver=(\S+)$", (REPO / "packaging/PKGBUILD").read_text(), re.M)
    assert pkgver is not None
    src = tmp_path / f"ventulus-{pkgver.group(1)}"
    for globbed in ("manual", "docs"):
        if not (src / globbed).exists():
            shutil.copytree(REPO / globbed, src / globbed)
    log = tmp_path / f"installs-{package}"
    # makepkg sets pkgname to the split package being packaged.
    script = (
        'set -e; log=$2; source "$1"; pkgdir=/PKGDIR; srcdir=$4; pkgname=$3; '
        'install() { printf "%s\\n" "$*" >> "$log"; }; python() { :; }; rm() { :; }; '
        '"package_$3"'
    )
    _ok(
        _run(
            [
                "bash",
                "-c",
                script,
                "_",
                str(REPO / "packaging/PKGBUILD"),
                str(log),
                package,
                str(tmp_path),
            ],
            tmp_path,
        ),
        f"PKGBUILD package_{package}()",
    )
    out = {}
    for line in log.read_text().splitlines():
        words = line.split()
        mode = next(w[3:] for w in words if w.startswith("-Dm"))
        dest = words[-1]
        assert dest.startswith("/PKGDIR/"), line
        out[dest.removeprefix("/PKGDIR")] = int(mode, 8)
    return out


def _as_flavour(path: str, flavour: str) -> str:
    """A PKGBUILD path as *flavour* lays it out."""
    if flavour == "deb":
        for pkg in PARTS.values():
            lic = f"/usr/share/licenses/{pkg}/"
            if path == lic + "LICENSE":
                return f"/usr/share/doc/{pkg}/copyright"
            if path.startswith(lic):
                return f"/usr/share/doc/{pkg}/" + path.removeprefix(lic)
        return path.replace("/usr/share/zsh/site-functions/", "/usr/share/zsh/vendor-completions/")
    if flavour == "tarball":
        if path.startswith("/usr/share/ventulus/"):
            return "/usr/local/lib/ventulus/" + path.removeprefix("/usr/share/ventulus/")
        return "/usr/local/" + path.removeprefix("/usr/")
    return path


@pytest.mark.parametrize("part", PARTS)
@pytest.mark.parametrize("flavour", FLAVOURS)
def test_stage_installs_what_the_pkgbuild_installs(tmp_path, flavour, part):
    """stage.sh is the one file list for three formats and the PKGBUILD is a
    second, independent one, for each of the two packages. A file added to one
    and not the other would ship on Arch and be missing elsewhere, or the
    reverse, or ship in the wrong package. The Python modules and the programs
    come from the wheel in both and are checked by the next test."""
    program = "/bin/ventulus-diag" if part == "cli" else "/bin/ventulus"
    expected = {
        _as_flavour(p, flavour): m
        for p, m in _pkgbuild_files(tmp_path, PARTS[part]).items()
        if not p.endswith(program)
    }
    stage = _stage(tmp_path, flavour, part)
    staged = {p: m for p, m in _tree(stage).items() if not p.endswith(program)}
    if part == "cli":
        lib = "/" + str(_libdir(flavour, stage).relative_to(stage))
        staged = {
            path: mode
            for path, mode in staged.items()
            if not path.startswith((f"{lib}/ventulus/", f"{lib}/ventulus-"))
        }
    assert staged == expected
    assert len(expected) > (30 if part == "gui" else 5), expected


def test_the_two_packages_share_no_file(tmp_path):
    """dpkg, rpm and pacman refuse two packages that ship one path."""
    for flavour in FLAVOURS:
        (tmp_path / flavour).mkdir()
        cli = _tree(_stage(tmp_path / flavour, flavour, "cli"))
        gui = _tree(_stage(tmp_path / flavour, flavour, "gui"))
        assert set(cli) & set(gui) == set(), flavour


def _launcher_inserts(launcher: Path) -> list[str]:
    tree = ast.parse(launcher.read_text())
    return [
        node.args[1].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "insert"
    ]


@pytest.mark.parametrize("flavour", FLAVOURS)
def test_every_format_runs_the_wheel_with_its_metadata(tmp_path, flavour):
    """ventulus-diag carries the whole package and its .dist-info, which is where
    both programs read their version: without it the version is "dev" and the
    daemon checks are off. RECORD is gone, so pip cannot remove package-managed
    files. Each program puts a private module directory first on the path; the
    GUI package carries its program and no module."""
    stage = _stage(tmp_path, flavour, "cli", version="9.8.7")
    gui = _stage(tmp_path, flavour, "gui", version="9.8.7")
    lib = _libdir(flavour, stage)
    meta = lib / "ventulus-9.8.7.dist-info"
    assert (meta / "METADATA").is_file()
    assert not (meta / "RECORD").exists()
    assert (meta / "INSTALLER").read_text().strip() == {
        "deb": "dpkg",
        "rpm": "rpm",
        "tarball": "ventulus-tarball",
    }[flavour]
    shipped = {p.relative_to(lib / "ventulus") for p in (lib / "ventulus").rglob("*.py")}
    source = {
        p.relative_to(REPO / "src/ventulus")
        for p in (REPO / "src/ventulus").rglob("*.py")
        if "__pycache__" not in p.parts
    }
    assert shipped == source
    assert not list(gui.rglob("*.py")), "the GUI package carries no module"

    prefix = "/usr/local" if flavour == "tarball" else "/usr"
    target = "/" + str(lib.relative_to(stage))
    for root, program, entry in (
        (stage, "ventulus-diag", "from ventulus.diag.cli import main"),
        (gui, "ventulus", "from ventulus.main import main"),
    ):
        launcher = root / prefix.lstrip("/") / "bin" / program
        assert launcher.stat().st_mode & 0o777 == 0o755
        assert _launcher_inserts(launcher) == ([] if flavour == "rpm" else [target])
        text = launcher.read_text()
        assert text.startswith("#!/usr/bin/python3\n") and entry in text, program

    # The staged code, first on the path as the launcher puts it, finds its own
    # version and, where the modules are private, the branding the GUI package
    # puts beside them.
    probe = (
        "import sys; sys.path.insert(0, sys.argv[1]);"
        "from ventulus.constants import APP_VERSION; from ventulus.paths import assets_dir;"
        "print(APP_VERSION); print(assets_dir())"
    )
    if flavour != "rpm":
        shutil.copytree(gui / target.lstrip("/"), lib, dirs_exist_ok=True)
    proc = _run([sys.executable, "-I", "-B", "-c", probe, str(lib)])
    _ok(proc, "the staged package")
    app_version, assets = proc.stdout.split("\n")[:2]
    assert app_version == "9.8.7"
    if flavour != "rpm":
        assert Path(assets) == lib / "assets/branding"
        assert (Path(assets) / "app_icon/app_icon.svg").is_file()


# ---------------------------------------------------------------- the tarball


def _build_tarball(tmp_path: Path) -> Path:
    work = tmp_path / "work"
    (work / "wheel").mkdir(parents=True)
    _wheel(work / "wheel", VERSION)
    _man(work / "man")
    out = tmp_path / "out"
    _ok(
        _run(["bash", "packaging/linux/build.sh", "tarball", str(work), VERSION, str(out)]),
        "build.sh tarball",
    )
    with tarfile.open(out / f"ventulus-{VERSION}-noarch.tar.gz") as tf:
        tf.extractall(tmp_path / "x", filter="tar")
    return tmp_path / "x" / f"ventulus-{VERSION}-noarch"


def _manifest(path: Path) -> dict[str, tuple[str, int]]:
    out = {}
    for line in path.read_text().splitlines():
        digest, mode, file = line.split(" ", 2)
        out[file] = (digest, int(mode, 8))
    return out


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rewrite_manifest(pkg: Path) -> None:
    """MANIFEST from the files now in the package, as build.sh writes it."""
    files = pkg / "files"
    lines = [
        f"{_sha256(p)} {p.stat().st_mode & 0o777:o} /{p.relative_to(files)}"
        for p in sorted(files.rglob("*"), key=lambda p: str(p.relative_to(files)))
        if p.is_file()
    ]
    (pkg / "MANIFEST").write_text("\n".join(lines) + "\n")


def _install(pkg: Path, root: Path, *extra: str) -> subprocess.CompletedProcess:
    return _run(["bash", str(pkg / "install.sh"), *extra, "--root", str(root)])


def test_the_tarball_lists_every_file_it_carries(tmp_path):
    """The tarball is the staged tree plus its uninstaller, every file in MANIFEST
    with the sum and mode it really has, and the installer and prerequisite check
    beside them."""
    pkg = _build_tarball(tmp_path)
    assert sorted(p.name for p in pkg.iterdir()) == [
        "CLI-FILES",
        "MANIFEST",
        "files",
        "install.sh",
        "prereqs.py",
    ]
    manifest = _manifest(pkg / "MANIFEST")
    files = _tree(pkg / "files")
    assert set(manifest) == set(files)
    for path, (digest, mode) in manifest.items():
        assert _sha256(pkg / "files" / path.lstrip("/")) == digest
        assert files[path] == mode, path
    assert files["/usr/local/lib/ventulus/uninstall"] == 0o755
    assert all(p.startswith("/usr/local/") for p in files)


def test_the_cli_files_are_ventulus_diags_and_nothing_of_the_guis(tmp_path):
    """CLI-FILES is what ``install.sh --cli-only`` places: the library, the
    ventulus-diag program and its man page and completions, the uninstaller —
    and no GUI program, desktop entry or Qt-only asset outside the library."""
    pkg = _build_tarball(tmp_path)
    cli = set((pkg / "CLI-FILES").read_text().split())
    manifest = set(_manifest(pkg / "MANIFEST"))
    assert cli < manifest
    assert {
        "/usr/local/bin/ventulus-diag",
        "/usr/local/lib/ventulus/uninstall",
        "/usr/local/lib/ventulus/ventulus/diag/cli.py",
        "/usr/local/share/man/man1/ventulus-diag.1",
    } <= cli
    gui_only = {
        "/usr/local/bin/ventulus",
        "/usr/local/share/applications/ventulus.desktop",
        "/usr/local/share/man/man1/ventulus.1",
    }
    assert gui_only <= manifest and not gui_only & cli


def test_a_cli_only_install_then_the_gui_then_back(tmp_path):
    """--cli-only places ventulus-diag's files alone and records just those; a
    full install adds the GUI's; --cli-only again takes the GUI away, as an
    upgrade drops a file the new version no longer ships."""
    pkg = _build_tarball(tmp_path)
    root = tmp_path / "root"
    cli = set((pkg / "CLI-FILES").read_text().split())
    record = root / "usr/local/lib/ventulus/tarball-manifest"

    _ok(_install(pkg, root, "--cli-only"), "install.sh --cli-only")
    placed = {
        p for p in _tree(root) if "/__pycache__/" not in p and p != str(record)[len(str(root)) :]
    }
    assert placed == cli
    assert set(_manifest(record)) == cli
    assert not (root / "usr/local/bin/ventulus").exists()

    _ok(_install(pkg, root), "install.sh")
    assert (root / "usr/local/bin/ventulus").is_file()
    assert set(_manifest(record)) == set(_manifest(pkg / "MANIFEST"))

    _ok(_install(pkg, root, "--cli-only"), "install.sh --cli-only over the GUI")
    assert not (root / "usr/local/bin/ventulus").exists()
    assert (root / "usr/local/bin/ventulus-diag").is_file()
    assert set(_manifest(record)) == cli


def test_deps_names_less_for_the_cli(tmp_path):
    pkg = _build_tarball(tmp_path)
    full = _run(["bash", str(pkg / "install.sh"), "--deps"])
    cli = _run(["bash", str(pkg / "install.sh"), "--deps", "--cli-only"])
    _ok(full, "--deps")
    _ok(cli, "--deps --cli-only")
    assert "pyside" not in cli.stdout.lower() and "httpx" in cli.stdout.lower()
    if full.stdout.startswith("sudo"):
        assert "pyside" in full.stdout.lower()


def test_install_places_every_file_compiles_and_records_the_manifest(tmp_path):
    pkg = _build_tarball(tmp_path)
    root = tmp_path / "root"
    _ok(_install(pkg, root), "install.sh")
    manifest = _manifest(pkg / "MANIFEST")
    placed = _tree(root)
    for path, (_digest, mode) in manifest.items():
        assert placed[path] == mode, path
    assert (root / "usr/local/lib/ventulus/tarball-manifest").read_text() == (
        pkg / "MANIFEST"
    ).read_text()
    pycache = list((root / "usr/local/lib/ventulus/ventulus").rglob("__pycache__/*.pyc"))
    assert pycache, "install.sh compiled no bytecode"
    # Nothing but the shipped files, their bytecode and the manifest.
    extra = {
        p
        for p in placed
        if p not in manifest and "/__pycache__/" not in p and not p.endswith("/tarball-manifest")
    }
    assert extra == set()


def test_an_upgrade_removes_what_the_new_version_no_longer_ships(tmp_path):
    pkg = _build_tarball(tmp_path)
    root = tmp_path / "root"
    _ok(_install(pkg, root), "first install")
    gone = "usr/local/share/doc/ventulus/manual/fan-wizard.md"
    module = "usr/local/lib/ventulus/ventulus/ui/branding.py"
    stale = root / "usr/local/lib/ventulus/ventulus/ui/__pycache__"
    assert any(stale.glob("branding.*.pyc"))

    (pkg / "files" / gone).unlink()
    (pkg / "files" / module).unlink()
    (pkg / "files/usr/local/share/doc/ventulus/manual/new.md").write_text("new\n")
    _rewrite_manifest(pkg)
    _ok(_install(pkg, root), "upgrade")

    assert not (root / gone).exists()
    assert not (root / module).exists()
    assert not any(stale.glob("branding.*.pyc")), "bytecode outlived its source"
    assert (root / "usr/local/share/doc/ventulus/manual/new.md").read_text() == "new\n"


def test_install_refuses_a_tarball_that_does_not_match_its_manifest(tmp_path):
    """A damaged extraction installs nothing. This catches corruption only:
    MANIFEST travels in the same tarball, so authenticity comes from SHA256SUMS
    and the attestation on the .tar.gz."""
    pkg = _build_tarball(tmp_path)
    (pkg / "files/usr/local/share/doc/ventulus/README.md").write_text("truncated")
    root = tmp_path / "root"
    proc = _install(pkg, root)
    assert proc.returncode != 0
    assert "does not match MANIFEST" in proc.stderr
    assert not root.exists() or _tree(root) == {}


def test_uninstall_removes_the_install_and_its_directories(tmp_path):
    pkg = _build_tarball(tmp_path)
    root = tmp_path / "root"
    _ok(_install(pkg, root), "install.sh")
    uninstall = root / "usr/local/lib/ventulus/uninstall"
    _ok(_run(["bash", str(uninstall), "--root", str(root)]), "uninstall")
    assert _tree(root) == {}
    for owned in ("lib/ventulus", "share/doc/ventulus", "share/licenses/ventulus"):
        assert not (root / "usr/local" / owned).exists(), owned


# --------------------------------------------------------- the prerequisites


def _prereqs():
    import importlib.util

    spec = importlib.util.spec_from_file_location("prereqs", REPO / "packaging/linux/prereqs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("version", "spec", "ok"),
    [
        ("6.8.2.1", ">=6.6,<7", True),
        ("6.5.3", ">=6.6,<7", False),
        ("7.0", ">=6.6,<7", False),
        ("0.13.7", ">=0.13.7,<1", True),
        ("0.13.6", ">=0.13.7,<1", False),
        ("2", ">=2.0,<3", True),
        ("2.4.6", ">=2.0,<3", True),
        ("1.26.4", ">=2.0,<3", False),
        ("0.28.1", ">=0.27,<1", True),
        ("2.0rc1", ">=2.0", True),
        ("3.1", "", True),
    ],
)
def test_prerequisite_versions_compare_by_release(version, spec, ok):
    assert _prereqs().satisfies(version, spec) is ok


def test_prerequisites_are_the_wheels_runtime_requirements(tmp_path):
    """The tarball checks exactly pyproject.toml's dependencies, read from the
    metadata it ships, and not the development extras."""
    stage = _stage(tmp_path, "tarball")
    got = _prereqs().requirements(stage / "usr/local/lib/ventulus")
    want = [
        re.fullmatch(r"([A-Za-z0-9_.-]+)(.*)", d).groups()
        for d in PYPROJECT["project"]["dependencies"]
    ]
    assert got == want


@pytest.mark.parametrize(
    "line",
    [
        "PySide6<7,>=6.6",
        "PySide6 (<7,>=6.6)",
        "PySide6 <7, >=6.6",
        "PySide6<7,>=6.6; python_version >= '3.12'",
    ],
)
def test_prerequisites_read_every_requirement_spelling(tmp_path, line):
    """setuptools writes ``name<7,>=6.6``; older metadata ``name (<7,>=6.6)``.
    A marker that is not an extra keeps the requirement."""
    meta = tmp_path / "ventulus-1.0.dist-info"
    meta.mkdir()
    (meta / "METADATA").write_text(
        f"Metadata-Version: 2.4\nName: ventulus\nVersion: 1.0\nRequires-Dist: {line}\n"
        'Requires-Dist: pytest>=8; extra == "dev"\n'
    )
    [(name, spec)] = _prereqs().requirements(tmp_path)
    assert name == "PySide6"
    assert _prereqs().satisfies("6.8.2.1", spec)
    assert not _prereqs().satisfies("7.0.0", spec)
    assert not _prereqs().satisfies("6.5", spec)


def test_prerequisite_check_passes_here_and_names_what_is_missing(tmp_path):
    """The check passes on an environment that runs the suite (whose packages
    meet pyproject.toml), and names an absent or too old requirement."""
    stage = _stage(tmp_path, "tarball")
    lib = stage / "usr/local/lib/ventulus"
    script = str(REPO / "packaging/linux/prereqs.py")
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    proc = _run([sys.executable, "-I", "-B", script, str(lib)], env=env)
    if "gpg is not installed" in proc.stdout or "gpg-agent is not installed" in proc.stdout:
        pytest.skip("no gpg or gpg-agent on this machine")
    _ok(proc, "prereqs.py")

    meta = next(lib.glob("ventulus-*.dist-info")) / "METADATA"
    meta.write_text(
        meta.read_text()
        + "Requires-Dist: ventulus-no-such-dependency>=1\nRequires-Dist: pytest>=999\n"
    )
    proc = _run([sys.executable, "-I", "-B", script, str(lib)], env=env)
    assert proc.returncode == 1
    assert "ventulus-no-such-dependency is not installed" in proc.stdout
    assert re.search(r"pytest \S+ is installed; Ventulus needs >=999", proc.stdout)


def test_the_cli_prerequisites_ignore_the_guis(tmp_path):
    """``--cli`` checks Python, the requirements ventulus-diag imports and that
    it loads — not the GUI's: a missing GUI dependency does not stop it, a
    missing CLI one does."""
    stage = _stage(tmp_path, "tarball")
    lib = stage / "usr/local/lib/ventulus"
    script = str(REPO / "packaging/linux/prereqs.py")
    meta = next(lib.glob("ventulus-*.dist-info")) / "METADATA"
    base = meta.read_text()
    meta.write_text(base + "Requires-Dist: ventulus-no-such-gui-dependency>=1\n")
    _ok(_run([sys.executable, "-I", "-B", script, "--cli", str(lib)]), "prereqs.py --cli")
    proc = _run([sys.executable, "-I", "-B", script, str(lib)])
    assert "ventulus-no-such-gui-dependency is not installed" in proc.stdout

    meta.write_text(base.replace("Requires-Dist: httpx", "Requires-Dist: httpx>=999,"))
    proc = _run([sys.executable, "-I", "-B", script, "--cli", str(lib)])
    assert proc.returncode == 1 and "httpx" in proc.stdout


def test_the_cli_requirements_are_what_the_cli_imports():
    """prereqs.CLI_REQUIREMENTS names every third-party distribution the CLI
    loads, and the rest of pyproject.toml's are the GUI's alone."""
    code = (
        "import sys, json; import ventulus.diag.cli, ventulus.diag.report, "
        "ventulus.diag.sweeps, ventulus.diag.validation; "
        "print(json.dumps(sorted({m.split('.')[0] for m in sys.modules})))"
    )
    env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
    proc = _run([sys.executable, "-c", code], env=env)
    _ok(proc, "import the CLI")
    import json

    loaded = {m.lower() for m in json.loads(proc.stdout)}
    deps = {d.lower() for d in _pyproject_floors()}
    assert {d for d in deps if d in loaded} == set(_prereqs().CLI_REQUIREMENTS)


# ----------------------------------------------------- dependency declarations


def _control_depends(package: str = "ventulus") -> list[tuple[str, str | None]]:
    """``(package, version)`` for each Depends entry of *package* in debian/control."""
    text = (REPO / "packaging/debian/control").read_text()
    text = "\n".join(ln for ln in text.splitlines() if not ln.startswith("#"))
    stanza = next(
        st for st in text.split("\n\n") if re.search(rf"^Package: {re.escape(package)}$", st, re.M)
    )
    field = re.search(r"^Depends:(.*?)(?=^\S|\Z)", stanza + "\n", re.M | re.S)
    assert field is not None
    out = []
    for entry in field.group(1).split(","):
        entry = " ".join(entry.split())
        if not entry or entry.startswith("${"):
            continue
        m = re.fullmatch(r"(\S+)(?: \((?:>=|=) (\S+)\))?", entry)
        assert m is not None, entry
        out.append((m.group(1), m.group(2)))
    return out


def _pyproject_floors() -> dict[str, str]:
    out = {}
    for dep in PYPROJECT["project"]["dependencies"]:
        m = re.match(r"([A-Za-z0-9_.-]+).*>=([0-9.]+)", dep)
        assert m is not None, dep
        out[m.group(1)] = m.group(2)
    return out


def test_debian_floors_are_pyprojects():
    """Debian's dependency floors restate pyproject.toml's, the one source the
    rpm and the tarball read directly. numpy carries Debian's epoch."""
    deps = dict(_control_depends())
    debian_name = {
        "PySide6": "python3-pyside6.qtcore",
        "httpx": "python3-httpx",
        "pyqtgraph": "python3-pyqtgraph",
        "numpy": "python3-numpy",
        "colorama": "python3-colorama",
    }
    floors = _pyproject_floors()
    assert set(floors) == set(debian_name), "a new dependency needs a Debian package"
    for dist, floor in floors.items():
        got = deps[debian_name[dist]]
        assert got is not None, f"{debian_name[dist]} has no floor"
        assert got.split(":")[-1] == floor, (dist, got, floor)
    assert deps["python3-numpy"].startswith("1:")
    assert deps["python3"] == PYPROJECT["project"]["requires-python"].removeprefix(">=")
    assert deps["ventulus-diag"] == "${binary:Version}", (
        "the GUI needs its own build of the library"
    )

    cli = dict(_control_depends("ventulus-diag"))
    assert set(cli) == {"python3", "ventulusd"} | {
        debian_name[d] for d in _prereqs().CLI_REQUIREMENTS
    }, "ventulus-diag must not pull in the Qt stack"
    assert cli["python3"] == deps["python3"]
    for dist in _prereqs().CLI_REQUIREMENTS:
        assert cli[debian_name[dist]] == floors[dist]


def test_the_library_moves_from_an_older_ventulus_package():
    """Up to 5.5.x the library was the ventulus package's: Breaks plus Replaces
    on ventulus-diag let dpkg move the files on upgrade, and rpm's Conflicts
    makes dnf upgrade the old ventulus with it. "Older than this build" is
    exact: every older ventulus depends on its own ventulus-diag, so none can
    run beside this one. A fixed version boundary instead would make a build
    of an unbumped version conflict with its own GUI."""
    control = (REPO / "packaging/debian/control").read_text()
    stanza = next(st for st in control.split("\n\n") if "Package: ventulus-diag" in st)
    for field in ("Breaks", "Replaces"):
        assert re.search(rf"^{field}: ventulus \(<< \$\{{binary:Version\}}\)$", stanza, re.M)
    spec = (REPO / "packaging/rpm/ventulus.spec").read_text()
    assert re.search(r"^Conflicts:\s+ventulus < %\{version\}-%\{release\}$", spec, re.M)
    assert re.search(r"^Requires:\s+ventulus-diag = %\{version\}-%\{release\}$", spec, re.M)


def test_every_package_requires_the_daemon_minimum():
    """dpkg and rpm enforce the daemon floor at install time, as pacman does the
    PKGBUILD's; each must be ``constants.DAEMON_MINIMUM_VERSION``."""
    from ventulus.constants import DAEMON_MINIMUM_VERSION

    for package in PARTS.values():
        assert dict(_control_depends(package))["ventulusd"] == DAEMON_MINIMUM_VERSION, package
    spec = (REPO / "packaging/rpm/ventulus.spec").read_text()
    assert (
        re.findall(r"^Requires:\s+ventulusd\b.*$", spec, re.M)
        == [f"Requires:       ventulusd >= {DAEMON_MINIMUM_VERSION}"] * 2
    ), "the GUI and ventulus-diag each"


def test_tarball_names_the_debian_packages_the_deb_depends_on():
    """``install.sh --deps`` gives Debian and Ubuntu users the .deb's own
    dependency list; the package-smoke job installs it before the tarball."""
    text = (REPO / "packaging/linux/install.sh").read_text()
    m = re.search(r'^deb_deps="([^"]*)"', text, re.M)
    assert m is not None
    want = {name for name, _ in _control_depends()} - {"ventulusd", "ventulus-diag"}
    assert set(m.group(1).split()) == want
    m = re.search(r'^deb_cli_deps="([^"]*)"', text, re.M)
    assert m is not None
    assert set(m.group(1).split()) == {n for n, _ in _control_depends("ventulus-diag")} - {
        "ventulusd"
    }


def _spec_requires() -> list[str]:
    spec = (REPO / "packaging/rpm/ventulus.spec").read_text()
    return re.findall(r"^Requires:\s+(.+?)\s*$", spec, re.M)


def test_tarball_names_the_fedora_packages_the_rpm_needs():
    """Fedora names each Python dependency ``python3-<name>``; with the
    interpreter and what the spec names by hand, that is the whole ``dnf``
    line ``install.sh --deps`` prints on Fedora. ventulus-diag needs Python and
    the CLI's requirements alone."""
    text = (REPO / "packaging/linux/install.sh").read_text()
    m = re.search(r'^rpm_deps="([^"]*)"', text, re.M)
    assert m is not None
    by_hand = {r for r in _spec_requires() if not r.startswith(("(", "ventulusd", "ventulus-diag"))}
    want = {"python3"} | {f"python3-{d.lower()}" for d in _pyproject_floors()} | by_hand
    assert set(m.group(1).split()) == want
    m = re.search(r'^rpm_cli_deps="([^"]*)"', text, re.M)
    assert m is not None
    assert set(m.group(1).split()) == {"python3"} | {
        f"python3-{d.lower()}" for d in _prereqs().CLI_REQUIREMENTS
    }


def test_the_rpm_moves_exactly_the_guis_python_requirements_to_the_gui():
    """rpm generates ventulus-diag's Python requirements from the metadata. The
    GUI's own are excluded there and named on ventulus with pyproject.toml's
    floor and ceiling; a new dependency must be classified one way or the other."""
    spec = (REPO / "packaging/rpm/ventulus.spec").read_text()
    excluded = re.search(r"^%global __requires_exclude .*dist\\\\\(\(([a-z0-9|]+)\)", spec, re.M)
    assert excluded is not None
    gui_only = {d.lower() for d in _pyproject_floors()} - set(_prereqs().CLI_REQUIREMENTS)
    assert set(excluded.group(1).split("|")) == gui_only
    rich = {}
    for req in _spec_requires():
        m = re.fullmatch(r"\(python3dist\((\S+)\) >= (\S+) with python3dist\(\1\) < (\S+)\)", req)
        if m:
            rich[m.group(1)] = (m.group(2), m.group(3))
    want = {}
    for dep in PYPROJECT["project"]["dependencies"]:
        m = re.fullmatch(r"([A-Za-z0-9_.-]+)>=([0-9.]+),<([0-9.]+)", dep)
        assert m is not None, dep
        if m.group(1).lower() in gui_only:
            want[m.group(1).lower()] = (m.group(2), m.group(3))
    assert rich == want


# ------------------------------------------------------------- the workflows


def _workflow(name: str) -> dict:
    return yaml.safe_load((REPO / ".github/workflows" / name).read_text(encoding="utf-8"))


def _fedora_releases(job: dict) -> list[int]:
    """The Fedora releases an rpm job builds for: its matrix, in its container."""
    assert job["container"] == "fedora:${{ matrix.fedora }}"
    releases = job["strategy"]["matrix"]["fedora"]
    assert releases and all(type(n) is int for n in releases)
    return sorted(releases)


def test_ci_smoke_tests_every_format_on_every_distribution_it_serves():
    """A format the Release ships with no smoke leg could ship a package that
    misses a dependency, its version metadata or its icon, and nothing would
    notice until a user installed it. Every Fedora release the .rpm is built for
    gets its own .rpm and tarball smoke leg, and runs the suite on its own Python."""
    jobs = _workflow("ci.yml")["jobs"]
    fedora = _fedora_releases(jobs["rpm"])
    assert len(fedora) >= 2  # the GA release and the one before it
    legs = {
        (leg["format"], leg["image"])
        for leg in jobs["package-smoke"]["strategy"]["matrix"]["include"]
    }
    assert legs == {
        ("deb", "debian:13"),
        ("deb", "ubuntu:26.04"),
        ("tarball", "debian:13"),
        ("tarball", "ubuntu:26.04"),
    } | {(fmt, f"fedora:{n}") for n in fedora for fmt in ("rpm", "tarball")}
    assert set(jobs["package-smoke"]["needs"]) == {"packages", "rpm", "released-daemon"}
    distro = set(jobs["distro"]["strategy"]["matrix"]["image"])
    assert {img for img in distro if img.startswith("fedora:")} == {f"fedora:{n}" for n in fedora}
    # Each release's build is its own artifact, and the smoke job downloads them all.
    upload = next(
        s for s in jobs["rpm"]["steps"] if s.get("uses", "").startswith("actions/upload-artifact")
    )
    pattern = next(
        s["with"]["pattern"]
        for s in jobs["package-smoke"]["steps"]
        if s.get("uses", "").startswith("actions/download-artifact") and "pattern" in s["with"]
    )
    names = {upload["with"]["name"].replace("${{ matrix.fedora }}", str(n)) for n in fedora}
    assert len(names) == len(fedora)
    assert all(re.fullmatch(pattern.replace("*", ".*"), n) for n in names)


def test_the_release_waits_for_and_attaches_every_format():
    """The Release needs every package job, attests and attaches everything it
    downloaded, and the .rpms it expects are the Fedora releases it builds on,
    the same ones CI smoke-tests."""
    jobs = _workflow("release.yml")["jobs"]
    needs = set(jobs["github-release"]["needs"])
    assert {"build-test", "linux-packages", "rpm-package", "ci-green"} <= needs
    fedora = _fedora_releases(jobs["rpm-package"])
    assert fedora == _fedora_releases(_workflow("ci.yml")["jobs"]["rpm"])
    sums = next(s for s in jobs["github-release"]["steps"] if s.get("name") == "Write SHA256SUMS")
    expected = re.search(r'expected="([^"]*)"', sums["run"]).group(1).split()
    assert expected == [
        "ventulus-$v-1-any.pkg.tar.zst",
        "ventulus-diag-$v-1-any.pkg.tar.zst",
        "ventulus_$v-1_all.deb",
        "ventulus-diag_$v-1_all.deb",
        *(f"ventulus-$v-1.fc{n}.noarch.rpm" for n in fedora),
        *(f"ventulus-diag-$v-1.fc{n}.noarch.rpm" for n in fedora),
        "ventulus-$v-noarch.tar.gz",
    ]
    uploads = {
        s["with"]["name"]
        for job in ("linux-packages", "rpm-package")
        for s in jobs[job]["steps"]
        if s.get("uses", "").startswith("actions/upload-artifact")
    }
    uploads = {u.replace("${{ matrix.fedora }}", str(n)) for u in uploads for n in fedora}
    pattern = next(
        s["with"]["pattern"]
        for s in jobs["github-release"]["steps"]
        if s.get("uses", "").startswith("actions/download-artifact") and "pattern" in s["with"]
    )
    assert {u for u in uploads if re.fullmatch(pattern.replace("*", ".*"), u)} == {
        "linux-release-package",
        *(f"rpm-fc{n}-release-package" for n in fedora),
    }
