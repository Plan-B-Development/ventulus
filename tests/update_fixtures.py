"""Manifests and installs for the update-check tests (DEC-499).

``manifest_dict`` builds a format-1 manifest shaped exactly as pacman-repo's
``.github/scripts/manifest.py`` writes one: the release.yml asset sets of both
projects, the URLs it derives, sorted assets.
"""

from __future__ import annotations

import copy
import hashlib
import json

from ventulus.services.install_ownership import InstallMethod, Ownership
from ventulus.services.update_check import Installed

OWNER = "Plan-B-Development"


def _assets(project: str, version: str, names: list[str]) -> list[dict]:
    out = []
    for name in names:
        fmt = (
            "pacman"
            if name.endswith(".pkg.tar.zst")
            else "deb"
            if name.endswith(".deb")
            else "rpm"
            if name.endswith(".rpm")
            else "tarball"
        )
        body = asset_body(name)
        entry = {
            "name": name,
            "format": fmt,
            "sha256": hashlib.sha256(body).hexdigest(),
            "size": len(body),
            "url": f"https://github.com/{OWNER}/{project}/releases/download/v{version}/{name}",
        }
        if ".fc" in name:
            entry["fedora"] = int(name.split(".fc", 1)[1].split(".", 1)[0])
        out.append(entry)
    return sorted(out, key=lambda a: a["name"])


def asset_body(name: str) -> bytes:
    """The bytes a test serves for an asset: deterministic, a few KB."""
    return (name.encode() + b"\n") * 200


def manifest_dict(
    *,
    gui: str = "5.2.0",
    daemon: str = "5.2.0",
    api_version: int = 1,
    daemon_minimum: str = "3.0.0",
    generated_at: str = "2026-10-20T12:00:00Z",
) -> dict:
    d_names = [
        f"ventulusd-{daemon}-1-x86_64.pkg.tar.zst",
        f"ventulusd_{daemon}-1_amd64.deb",
        f"ventulusd-{daemon}-1.x86_64.rpm",
        f"ventulusd-{daemon}-x86_64.tar.gz",
    ]
    g_names = [
        f"ventulus-{gui}-1-any.pkg.tar.zst",
        f"ventulus_{gui}-1_all.deb",
        f"ventulus-{gui}-1.fc44.noarch.rpm",
        f"ventulus-{gui}-1.fc45.noarch.rpm",
        f"ventulus-{gui}-noarch.tar.gz",
    ]
    return {
        "schema": 1,
        "generated_at": generated_at,
        "components": {
            "ventulusd": {
                "version": daemon,
                "tag": f"v{daemon}",
                "release_url": f"https://github.com/{OWNER}/ventulusd/releases/tag/v{daemon}",
                "api_version": api_version,
                "assets": _assets("ventulusd", daemon, d_names),
            },
            "ventulus": {
                "version": gui,
                "tag": f"v{gui}",
                "release_url": f"https://github.com/{OWNER}/ventulus/releases/tag/v{gui}",
                "daemon_minimum": daemon_minimum,
                "assets": _assets("ventulus", gui, g_names),
            },
        },
    }


def encode(manifest: dict) -> bytes:
    return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()


def mutated(manifest: dict, mutate) -> dict:
    copied = copy.deepcopy(manifest)
    mutate(copied)
    return copied


def installed(
    *,
    gui_version: str = "5.1.0",
    daemon_version: str | None = "5.1.0",
    gui: InstallMethod = InstallMethod.PACMAN,
    daemon: InstallMethod = InstallMethod.PACMAN,
    configured: bool = True,
    machine: str = "x86_64",
    fedora: int | None = None,
    api_version: int = 1,
) -> Installed:
    return Installed(
        gui_version=gui_version,
        daemon_version=daemon_version,
        gui=Ownership(gui, configured),
        daemon=Ownership(daemon, configured),
        machine=machine,
        fedora=fedora,
        api_version=api_version,
    )
