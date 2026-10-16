"""DEC-499: the opt-in update check, end to end against a mock server and a test key.

Each case of the phase brief: up to date, a newer stable release, a prerelease
never offered, a local version ahead, GUI/daemon mismatches, asset selection per
install method, an unsupported architecture, a missing asset, a malformed
manifest, a bad signature, a wrong fingerprint, offline, a timeout, 403/429, a
304, an interrupted download, a SHA-256 mismatch, a source install, no installed
file changed by a check, and no request at all while the check is off.
"""

from __future__ import annotations

import datetime
import hashlib
import os
import threading
from pathlib import Path

import httpx
import pytest

from tests.update_fixtures import asset_body, encode, installed, manifest_dict, mutated
from ventulus.services import update_check
from ventulus.services.install_ownership import InstallMethod
from ventulus.services.update_check import (
    MANIFEST_URL,
    SIGNATURE_URL,
    CheckState,
    DownloadError,
    Outcome,
    VersionState,
    automatic_check_due,
    check,
    download_asset,
    tarball_install_commands,
)
from ventulus.services.update_manifest import MAX_MANIFEST_BYTES, AssetFormat, parse_manifest

NOW = datetime.datetime(2026, 10, 21, 9, 0, tzinfo=datetime.UTC)


class Server:
    """A mock Pages site serving the manifest and its signature."""

    def __init__(self, signer, manifest: dict | bytes | None = None, *, other_key=False):
        self.signer = signer
        self.requests: list[httpx.Request] = []
        self.overrides: dict[str, object] = {}
        self.etag = '"abc123"'
        self.set_manifest(manifest if manifest is not None else manifest_dict(), other_key)

    def set_manifest(self, manifest: dict | bytes, other_key: bool = False) -> None:
        self.raw = manifest if isinstance(manifest, bytes) else encode(manifest)
        self.sig = self.signer.sign(self.raw, other=other_key)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        override = self.overrides.get(url)
        if isinstance(override, Exception):
            raise override
        if isinstance(override, httpx.Response):
            return override
        if url == MANIFEST_URL:
            if request.headers.get("if-none-match") == self.etag:
                return httpx.Response(304)
            return httpx.Response(200, content=self.raw, headers={"ETag": self.etag})
        if url == SIGNATURE_URL:
            return httpx.Response(200, content=self.sig)
        return httpx.Response(404)

    def client(self) -> httpx.Client:
        return httpx.Client(
            transport=httpx.MockTransport(self.handler),
            headers={"User-Agent": "Ventulus/5.1.0"},
            follow_redirects=False,
        )


@pytest.fixture()
def cache(tmp_path):
    return tmp_path / "cache"


def run_check(server: Server, cache: Path, state: CheckState | None = None, **kw):
    state = state if state is not None else CheckState()
    with server.client() as client:
        report = check(
            kw.pop("inst", installed()),
            client=client,
            state=state,
            cache=cache,
            now=kw.pop("now", NOW),
            key_file=server.signer.key_file,
            fingerprint=server.signer.fingerprint,
        )
    return report, state


# ── versions ────────────────────────────────────────────────────────────────


def test_up_to_date(update_signer, cache):
    report, _ = run_check(Server(update_signer, manifest_dict(gui="5.1.0", daemon="5.1.0")), cache)
    assert report.outcome is Outcome.CHECKED
    assert [c.state for c in report.components] == [VersionState.UP_TO_DATE] * 2
    assert not report.update_available
    assert all(c.handoff == () for c in report.components)


def test_a_newer_stable_release_is_offered(update_signer, cache):
    report, state = run_check(Server(update_signer, manifest_dict(gui="5.2.0")), cache)
    assert report.gui.state is VersionState.UPDATE_AVAILABLE
    assert report.gui.latest == "5.2.0"
    assert report.daemon.state is VersionState.UPDATE_AVAILABLE
    assert report.update_available
    assert report.offer_key == "ventulus=5.2.0;ventulusd=5.2.0"
    assert report.published_at == datetime.datetime(2026, 10, 20, 12, tzinfo=datetime.UTC)
    assert state.accepted_generated_at == report.published_at


