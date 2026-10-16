"""The opt-in update check (DEC-499 decision 4): fetch, verify, compare, hand off.

Off by default. A check is one HTTPS GET of the signed manifest on Pages (and of
its signature when the manifest changed), sent with no header beyond what httpx
always sends and ``User-Agent: Ventulus/<version>``. Nothing reaches the daemon.

Trust: the signature is checked against the bundled key and the pinned
fingerprint (``services/signature.py``) before the manifest is parsed
(``services/update_manifest.py``), and a manifest older than the newest one this
user has already accepted is refused, so a replayed old manifest cannot hide a
release. Any failure is reported as a failure and never as a result.

Hand-off: the GUI never runs a privileged command. A package-managed component is
handed to its package manager; a tarball install gets a verified download and the
commands that install it; a source install gets the version and a link. How each
was installed comes from ``services/install_ownership.py``, separately.

The only files written are this module's cache (``<cache_dir>/updates/``) and a
download the user asked for. Qt-free; the UI runs it on a worker thread.
"""

from __future__ import annotations

import contextlib
import datetime
import hashlib
import json
import logging
import os
import shlex
import tempfile
import threading
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import httpx

from ventulus import paths
from ventulus.services import signature
from ventulus.services.install_ownership import InstallMethod, Ownership
from ventulus.services.update_manifest import (
    MAX_MANIFEST_BYTES,
    MAX_SIGNATURE_BYTES,
    Asset,
    AssetChoice,
    AssetFormat,
    Component,
    Manifest,
    ManifestError,
    format_version,
    parse_manifest,
    parse_version,
    select_asset,
)

log = logging.getLogger(__name__)

MANIFEST_URL = "https://plan-b-development.github.io/pacman-repo/ventulus-updates.json"
SIGNATURE_URL = MANIFEST_URL + ".sig"
#: Where the repository setup for pacman, APT and DNF is written down.
REPOSITORY_SETUP_URL = "https://github.com/Plan-B-Development/pacman-repo#readme"

#: The automatic check runs at most this often; a manual check any time.
CHECK_INTERVAL = datetime.timedelta(days=1)

#: Per connection attempt and per read; a download that keeps arriving is never
#: cut off. Short, so closing the window never waits long for a stalled one.
CHECK_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
DOWNLOAD_TIMEOUT = httpx.Timeout(10.0, connect=5.0)

#: The transport every client uses. None is httpx's own; the test suite replaces
#: it with one that records any request a test did not set up (tests/conftest.py).
TRANSPORT: httpx.BaseTransport | None = None

_STATE_FILE = "state.json"
_MANIFEST_FILE = "ventulus-updates.json"
_SIGNATURE_FILE = "ventulus-updates.json.sig"
_DISMISSED_FILE = "dismissed"
_TIMESTAMP = "%Y-%m-%dT%H:%M:%SZ"
_CHUNK = 64 * 1024


class Outcome(StrEnum):
    #: A verified manifest was compared with what is installed.
    CHECKED = "checked"
    #: No answer: offline, a timeout, a refused connection.
    UNREACHABLE = "unreachable"
    #: The server answered with something other than the manifest (403, 429, 5xx).
    REFUSED = "refused"
    #: An answer came, but it could not be verified: a bad or foreign signature,
    #: a malformed or unknown-format manifest, or one older than one seen before.
    UNVERIFIED = "unverified"


class VersionState(StrEnum):
    UP_TO_DATE = "up_to_date"
    UPDATE_AVAILABLE = "update_available"
    #: The installed version is newer than the latest release.
    AHEAD = "ahead"
    #: The installed version is not known (no daemon connection, a source build).
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Installed:
    """What is installed, gathered by the caller."""

    gui_version: str
    #: The connected daemon's version, or None while there is no connection.
    daemon_version: str | None
    gui: Ownership
    daemon: Ownership
    #: ``platform.machine()``.
    machine: str
    #: os-release ``VERSION_ID`` on Fedora, else None.
    fedora: int | None
    #: The API version this GUI speaks (``constants.EXPECTED_API_VERSION``).
    api_version: int


@dataclass(frozen=True)
class ComponentStatus:
    project: str
    installed: str | None
    latest: str
    state: VersionState
    method: InstallMethod
    repository_configured: bool
    release_url: str
    asset: Asset | None
    #: What the hand-off says, one instruction per line (commands included).
    handoff: tuple[str, ...]
    #: Why a package is missing, and similar.
    notes: tuple[str, ...] = ()

    @property
    def can_download(self) -> bool:
        """A tarball install with a newer release has a verified download."""
        return (
            self.method is InstallMethod.TARBALL
            and self.state is VersionState.UPDATE_AVAILABLE
            and self.asset is not None
        )


