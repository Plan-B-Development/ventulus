"""The signed update manifest, ``ventulus-updates.json`` (DEC-499 decision 3).

``pacman-repo`` publishes it on Pages beside its detached signature, from both
projects' latest stable Releases (format 1 is defined by that repository's
``.github/scripts/manifest.py``)::

    {
      "schema": 1,
      "generated_at": "2026-10-16T12:00:00Z",
      "components": {
        "ventulusd": {"version", "tag", "release_url", "api_version", "assets"},
        "ventulus":  {"version", "tag", "release_url", "daemon_minimum", "assets"}
      }
    }

with each asset ``{"name", "format", "sha256", "size", "url"}`` plus ``"fedora"``
for a Fedora-specific ``.rpm``.

Parse only bytes whose signature has been checked (``services/signature.py``).
The parser is strict anyway: every field it reads must have the right type and
shape, a version must be a stable ``X.Y.Z`` (a prerelease anywhere refuses the
whole manifest), and every URL must point at the project's own GitHub Release for
that tag, so even a correctly signed but malformed manifest cannot send a
download elsewhere. Keys it does not read are ignored; a change that matters
bumps ``schema``, which this GUI then refuses. Qt-free.
"""

from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass, replace
from enum import StrEnum

SCHEMA = 1
OWNER = "Plan-B-Development"
GUI = "ventulus"
DAEMON = "ventulusd"

#: Largest manifest accepted. A real one is a few KB (eight assets).
MAX_MANIFEST_BYTES = 256 * 1024
#: Largest detached signature accepted (an ed25519 one is about 120 bytes).
MAX_SIGNATURE_BYTES = 16 * 1024
#: Largest asset the manifest may describe; the packages are a few MB.
MAX_ASSET_BYTES = 512 * 1024 * 1024

_VERSION = re.compile(r"^(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ASSET_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,199}$")
_GENERATED_AT = "%Y-%m-%dT%H:%M:%SZ"

Version = tuple[int, int, int]


class ManifestError(ValueError):
    """The manifest is not a well-formed format-1 manifest."""


class AssetFormat(StrEnum):
    PACMAN = "pacman"
    DEB = "deb"
    RPM = "rpm"
    TARBALL = "tarball"


#: How each format's file name ends, and where its architecture token sits.
_FORMAT_NAME: dict[AssetFormat, re.Pattern[str]] = {
    AssetFormat.PACMAN: re.compile(r"-([a-z0-9_]+)\.pkg\.tar\.zst$"),
    AssetFormat.DEB: re.compile(r"_([a-z0-9_]+)\.deb$"),
    AssetFormat.RPM: re.compile(r"\.([a-z0-9_]+)\.rpm$"),
    AssetFormat.TARBALL: re.compile(r"-([a-z0-9_]+)\.tar\.gz$"),
}

#: Architecture tokens that run anywhere.
_ARCH_INDEPENDENT = frozenset({"any", "all", "noarch"})
#: ``platform.machine()`` -> the tokens packages use for it.
_ARCH_ALIASES: dict[str, frozenset[str]] = {
    "x86_64": frozenset({"x86_64", "amd64"}),
}


def parse_version(text: object) -> Version | None:
    """``X.Y.Z`` as a tuple, or None for anything else (prereleases included)."""
    if not isinstance(text, str):
        return None
    m = _VERSION.match(text)
    if m is None:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def format_version(version: Version) -> str:
    return ".".join(str(part) for part in version)


@dataclass(frozen=True)
class Asset:
    name: str
    format: AssetFormat
    sha256: str
    size: int
    url: str
    arch: str
    fedora: int | None = None

    def runs_on(self, machine: str) -> bool:
        return self.arch in _ARCH_INDEPENDENT or self.arch in _ARCH_ALIASES.get(
            machine, frozenset()
        )


@dataclass(frozen=True)
class Component:
    project: str
    version: Version
    tag: str
    release_url: str
    assets: tuple[Asset, ...]
    #: The daemon's ``API_VERSION`` (ventulusd only).
    api_version: int | None = None
    #: The oldest ventulusd this GUI release needs (ventulus only).
    daemon_minimum: Version | None = None

    @property
    def version_text(self) -> str:
        return format_version(self.version)


@dataclass(frozen=True)
class Manifest:
    generated_at: datetime.datetime
    daemon: Component
    gui: Component


class AssetChoice(StrEnum):
    FOUND = "found"
    #: The release has no file of this format at all.
    MISSING = "missing"
    #: It has the format, but nothing for this machine's architecture.
    UNSUPPORTED_ARCH = "unsupported_arch"
    #: It has the format for this architecture, but not for this Fedora release.
    NO_FEDORA_BUILD = "no_fedora_build"


def select_asset(
    component: Component,
    fmt: AssetFormat,
    *,
    machine: str,
    fedora: int | None = None,
) -> tuple[AssetChoice, Asset | None]:
    """The one asset of *fmt* this machine installs, or why there is none.

    A Fedora-specific ``.rpm`` (one carrying ``fedora``) matches only that
    Fedora release; the daemon's ``.rpm`` carries none and serves every Fedora.
    """
    of_format = [a for a in component.assets if a.format is fmt]
    if not of_format:
        return AssetChoice.MISSING, None
    runnable = [a for a in of_format if a.runs_on(machine)]
    if not runnable:
        return AssetChoice.UNSUPPORTED_ARCH, None
    if fmt is AssetFormat.RPM:
        generic = [a for a in runnable if a.fedora is None]
        specific = [a for a in runnable if a.fedora is not None and a.fedora == fedora]
        runnable = specific or generic
        if not runnable:
            return AssetChoice.NO_FEDORA_BUILD, None
    if len(runnable) != 1:
        # Two candidates for one machine would mean a broken release; offer none.
        return AssetChoice.MISSING, None
    return AssetChoice.FOUND, runnable[0]