def test_a_prerelease_is_never_offered(update_signer, cache):
    server = Server(update_signer, manifest_dict(gui="5.3.0-rc1"))
    report, state = run_check(server, cache)
    assert report.outcome is Outcome.UNVERIFIED
    assert report.components == ()
    assert not report.update_available
    assert state.accepted_generated_at is None


def test_a_local_version_ahead_is_never_offered_a_downgrade(update_signer, cache):
    report, _ = run_check(
        Server(update_signer, manifest_dict(gui="5.1.0", daemon="5.1.0")),
        cache,
        inst=installed(gui_version="5.2.0", daemon_version="6.0.0"),
    )
    assert [c.state for c in report.components] == [VersionState.AHEAD] * 2
    assert not report.update_available
    assert all(c.handoff == () for c in report.components)


def test_the_new_gui_needs_a_newer_daemon(update_signer, cache):
    report, _ = run_check(
        Server(update_signer, manifest_dict(gui="5.2.0", daemon_minimum="5.2.0")),
        cache,
        inst=installed(daemon_version="5.1.0"),
    )
    assert any(note.startswith("Update the daemon first") for note in report.compatibility)
    # The pair is fine once the daemon meets the floor.
    report, _ = run_check(
        Server(update_signer, manifest_dict(gui="5.2.0", daemon_minimum="5.1.0")),
        cache / "b",
        inst=installed(daemon_version="5.1.0"),
    )
    assert report.compatibility == ()


def test_the_new_daemon_needs_a_newer_gui(update_signer, cache):
    report, _ = run_check(
        Server(update_signer, manifest_dict(daemon="6.0.0", api_version=2)),
        cache,
        inst=installed(api_version=1),
    )
    assert any("needs a newer Ventulus" in note for note in report.compatibility)
    report, _ = run_check(
        Server(update_signer, manifest_dict(daemon="6.0.0", api_version=1)),
        cache / "b",
        inst=installed(api_version=1),
    )
    assert report.compatibility == ()


def test_without_a_daemon_connection_its_version_is_unknown(update_signer, cache):
    report, _ = run_check(
        Server(update_signer, manifest_dict()), cache, inst=installed(daemon_version=None)
    )
    assert report.daemon.state is VersionState.UNKNOWN
    assert report.daemon.handoff == ()
    assert report.gui.state is VersionState.UPDATE_AVAILABLE


# ── hand-off and asset selection per install method ──────────────────────────


@pytest.mark.parametrize(
    "method, command",
    [
        (InstallMethod.PACMAN, "sudo pacman -Syu"),
        (InstallMethod.DEB, "sudo apt update && sudo apt upgrade"),
        (InstallMethod.RPM, "sudo dnf upgrade --refresh"),
    ],
)
def test_package_installs_are_handed_to_their_package_manager(
    update_signer, cache, method, command
):
    report, _ = run_check(
        Server(update_signer),
        cache,
        inst=installed(gui=method, daemon=method, configured=True, fedora=44),
    )
    for status in report.components:
        assert status.handoff == (command,)
        assert status.asset is not None and status.asset.format.value == method.value
        assert not status.can_download
    report, _ = run_check(
        Server(update_signer),
        cache / "b",
        inst=installed(gui=method, daemon=method, configured=False, fedora=44),
    )
    for status in report.components:
        assert status.handoff[-1] == command
        assert (
            "first" in status.handoff[0] and update_check.REPOSITORY_SETUP_URL in status.handoff[0]
        )


def test_a_tarball_install_gets_a_verified_download(update_signer, cache):
    report, _ = run_check(
        Server(update_signer),
        cache,
        inst=installed(gui=InstallMethod.TARBALL, daemon=InstallMethod.TARBALL),
    )
    assert report.gui.can_download and report.daemon.can_download
    assert report.gui.asset.name == "ventulus-5.2.0-noarch.tar.gz"
    assert report.daemon.asset.name == "ventulusd-5.2.0-x86_64.tar.gz"


def test_a_source_install_gets_the_version_and_a_link(update_signer, cache):
    report, _ = run_check(
        Server(update_signer),
        cache,
        inst=installed(gui=InstallMethod.SOURCE, daemon=InstallMethod.UNKNOWN),
    )
    for status in report.components:
        assert status.asset is None and not status.can_download
        assert status.handoff == (f"Release 5.2.0: {status.release_url}",)