@dataclass(frozen=True)
class UpdateReport:
    outcome: Outcome
    checked_at: datetime.datetime
    #: A failure in words (never a result).
    error: str = ""
    published_at: datetime.datetime | None = None
    gui: ComponentStatus | None = None
    daemon: ComponentStatus | None = None
    compatibility: tuple[str, ...] = ()
    #: Answered from the cache because the manifest had not changed (HTTP 304).
    unchanged: bool = False

    @property
    def components(self) -> tuple[ComponentStatus, ...]:
        return tuple(c for c in (self.gui, self.daemon) if c is not None)

    @property
    def update_available(self) -> bool:
        return any(c.state is VersionState.UPDATE_AVAILABLE for c in self.components)

    @property
    def offer_key(self) -> str:
        """Names the offered versions, so a dismissed notice stays dismissed
        until a newer release appears."""
        return ";".join(
            f"{c.project}={c.latest}"
            for c in self.components
            if c.state is VersionState.UPDATE_AVAILABLE
        )


@dataclass
class CheckState:
    """What the check remembers between runs, in ``<cache_dir>/updates/``."""

    last_attempt: datetime.datetime | None = None
    #: ``generated_at`` of the newest manifest accepted; an older one is refused.
    accepted_generated_at: datetime.datetime | None = None
    etag: str = ""
    last_modified: str = ""


def state_dir() -> Path:
    return paths.cache_dir() / "updates"


def load_state(directory: Path | None = None) -> CheckState:
    directory = directory or state_dir()
    try:
        data = paths.load_json_capped(directory / _STATE_FILE, max_bytes=64 * 1024)
    except (OSError, ValueError):
        return CheckState()
    if not isinstance(data, dict):
        return CheckState()

    def text(key: str, limit: int = 512) -> str:
        value = data.get(key)
        return value[:limit] if isinstance(value, str) else ""

    return CheckState(
        last_attempt=_parse_time(data.get("last_attempt")),
        accepted_generated_at=_parse_time(data.get("accepted_generated_at")),
        etag=text("etag"),
        last_modified=text("last_modified"),
    )


def save_state(state: CheckState, directory: Path | None = None) -> None:
    directory = directory or state_dir()
    data = {
        "last_attempt": _format_time(state.last_attempt),
        "accepted_generated_at": _format_time(state.accepted_generated_at),
        "etag": state.etag,
        "last_modified": state.last_modified,
    }
    try:
        paths.atomic_write(directory / _STATE_FILE, json.dumps(data, indent=2) + "\n")
    except OSError as exc:
        log.warning("Could not save the update-check state: %s", exc)


def load_dismissed(directory: Path | None = None) -> str:
    """The :attr:`UpdateReport.offer_key` whose notice the user dismissed.

    Its own file, written only by the UI thread, so it never races the worker's
    :func:`save_state`.
    """
    path = (directory or state_dir()) / _DISMISSED_FILE
    try:
        return _read_capped(path, 4096).decode("utf-8", "replace").strip()
    except OSError:
        return ""


def save_dismissed(offer_key: str, directory: Path | None = None) -> None:
    try:
        paths.atomic_write((directory or state_dir()) / _DISMISSED_FILE, offer_key + "\n")
    except OSError as exc:
        log.warning("Could not save the dismissed update notice: %s", exc)


def automatic_check_due(state: CheckState, now: datetime.datetime, *, enabled: bool) -> bool:
    """Whether the opt-in daily check should run now. Never when it is off."""
    if not enabled:
        return False
    return state.last_attempt is None or now - state.last_attempt >= CHECK_INTERVAL


def make_client(app_version: str, timeout: httpx.Timeout = CHECK_TIMEOUT) -> httpx.Client:
    return httpx.Client(
        transport=TRANSPORT,
        timeout=timeout,
        # identity: the size limits count the bytes that arrive, so a small
        # compressed answer cannot expand past them before the limit is checked.
        headers={"User-Agent": f"Ventulus/{app_version}", "Accept-Encoding": "identity"},
        follow_redirects=False,
    )


class _TooLarge(Exception):
    pass


@dataclass(frozen=True)
class _Fetched:
    status: int
    body: bytes = b""
    etag: str = ""
    last_modified: str = ""


