"""Whether this system's Python can run Ventulus from the tarball (DEC-499).

    python3 -I -B prereqs.py [--cli] <libdir>

``--cli`` checks only what ventulus-diag needs (``install.sh --cli-only``,
DEC-503): Python and the requirements in :data:`CLI_REQUIREMENTS`, then that
the CLI imports. Without it, everything the GUI needs.

<libdir> holds the ``ventulus`` package and its ``.dist-info``, as the tarball
carries them. The requirements are the ``Requires-Dist`` lines of that
metadata, which is pyproject.toml's dependency list, so the floors are never
restated here. The tarball's install.sh runs this before it installs anything
and prints the command that installs what is missing.

Exit status 0 when everything is present, 1 with one line per problem.
"""

from __future__ import annotations

import importlib.metadata
import re
import shutil
import sys
from email.parser import Parser
from pathlib import Path

MIN_PYTHON = (3, 12)

#: The runtime requirements ventulus-diag imports; every other one is the GUI's.
#: Debian's and Fedora's ventulus-diag packages depend on the same set.
CLI_REQUIREMENTS = frozenset({"httpx"})

_REQUIREMENT = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*\(?([^;()]*)\)?\s*(?:;(.*))?$")
_CLAUSE = re.compile(r"^\s*(>=|<=|==|!=|<|>)\s*([0-9][0-9A-Za-z.]*)\s*$")


def release(version: str) -> tuple[int, ...]:
    """The numeric release of a version: ``"6.8.2.1"`` → ``(6, 8, 2, 1)``.

    Anything after the leading dotted digits (``rc1``, ``.post2``, a local part)
    is ignored, and trailing zeros do not count, so ``2`` equals ``2.0``.
    """
    match = re.match(r"\d+(?:\.\d+)*", version)
    if match is None:
        raise ValueError(f"not a version: {version!r}")
    parts = [int(p) for p in match.group(0).split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def satisfies(version: str, spec: str) -> bool:
    """Whether *version* meets every clause of *spec* (``">=6.6,<7"``)."""
    have = release(version)
    for clause in filter(None, (c.strip() for c in spec.split(","))):
        match = _CLAUSE.match(clause)
        if match is None:
            raise ValueError(f"unsupported version clause: {clause!r}")
        op, want = match.group(1), release(match.group(2))
        ok = {
            ">=": have >= want,
            "<=": have <= want,
            "==": have == want,
            "!=": have != want,
            "<": have < want,
            ">": have > want,
        }[op]
        if not ok:
            return False
    return True


def requirements(libdir: Path) -> list[tuple[str, str]]:
    """``(name, spec)`` for each runtime requirement in the shipped metadata."""
    found = list(libdir.glob("ventulus-*.dist-info/METADATA"))
    if len(found) != 1:
        raise SystemExit(f"prereqs.py: expected one ventulus .dist-info in {libdir}")
    meta = Parser().parsestr(found[0].read_text(encoding="utf-8"))
    out = []
    for line in meta.get_all("Requires-Dist") or []:
        match = _REQUIREMENT.match(line)
        if match is None:
            raise SystemExit(f"prereqs.py: cannot read requirement {line!r}")
        name, spec, marker = match.groups()
        if marker and "extra" in marker:
            continue  # the development extras
        out.append((name, spec.strip()))
    return out


def problems(libdir: Path, *, cli: bool = False) -> list[str]:
    found = []
    if sys.version_info < MIN_PYTHON:
        found.append(
            "Python {}.{} or newer is needed; this is {}.{}".format(
                *MIN_PYTHON, *sys.version_info[:2]
            )
        )
    for name, spec in requirements(libdir):
        if cli and name not in CLI_REQUIREMENTS:
            continue
        try:
            have = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            found.append(f"{name} is not installed")
            continue
        if spec and not satisfies(have, spec):
            found.append(f"{name} {have} is installed; Ventulus needs {spec}")
    if found:
        return found  # the checks below would only repeat these
    if cli:
        sys.path.insert(0, str(libdir))
        try:
            import ventulus.diag.cli
        except ImportError as exc:
            found.append(f"ventulus-diag cannot load: {exc}")
        return found

    # A module the metadata cannot name: Debian and Ubuntu split PySide6 per Qt
    # module, and pyqtgraph imports QtOpenGL. Importing the GUI finds them all.
    sys.path.insert(0, str(libdir))
    try:
        import ventulus.main  # noqa: F401
    except ImportError as exc:
        found.append(f"the GUI cannot load: {exc}")

    # Without Qt's SVG image plugin the app icon is blank (DEC-499 phase 0).
    try:
        from PySide6.QtGui import QImageReader

        formats = {bytes(f).decode() for f in QImageReader.supportedImageFormats()}
        if "svg" not in formats:
            found.append("Qt's SVG image plugin is not installed")
    except ImportError as exc:
        found.append(f"PySide6 cannot load: {exc}")

    # The update check verifies the signed release manifest with gpg, whose
    # --import fails without gpg-agent on Debian and Ubuntu.
    for tool in ("gpg", "gpg-agent"):
        if shutil.which(tool) is None:
            found.append(f"{tool} is not installed")
    return found


def main(argv: list[str]) -> int:
    args = argv[1:]
    cli = args[:1] == ["--cli"]
    if cli:
        args = args[1:]
    if len(args) != 1:
        print("usage: python3 -I -B prereqs.py [--cli] <libdir>", file=sys.stderr)
        return 2
    found = problems(Path(args[0]), cli=cli)
    for line in found:
        print(f"  - {line}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