def test_a_dev_checkout_is_not_compared(update_signer, cache):
    report, _ = run_check(
        Server(update_signer),
        cache,
        inst=installed(gui_version="dev", gui=InstallMethod.SOURCE),
    )
    assert report.gui.state is VersionState.UNKNOWN
    assert report.gui.handoff == ()
    assert report.gui.latest == "5.2.0"


def test_an_unsupported_architecture_gets_no_daemon_package(update_signer, cache):
    report, _ = run_check(
        Server(update_signer),
        cache,
        inst=installed(gui=InstallMethod.TARBALL, daemon=InstallMethod.TARBALL, machine="aarch64"),
    )
    assert report.gui.can_download  # noarch
    assert report.daemon.asset is None and not report.daemon.can_download
    assert any("aarch64" in note for note in report.daemon.notes)


def test_a_missing_asset_is_reported_and_not_offered(update_signer, cache):
    def drop_tarballs(m):
        for project in ("ventulus", "ventulusd"):
            assets = m["components"][project]["assets"]
            m["components"][project]["assets"] = [a for a in assets if a["format"] != "tarball"]

    report, _ = run_check(
        Server(update_signer, mutated(manifest_dict(), drop_tarballs)),
        cache,
        inst=installed(gui=InstallMethod.TARBALL, daemon=InstallMethod.TARBALL),
    )
    for status in report.components:
        assert status.asset is None and not status.can_download
        assert any("no tarball package" in note for note in status.notes)


def test_a_fedora_release_without_a_gui_build(update_signer, cache):
    report, _ = run_check(
        Server(update_signer),
        cache,
        inst=installed(gui=InstallMethod.RPM, daemon=InstallMethod.RPM, fedora=45),
    )
    assert report.gui.asset is None
    assert any("Fedora 45" in note for note in report.gui.notes)
    assert report.daemon.asset is not None  # the daemon .rpm serves every Fedora


# ── trust ────────────────────────────────────────────────────────────────────


def test_a_malformed_manifest_is_never_a_result(update_signer, cache):
    report, _ = run_check(Server(update_signer, b'{"schema": 1, "components": {}}'), cache)
    assert report.outcome is Outcome.UNVERIFIED and report.components == ()
    assert "Could not verify" in report.error
    assert not (cache / "ventulus-updates.json").exists()


def test_a_bad_signature_is_never_a_result(update_signer, cache):
    server = Server(update_signer)
    server.raw = encode(manifest_dict(gui="9.9.9"))  # served, but the signature is the old one
    report, _ = run_check(server, cache)
    assert report.outcome is Outcome.UNVERIFIED and report.components == ()


def test_a_wrong_fingerprint_is_never_a_result(update_signer, cache):
    report, _ = run_check(Server(update_signer, other_key=True), cache)
    assert report.outcome is Outcome.UNVERIFIED and report.components == ()


def test_an_older_manifest_than_one_accepted_is_refused(update_signer, cache):
    state = CheckState()
    newer = manifest_dict(generated_at="2026-10-20T12:00:00Z")
    report, _ = run_check(Server(update_signer, newer), cache, state)
    assert report.outcome is Outcome.CHECKED
    replayed = manifest_dict(gui="5.1.5", generated_at="2026-10-19T12:00:00Z")
    report, _ = run_check(Server(update_signer, replayed), cache / "b", state)
    assert report.outcome is Outcome.UNVERIFIED and "replay" in report.error
    assert state.accepted_generated_at == datetime.datetime(2026, 10, 20, 12, tzinfo=datetime.UTC)
    # The same manifest again is not a replay.
    report, _ = run_check(Server(update_signer, newer), cache / "c", state)
    assert report.outcome is Outcome.CHECKED


def test_an_oversized_answer_is_refused(update_signer, cache):
    server = Server(update_signer)
    server.overrides[MANIFEST_URL] = httpx.Response(200, content=b" " * (MAX_MANIFEST_BYTES + 1))
    report, _ = run_check(server, cache)
    assert report.outcome is Outcome.UNVERIFIED and report.components == ()