def _fetch(client: httpx.Client, url: str, limit: int, headers: dict[str, str]) -> _Fetched:
    with client.stream("GET", url, headers=headers) as response:
        if response.status_code != 200:
            return _Fetched(response.status_code)
        body = bytearray()
        for chunk in response.iter_bytes():
            body += chunk
            if len(body) > limit:
                raise _TooLarge(url)
        return _Fetched(
            200,
            bytes(body),
            response.headers.get("etag", "")[:512],
            response.headers.get("last-modified", "")[:512],
        )


def check(
    installed: Installed,
    *,
    client: httpx.Client,
    state: CheckState,
    cache: Path | None = None,
    now: datetime.datetime | None = None,
    key_file: Path | None = None,
    fingerprint: str = signature.REPOSITORY_KEY_FINGERPRINT,
    cancel: threading.Event | None = None,
) -> UpdateReport:
    """Run one check. Updates *state* in place; the caller saves it.

    *cancel* (set when the window closes) stops it between its steps.
    *key_file* and *fingerprint* exist for the tests (a test-only key).
    """
    cache = cache or state_dir()
    now = now or datetime.datetime.now(datetime.UTC)
    state.last_attempt = now

    def failed(outcome: Outcome, error: str) -> UpdateReport:
        log.info("Update check: %s (%s)", outcome, error)
        return UpdateReport(outcome=outcome, checked_at=now, error=error)

    cached_manifest = cache / _MANIFEST_FILE
    cached_signature = cache / _SIGNATURE_FILE
    conditional: dict[str, str] = {}
    if cached_manifest.is_file() and cached_signature.is_file():
        if state.etag:
            conditional["If-None-Match"] = state.etag
        if state.last_modified:
            conditional["If-Modified-Since"] = state.last_modified

    try:
        got = _fetch(client, MANIFEST_URL, MAX_MANIFEST_BYTES, conditional)
        unchanged = got.status == 304 and bool(conditional)
        if unchanged:
            try:
                raw = _read_capped(cached_manifest, MAX_MANIFEST_BYTES)
                sig = _read_capped(cached_signature, MAX_SIGNATURE_BYTES)
            except OSError as exc:
                # The next check asks for the whole manifest again.
                state.etag = state.last_modified = ""
                return failed(
                    Outcome.UNVERIFIED, f"The cached update information is unreadable ({exc})."
                )
        elif got.status == 200:
            raw = got.body
            sig_got = _fetch(client, SIGNATURE_URL, MAX_SIGNATURE_BYTES, {})
            if sig_got.status != 200:
                return failed(Outcome.REFUSED, _http_refusal(sig_got.status))
            sig = sig_got.body
        else:
            return failed(Outcome.REFUSED, _http_refusal(got.status))
    except httpx.TimeoutException:
        return failed(Outcome.UNREACHABLE, "The update server did not answer in time.")
    except _TooLarge:
        return failed(Outcome.UNVERIFIED, "The update server sent more data than expected.")
    except (httpx.HTTPError, OSError) as exc:
        return failed(Outcome.UNREACHABLE, f"Could not reach the update server ({_brief(exc)}).")

    if cancel is not None and cancel.is_set():
        return failed(Outcome.UNREACHABLE, "The check was cancelled.")
    try:
        signature.verify_detached(raw, sig, key_file=key_file, fingerprint=fingerprint)
    except signature.SignatureError as exc:
        return failed(Outcome.UNVERIFIED, f"Could not verify the update information: {exc}.")
    try:
        manifest = parse_manifest(raw)
    except ManifestError as exc:
        return failed(Outcome.UNVERIFIED, f"Could not verify the update information: {exc}.")
    if state.accepted_generated_at and manifest.generated_at < state.accepted_generated_at:
        return failed(
            Outcome.UNVERIFIED,
            "Could not verify the update information: it is older than information "
            "already seen, so it may be a replay.",
        )

    state.accepted_generated_at = manifest.generated_at
    if not unchanged:
        try:
            paths.atomic_write_bytes(cached_manifest, raw)
            paths.atomic_write_bytes(cached_signature, sig)
            state.etag, state.last_modified = got.etag, got.last_modified
        except OSError as exc:
            log.warning("Could not cache the update manifest: %s", exc)
            state.etag = state.last_modified = ""
    return evaluate(manifest, installed, checked_at=now, unchanged=unchanged)