def parse_manifest(raw: bytes) -> Manifest:
    """Parse format-1 manifest bytes; raise :class:`ManifestError` on any defect."""
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ManifestError("the manifest is larger than any real one")
    try:
        data = json.loads(raw.decode("utf-8"), parse_constant=_reject_constant)
    except RecursionError as exc:
        raise ManifestError("the manifest is nested too deeply") from exc
    except (UnicodeDecodeError, ValueError) as exc:
        raise ManifestError(f"the manifest is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestError("the manifest is not a JSON object")
    schema = data.get("schema")
    if type(schema) is not int or schema != SCHEMA:
        raise ManifestError(f"unsupported manifest schema {schema!r}")
    generated = data.get("generated_at")
    try:
        if not isinstance(generated, str):
            raise ValueError
        generated_at = datetime.datetime.strptime(generated, _GENERATED_AT).replace(
            tzinfo=datetime.UTC
        )
    except ValueError as exc:
        raise ManifestError("generated_at is not a UTC timestamp") from exc
    components = data.get("components")
    if not isinstance(components, dict) or set(components) != {GUI, DAEMON}:
        raise ManifestError("the manifest must describe exactly ventulus and ventulusd")
    daemon = _component(DAEMON, components[DAEMON])
    gui = _component(GUI, components[GUI])
    api = components[DAEMON].get("api_version")
    if type(api) is not int or api < 0:
        raise ManifestError("ventulusd: api_version is not a non-negative integer")
    floor = parse_version(components[GUI].get("daemon_minimum"))
    if floor is None:
        raise ManifestError("ventulus: daemon_minimum is not a stable X.Y.Z version")
    return Manifest(
        generated_at=generated_at,
        daemon=replace(daemon, api_version=api),
        gui=replace(gui, daemon_minimum=floor),
    )


def _reject_constant(token: str) -> object:
    raise ValueError(f"non-standard JSON constant {token}")


def _component(project: str, entry: object) -> Component:
    if not isinstance(entry, dict):
        raise ManifestError(f"{project}: not an object")
    version = parse_version(entry.get("version"))
    if version is None:
        raise ManifestError(f"{project}: version is not a stable X.Y.Z release")
    tag = f"v{format_version(version)}"
    if entry.get("tag") != tag:
        raise ManifestError(f"{project}: tag does not match its version")
    release_url = f"https://github.com/{OWNER}/{project}/releases/tag/{tag}"
    if entry.get("release_url") != release_url:
        raise ManifestError(f"{project}: release_url is not the project's Release")
    assets = entry.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ManifestError(f"{project}: no assets")
    parsed = tuple(_asset(project, tag, a) for a in assets)
    if len({a.name for a in parsed}) != len(parsed):
        raise ManifestError(f"{project}: an asset is listed twice")
    return Component(
        project=project,
        version=version,
        tag=tag,
        release_url=release_url,
        assets=parsed,
    )


def _asset(project: str, tag: str, entry: object) -> Asset:
    if not isinstance(entry, dict):
        raise ManifestError(f"{project}: an asset is not an object")
    name = entry.get("name")
    if not isinstance(name, str) or not _ASSET_NAME.match(name) or ".." in name:
        raise ManifestError(f"{project}: an asset name is not a plain file name")
    try:
        fmt = AssetFormat(entry.get("format"))
    except ValueError as exc:
        raise ManifestError(f"{project}: {name} has an unknown format") from exc
    m = _FORMAT_NAME[fmt].search(name)
    if m is None:
        raise ManifestError(f"{project}: {name} does not look like a {fmt} file")
    sha = entry.get("sha256")
    if not isinstance(sha, str) or not _SHA256.match(sha):
        raise ManifestError(f"{project}: {name} has no SHA-256")
    size = entry.get("size")
    if type(size) is not int or not 0 < size <= MAX_ASSET_BYTES:
        raise ManifestError(f"{project}: {name} has an impossible size")
    url = f"https://github.com/{OWNER}/{project}/releases/download/{tag}/{name}"
    if entry.get("url") != url:
        raise ManifestError(f"{project}: {name} is not served from the project's Release")
    fedora = entry.get("fedora")
    rpm_fc = re.search(r"\.fc(\d+)\.[a-z0-9_]+\.rpm$", name) if fmt is AssetFormat.RPM else None
    if fedora is not None:
        if type(fedora) is not int or rpm_fc is None or int(rpm_fc.group(1)) != fedora:
            raise ManifestError(f"{project}: {name} names the wrong Fedora release")
    elif rpm_fc is not None:
        raise ManifestError(f"{project}: {name} is Fedora-specific but says not which release")
    return Asset(
        name=name,
        format=fmt,
        sha256=sha,
        size=size,
        url=url,
        arch=m.group(1),
        fedora=fedora,
    )