# ── the network ──────────────────────────────────────────────────────────────


def test_offline(update_signer, cache):
    server = Server(update_signer)
    server.overrides[MANIFEST_URL] = httpx.ConnectError("Name or service not known")
    report, state = run_check(server, cache)
    assert report.outcome is Outcome.UNREACHABLE and report.components == ()
    assert state.last_attempt == NOW


def test_timeout(update_signer, cache):
    server = Server(update_signer)
    server.overrides[MANIFEST_URL] = httpx.ReadTimeout("timed out")
    report, _ = run_check(server, cache)
    assert report.outcome is Outcome.UNREACHABLE and "in time" in report.error


@pytest.mark.parametrize("status", [403, 429])
def test_rate_limited(update_signer, cache, status):
    server = Server(update_signer)
    server.overrides[MANIFEST_URL] = httpx.Response(status)
    report, _ = run_check(server, cache)
    assert report.outcome is Outcome.REFUSED and report.components == ()
    assert "try again later" in report.error


def test_a_failed_signature_fetch_is_no_result(update_signer, cache):
    server = Server(update_signer)
    server.overrides[SIGNATURE_URL] = httpx.Response(404)
    report, _ = run_check(server, cache)
    assert report.outcome is Outcome.REFUSED and report.components == ()


def test_304_reuses_the_cached_manifest_and_verifies_it_again(update_signer, cache):
    server = Server(update_signer)
    state = CheckState()
    first, _ = run_check(server, cache, state)
    assert first.outcome is Outcome.CHECKED and not first.unchanged
    assert state.etag == server.etag
    server.requests.clear()
    second, _ = run_check(server, cache, state)
    assert second.outcome is Outcome.CHECKED and second.unchanged
    assert second.gui == first.gui
    # One conditional request, and no signature fetch.
    assert [str(r.url) for r in server.requests] == [MANIFEST_URL]
    assert server.requests[0].headers["if-none-match"] == server.etag
    # The cached copy is checked again: altered on disk, it is refused.
    cached = cache / "ventulus-updates.json"
    cached.write_bytes(cached.read_bytes().replace(b"5.2.0", b"9.9.9"))
    third, _ = run_check(server, cache, state)
    assert third.outcome is Outcome.UNVERIFIED and third.components == ()


def test_the_request_carries_nothing_but_the_user_agent(update_signer, cache, monkeypatch):
    """Through the production client: GET, the manifest URL, User-Agent, no cookies."""
    server = Server(update_signer)
    monkeypatch.setattr(update_check, "TRANSPORT", httpx.MockTransport(server.handler))
    with update_check.make_client("5.1.0") as client:
        check(
            installed(),
            client=client,
            state=CheckState(),
            cache=cache,
            now=NOW,
            key_file=update_signer.key_file,
            fingerprint=update_signer.fingerprint,
        )
    assert [(r.method, str(r.url)) for r in server.requests] == [
        ("GET", MANIFEST_URL),
        ("GET", SIGNATURE_URL),
    ]
    for request in server.requests:
        assert request.headers["user-agent"] == "Ventulus/5.1.0"
        assert request.headers["accept-encoding"] == "identity"
        assert set(request.headers) <= {
            "host",
            "accept",
            "accept-encoding",
            "connection",
            "user-agent",
        }


def test_a_cancelled_check_verifies_nothing(update_signer, cache):
    cancel = threading.Event()
    cancel.set()
    server = Server(update_signer)
    with server.client() as client:
        report = check(
            installed(),
            client=client,
            state=CheckState(),
            cache=cache,
            now=NOW,
            key_file=update_signer.key_file,
            fingerprint=update_signer.fingerprint,
            cancel=cancel,
        )
    assert report.outcome is Outcome.UNREACHABLE and report.components == ()
    assert not cache.exists()


def test_the_manifest_lives_on_pages():
    assert MANIFEST_URL == "https://plan-b-development.github.io/pacman-repo/ventulus-updates.json"
    assert SIGNATURE_URL == MANIFEST_URL + ".sig"


# ── state and scheduling ─────────────────────────────────────────────────────