def evaluate(
    manifest: Manifest,
    installed: Installed,
    *,
    checked_at: datetime.datetime,
    unchanged: bool = False,
) -> UpdateReport:
    """Compare a verified manifest with what is installed. Pure."""
    gui = _status(
        manifest.gui,
        installed.gui_version,
        installed.gui,
        installed,
        unknown_note="This is a source checkout; its version is not compared.",
    )
    daemon = _status(
        manifest.daemon,
        installed.daemon_version,
        installed.daemon,
        installed,
        unknown_note="Not connected to ventulusd, so its version is not known.",
    )
    notes: list[str] = []
    daemon_now = parse_version(installed.daemon_version)
    floor = manifest.gui.daemon_minimum
    if gui.state is VersionState.UPDATE_AVAILABLE and floor and daemon_now and daemon_now < floor:
        notes.append(
            f"Update the daemon first: Ventulus {gui.latest} needs ventulusd "
            f"{format_version(floor)} or newer, and {installed.daemon_version} is running."
        )
    api = manifest.daemon.api_version
    if (
        daemon.state is VersionState.UPDATE_AVAILABLE
        and api is not None
        and api != installed.api_version
    ):
        notes.append(
            f"ventulusd {daemon.latest} needs a newer Ventulus: it speaks API version "
            f"{api} and this Ventulus speaks {installed.api_version}. Update Ventulus "
            "together with it."
        )
    return UpdateReport(
        outcome=Outcome.CHECKED,
        checked_at=checked_at,
        published_at=manifest.generated_at,
        gui=gui,
        daemon=daemon,
        compatibility=tuple(notes),
        unchanged=unchanged,
    )


_PACKAGE_FORMAT = {
    InstallMethod.PACMAN: AssetFormat.PACMAN,
    InstallMethod.DEB: AssetFormat.DEB,
    InstallMethod.RPM: AssetFormat.RPM,
    InstallMethod.TARBALL: AssetFormat.TARBALL,
}

_UPGRADE_COMMAND = {
    InstallMethod.PACMAN: "sudo pacman -Syu",
    InstallMethod.DEB: "sudo apt update && sudo apt upgrade",
    InstallMethod.RPM: "sudo dnf upgrade --refresh",
}

_REPOSITORY_NAME = {
    InstallMethod.PACMAN: "the [ventulus] pacman repository",
    InstallMethod.DEB: "the Ventulus APT repository",
    InstallMethod.RPM: "the Ventulus DNF repository",
}


def _status(
    component: Component,
    installed_text: str | None,
    ownership: Ownership,
    installed: Installed,
    *,
    unknown_note: str,
) -> ComponentStatus:
    latest = component.version_text
    now = parse_version(installed_text)
    if now is None:
        state = VersionState.UNKNOWN
    elif now < component.version:
        state = VersionState.UPDATE_AVAILABLE
    elif now > component.version:
        state = VersionState.AHEAD
    else:
        state = VersionState.UP_TO_DATE
    method = ownership.method
    notes: list[str] = []
    if state is VersionState.UNKNOWN:
        notes.append(unknown_note)

    asset: Asset | None = None
    fmt = _PACKAGE_FORMAT.get(method)
    if fmt is not None:
        choice, asset = select_asset(
            component, fmt, machine=installed.machine, fedora=installed.fedora
        )
        if choice is AssetChoice.UNSUPPORTED_ARCH:
            notes.append(f"This release has no {fmt} package for {installed.machine}.")
        elif choice is AssetChoice.NO_FEDORA_BUILD:
            notes.append(
                f"This release has no build for Fedora {installed.fedora}; dnf will not offer it."
            )
        elif choice is AssetChoice.MISSING:
            notes.append(f"This release has no {fmt} package.")

    handoff: list[str] = []
    if state is VersionState.UPDATE_AVAILABLE:
        if method in _UPGRADE_COMMAND:
            if not ownership.repository_configured:
                handoff.append(
                    f"Add {_REPOSITORY_NAME[method]} first, as described at "
                    f"{REPOSITORY_SETUP_URL}, then run:"
                )
            handoff.append(_UPGRADE_COMMAND[method])
        elif method is InstallMethod.TARBALL and asset is not None:
            handoff.append(
                "Download and verify the new tarball, then install it with the commands shown."
            )
        else:
            handoff.append(f"Release {latest}: {component.release_url}")
    return ComponentStatus(
        project=component.project,
        installed=installed_text,
        latest=latest,
        state=state,
        method=method,
        repository_configured=ownership.repository_configured,
        release_url=component.release_url,
        asset=asset,
        handoff=tuple(handoff),
        notes=tuple(notes),
    )


# ── The tarball download ───────────────────────────────────────────────────