def test_the_automatic_check_is_off_by_default_and_at_most_daily():
    from ventulus.services.app_settings_service import AppSettings

    assert AppSettings().update_check_auto is False
    fresh = CheckState()
    assert not automatic_check_due(fresh, NOW, enabled=False)
    assert automatic_check_due(fresh, NOW, enabled=True)
    recent = CheckState(last_attempt=NOW - datetime.timedelta(hours=23))
    assert not automatic_check_due(recent, NOW, enabled=True)
    old = CheckState(last_attempt=NOW - datetime.timedelta(hours=24))
    assert automatic_check_due(old, NOW, enabled=True)


def test_the_state_round_trips(tmp_path):
    state = CheckState(
        last_attempt=NOW,
        accepted_generated_at=NOW - datetime.timedelta(days=1),
        etag='"x"',
        last_modified="Tue, 20 Oct 2026 12:00:00 GMT",
    )
    update_check.save_state(state, tmp_path)
    assert update_check.load_state(tmp_path) == state
    (tmp_path / "state.json").write_text("{not json")
    assert update_check.load_state(tmp_path) == CheckState()


def test_a_check_changes_no_installed_file(update_signer, tmp_path):
    """Only the cache is written: the package's own files are untouched."""
    import ventulus

    package = Path(ventulus.__file__).resolve().parent

    def snapshot(root: Path) -> dict[str, str]:
        return {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts
        }

    home = Path(os.environ["HOME"])
    before_pkg, before_home = snapshot(package), snapshot(home) if home.exists() else {}
    cache = tmp_path / "cache"
    report, _ = run_check(Server(update_signer), cache)
    assert report.outcome is Outcome.CHECKED
    assert snapshot(package) == before_pkg
    assert (snapshot(home) if home.exists() else {}) == before_home
    assert sorted(p.name for p in cache.iterdir()) == [
        "ventulus-updates.json",
        "ventulus-updates.json.sig",
    ]


# ── the tarball download ─────────────────────────────────────────────────────


@pytest.fixture()
def tarball():
    gui = parse_manifest(encode(manifest_dict())).gui
    return next(a for a in gui.assets if a.format is AssetFormat.TARBALL)