class DownloadError(Exception):
    """The download failed or did not match the manifest; nothing was kept."""


def download_asset(
    asset: Asset,
    dest_dir: Path,
    *,
    client: httpx.Client,
    cancel: threading.Event | None = None,
) -> Path:
    """Download *asset* into *dest_dir*, keeping it only if it matches the manifest.

    The bytes go to a hidden temporary file beside the target; the file gets its
    real name only once its size and SHA-256 equal what the signed manifest says.
    An interrupted, oversized, truncated or altered download is deleted. GitHub
    answers a Release download with a redirect to its asset host, so redirects are
    followed, over HTTPS only.
    """
    if not dest_dir.is_dir():
        raise DownloadError(f"{dest_dir} is not a folder")
    target = dest_dir / asset.name
    fd, tmp_name = tempfile.mkstemp(prefix=f".{asset.name}.", suffix=".part", dir=dest_dir)
    tmp = Path(tmp_name)
    kept = False
    try:
        digest = hashlib.sha256()
        written = 0
        with os.fdopen(fd, "wb") as out:
            with client.stream("GET", asset.url, follow_redirects=True) as response:
                if response.url.scheme != "https":
                    raise DownloadError("the download was redirected away from HTTPS")
                if response.status_code != 200:
                    raise DownloadError(_http_refusal(response.status_code))
                for chunk in response.iter_bytes(_CHUNK):
                    if cancel is not None and cancel.is_set():
                        raise DownloadError("the download was cancelled")
                    written += len(chunk)
                    if written > asset.size:
                        raise DownloadError("the server sent more than the release lists")
                    digest.update(chunk)
                    out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        if written != asset.size:
            raise DownloadError(f"the download stopped early ({written} of {asset.size} bytes)")
        if digest.hexdigest() != asset.sha256:
            raise DownloadError("the file does not match the SHA-256 the release lists")
        os.chmod(tmp, 0o644)
        os.replace(tmp, target)
        kept = True
        return target
    except httpx.TimeoutException as exc:
        raise DownloadError("the download timed out") from exc
    except httpx.HTTPError as exc:
        raise DownloadError(f"the download failed ({_brief(exc)})") from exc
    except OSError as exc:
        raise DownloadError(f"the file could not be written ({exc.strerror or exc})") from exc
    finally:
        if not kept:
            with contextlib.suppress(OSError):
                tmp.unlink()


def tarball_install_commands(asset: Asset, saved: Path) -> str | None:
    """One command line that checks *saved* once more and installs it.

    ``sha256sum -c`` checks the tarball against the signed manifest's digest right
    before root runs anything, and ``install.sh`` then checks every file against
    the tarball's own MANIFEST. The steps are chained with ``&&``, so a failed
    ``cd`` or a file that no longer matches stops the line before ``sudo``. It
    reads the same in bash, zsh and fish 3+.

    None when the folder's path cannot be quoted the same way in all three: a
    backslash is an escape inside fish's single quotes, and a control character
    has no place on a pasted command line.
    """
    folder = str(saved.parent)
    if "\\" in folder or any(ord(ch) < 32 or ord(ch) == 127 for ch in folder):
        return None
    top = asset.name.removesuffix(".tar.gz")
    return " && ".join(
        (
            f"cd {shlex.quote(folder)}",
            f"echo {shlex.quote(f'{asset.sha256}  {asset.name}')} | sha256sum -c",
            f"tar xf {shlex.quote(asset.name)}",
            f"sudo ./{shlex.quote(top)}/install.sh",
        )
    )


def default_download_dir() -> Path:
    downloads = Path.home() / "Downloads"
    return downloads if downloads.is_dir() else Path.home()


# ── helpers ────────────────────────────────────────────────────────────────


def _http_refusal(status: int) -> str:
    if status in (403, 429):
        return f"The update server is limiting requests (HTTP {status}); try again later."
    return f"The update server answered HTTP {status}."


def _brief(exc: BaseException) -> str:
    text = str(exc).strip()
    return (text or type(exc).__name__)[:160]


def _read_capped(path: Path, limit: int) -> bytes:
    with path.open("rb") as f:
        data = f.read(limit + 1)
    if len(data) > limit:
        raise OSError(f"{path.name} is larger than expected")
    return data


def _parse_time(value: object) -> datetime.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.datetime.strptime(value, _TIMESTAMP).replace(tzinfo=datetime.UTC)
    except ValueError:
        return None


def _format_time(value: datetime.datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(datetime.UTC).strftime(_TIMESTAMP)