def _download_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def _files(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


def test_a_verified_download_is_kept(tarball, tmp_path):
    assert tarball.name == "ventulus-5.2.0-noarch.tar.gz"
    seen: list[str] = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.host == "github.com":
            return httpx.Response(302, headers={"Location": "https://release-assets.example/x"})
        return httpx.Response(200, content=asset_body(tarball.name))

    with _download_client(handler) as client:
        saved = download_asset(tarball, tmp_path, client=client)
    assert saved == tmp_path / tarball.name
    assert saved.read_bytes() == asset_body(tarball.name)
    assert oct(saved.stat().st_mode & 0o777) == "0o644"
    assert _files(tmp_path) == [tarball.name]
    assert seen[0] == tarball.url


def _refused(tarball, directory: Path, handler, match: str, cancel=None) -> None:
    with _download_client(handler) as client, pytest.raises(DownloadError, match=match):
        download_asset(tarball, directory, client=client, cancel=cancel)
    assert _files(directory) == []  # nothing kept, no partial file left


def test_a_sha256_mismatch_is_refused(tarball, tmp_path):
    body = bytearray(asset_body(tarball.name))
    body[10] ^= 0xFF  # same size, different bytes
    _refused(tarball, tmp_path, lambda r: httpx.Response(200, content=bytes(body)), "SHA-256")


def test_an_interrupted_download_is_refused(tarball, tmp_path):
    class Broken(httpx.SyncByteStream):
        def __iter__(self):
            yield asset_body(tarball.name)[:1000]
            raise httpx.ReadError("connection reset")

    _refused(tarball, tmp_path, lambda r: httpx.Response(200, stream=Broken()), "failed")


def test_a_truncated_download_is_refused(tarball, tmp_path):
    short = asset_body(tarball.name)[:-1]
    _refused(tarball, tmp_path, lambda r: httpx.Response(200, content=short), "stopped early")


def test_an_oversized_download_is_refused(tarball, tmp_path):
    long = asset_body(tarball.name) + b"x"
    _refused(tarball, tmp_path, lambda r: httpx.Response(200, content=long), "more than")


def test_a_redirect_away_from_https_is_refused(tarball, tmp_path):
    def handler(request):
        if request.url.scheme == "https":
            return httpx.Response(302, headers={"Location": "http://plain.example/x"})
        return httpx.Response(200, content=asset_body(tarball.name))

    _refused(tarball, tmp_path, handler, "HTTPS")


def test_an_http_error_is_refused(tarball, tmp_path):
    _refused(tarball, tmp_path, lambda r: httpx.Response(429), "try again later")


def test_a_cancelled_download_is_refused(tarball, tmp_path):
    cancel = threading.Event()
    cancel.set()
    _refused(
        tarball,
        tmp_path,
        lambda r: httpx.Response(200, content=asset_body(tarball.name)),
        "cancelled",
        cancel,
    )


def test_a_download_replaces_nothing_on_failure(tarball, tmp_path):
    existing = tmp_path / tarball.name
    existing.write_bytes(b"the user's own file")
    bad = _download_client(lambda r: httpx.Response(200, content=b"bad"))
    with bad as client, pytest.raises(DownloadError):
        download_asset(tarball, tmp_path, client=client)
    assert existing.read_bytes() == b"the user's own file"
    assert _files(tmp_path) == [tarball.name]


def test_the_install_command_is_one_chained_line(tarball, tmp_path):
    folder = tmp_path / "My Downloads"
    line = tarball_install_commands(tarball, folder / tarball.name)
    assert line == (
        f"cd '{folder}' && echo '{tarball.sha256}  {tarball.name}' | sha256sum -c"
        f" && tar xf {tarball.name} && sudo ./ventulus-5.2.0-noarch/install.sh"
    )


@pytest.mark.parametrize("bad", ["back\\slash", "new\nline", "tab\there"])
def test_no_command_for_a_folder_fish_would_read_differently(tarball, tmp_path, bad):
    assert tarball_install_commands(tarball, tmp_path / bad / tarball.name) is None


def _real_tarball(folder: Path, top: str) -> Path:
    """A tarball holding <top>/install.sh, which leaves a mark when it runs."""
    import tarfile

    src = folder / "src" / top
    src.mkdir(parents=True)
    script = src / "install.sh"
    script.write_text('#!/bin/sh\ntouch "$(dirname "$0")/../INSTALLED"\n')
    script.chmod(0o755)
    path = folder / f"{top}.tar.gz"
    with tarfile.open(path, "w:gz") as tf:
        tf.add(src, arcname=top)
    return path


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
def test_the_line_installs_only_a_file_that_still_matches(tmp_path, shell):
    """Run the line as pasted: sudo is a stub, the folder a scratch one."""
    import dataclasses
    import shutil
    import subprocess

    if shutil.which(shell) is None:
        pytest.skip(f"{shell} is not installed")
    folder = tmp_path / "Down loads"
    folder.mkdir()
    saved = _real_tarball(folder, "ventulus-5.2.0-noarch")
    asset = dataclasses.replace(
        next(
            a
            for a in parse_manifest(encode(manifest_dict())).gui.assets
            if a.format is AssetFormat.TARBALL
        ),
        sha256=hashlib.sha256(saved.read_bytes()).hexdigest(),
    )
    stubs = tmp_path / "bin"
    stubs.mkdir()
    sudo = stubs / "sudo"
    sudo.write_text('#!/bin/sh\nexec "$@"\n')
    sudo.chmod(0o755)
    env = {**os.environ, "PATH": f"{stubs}:{os.environ['PATH']}", "HOME": str(tmp_path)}
    line = tarball_install_commands(asset, saved)
    assert line is not None

    def run() -> int:
        return subprocess.run(
            [shell, "-c", line], cwd=tmp_path, env=env, capture_output=True, timeout=30
        ).returncode

    assert run() == 0
    assert (folder / "INSTALLED").exists()
    # The file changed after the check: the line stops before sudo.
    (folder / "INSTALLED").unlink()
    shutil.rmtree(folder / "ventulus-5.2.0-noarch")
    with saved.open("ab") as f:
        f.write(b"tampered")
    assert run() != 0
    assert not (folder / "INSTALLED").exists()
    assert not (folder / "ventulus-5.2.0-noarch").exists()
