"""DEC-499: the update manifest parser is strict, and asset selection is per machine."""

from __future__ import annotations

import pytest

from tests.update_fixtures import encode, manifest_dict, mutated
from ventulus.services.update_manifest import (
    MAX_MANIFEST_BYTES,
    AssetChoice,
    AssetFormat,
    ManifestError,
    parse_manifest,
    parse_version,
    select_asset,
)


def test_a_published_manifest_parses():
    m = parse_manifest(encode(manifest_dict(gui="5.2.0", daemon="5.3.1", api_version=2)))
    assert m.gui.version == (5, 2, 0)
    assert m.daemon.version == (5, 3, 1)
    assert m.daemon.api_version == 2
    assert m.gui.daemon_minimum == (3, 0, 0)
    assert m.generated_at.isoformat() == "2026-10-20T12:00:00+00:00"
    assert {a.format for a in m.gui.assets} == set(AssetFormat)
    assert {a.format for a in m.daemon.assets} == set(AssetFormat)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("5.2.0", (5, 2, 0)),
        ("10.0.12", (10, 0, 12)),
        ("5.2.0-rc1", None),
        ("5.2.0rc1", None),
        ("5.2", None),
        ("05.2.0", None),
        ("v5.2.0", None),
        ("dev", None),
        (5, None),
    ],
)
def test_only_stable_versions_parse(text, expected):
    assert parse_version(text) == expected


def _comp(m, project):
    return m["components"][project]


DEFECTS = {
    "unknown schema": lambda m: m.update(schema=2),
    "schema as a string": lambda m: m.update(schema="1"),
    "schema as a bool": lambda m: m.update(schema=True),
    "no generated_at": lambda m: m.pop("generated_at"),
    "local-time generated_at": lambda m: m.update(generated_at="2026-10-20T12:00:00+02:00"),
    "a third component": lambda m: m["components"].update(other={}),
    "no daemon": lambda m: m["components"].pop("ventulusd"),
    "prerelease GUI": lambda m: _comp(m, "ventulus").update(version="5.3.0-rc1"),
    "prerelease daemon": lambda m: _comp(m, "ventulusd").update(version="5.3.0-beta.1"),
    "tag disagrees": lambda m: _comp(m, "ventulus").update(tag="v5.1.0"),
    "foreign release_url": lambda m: _comp(m, "ventulus").update(
        release_url="https://example.com/ventulus/releases/tag/v5.2.0"
    ),
    "asset served elsewhere": lambda m: _comp(m, "ventulus")["assets"][0].update(
        url="https://example.com/" + _comp(m, "ventulus")["assets"][0]["name"]
    ),
    "asset from the other project": lambda m: _comp(m, "ventulus")["assets"][0].update(
        url=_comp(m, "ventulus")["assets"][0]["url"].replace("/ventulus/", "/ventulusd/")
    ),
    "path in an asset name": lambda m: _comp(m, "ventulus")["assets"][0].update(
        name="../ventulus-5.2.0-noarch.tar.gz"
    ),
    "short sha256": lambda m: _comp(m, "ventulus")["assets"][0].update(sha256="ab" * 16),
    "upper-case sha256": lambda m: _comp(m, "ventulus")["assets"][0].update(
        sha256=_comp(m, "ventulus")["assets"][0]["sha256"].upper()
    ),
    "zero size": lambda m: _comp(m, "ventulus")["assets"][0].update(size=0),
    "bool size": lambda m: _comp(m, "ventulus")["assets"][0].update(size=True),
    "huge size": lambda m: _comp(m, "ventulus")["assets"][0].update(size=2**40),
    "unknown format": lambda m: _comp(m, "ventulus")["assets"][0].update(format="snap"),
    "format disagrees with the name": lambda m: _comp(m, "ventulus")["assets"][0].update(
        format="deb"
    ),
    "wrong Fedora": lambda m: next(
        a for a in _comp(m, "ventulus")["assets"] if a["format"] == "rpm"
    ).update(fedora=45),
    "Fedora build without fedora": lambda m: next(
        a for a in _comp(m, "ventulus")["assets"] if a["format"] == "rpm"
    ).pop("fedora"),
    "asset listed twice": lambda m: _comp(m, "ventulus")["assets"].append(
        dict(_comp(m, "ventulus")["assets"][0])
    ),
    "no assets": lambda m: _comp(m, "ventulus").update(assets=[]),
    "api_version as a bool": lambda m: _comp(m, "ventulusd").update(api_version=True),
    "negative api_version": lambda m: _comp(m, "ventulusd").update(api_version=-1),
    "no daemon_minimum": lambda m: _comp(m, "ventulus").pop("daemon_minimum"),
    "prerelease daemon_minimum": lambda m: _comp(m, "ventulus").update(daemon_minimum="5.0.0-rc1"),
}


@pytest.mark.parametrize("defect", sorted(DEFECTS))
def test_malformed_manifests_are_refused(defect):
    good = manifest_dict()
    parse_manifest(encode(good))  # positive control: the unmutated manifest parses
    with pytest.raises(ManifestError):
        parse_manifest(encode(mutated(good, DEFECTS[defect])))


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"[]",
        b"not json",
        b"\xff\xfe{}",
        b'{"schema": NaN}',
        b"[" * 100_000 + b"]" * 100_000,
    ],
)
def test_non_manifests_are_refused(raw):
    with pytest.raises(ManifestError):
        parse_manifest(raw)


def test_deep_nesting_is_refused_without_a_recursion_error(json_parser_out_of_stack):
    with pytest.raises(ManifestError, match="nested too deeply"):
        parse_manifest(b"[" * 20_000 + b"]" * 20_000)


def test_an_oversized_manifest_is_refused_before_parsing():
    big = encode(mutated(manifest_dict(), lambda d: d.update(pad="x" * MAX_MANIFEST_BYTES)))
    assert len(big) > MAX_MANIFEST_BYTES
    with pytest.raises(ManifestError, match="larger"):
        parse_manifest(big)


def test_unknown_keys_are_ignored():
    """Additions that do not change meaning stay readable; meaning bumps schema."""
    m = mutated(manifest_dict(), lambda d: d.update(note="hello"))
    assert parse_manifest(encode(m)).gui.version == (5, 2, 0)


# ── asset selection ──────────────────────────────────────────────────────────


@pytest.fixture()
def manifest():
    return parse_manifest(encode(manifest_dict()))


@pytest.mark.parametrize("fmt", list(AssetFormat))
def test_each_format_has_one_asset_per_component_on_x86_64(manifest, fmt):
    for component in (manifest.gui, manifest.daemon):
        choice, asset = select_asset(component, fmt, machine="x86_64", fedora=44)
        assert choice is AssetChoice.FOUND
        assert asset is not None and asset.format is fmt
        assert asset.name.startswith(component.project)


def test_another_architecture_gets_the_gui_but_no_daemon(manifest):
    choice, asset = select_asset(manifest.gui, AssetFormat.TARBALL, machine="aarch64")
    assert choice is AssetChoice.FOUND and asset is not None
    assert asset.name.endswith("-noarch.tar.gz")
    choice, asset = select_asset(manifest.daemon, AssetFormat.TARBALL, machine="aarch64")
    assert (choice, asset) == (AssetChoice.UNSUPPORTED_ARCH, None)


def test_the_gui_rpm_is_per_fedora_release_and_the_daemon_rpm_is_not(manifest):
    builds = sorted(a.fedora for a in manifest.gui.assets if a.format is AssetFormat.RPM)
    assert len(builds) >= 2  # one per Fedora release served
    for fedora in builds:
        choice, asset = select_asset(manifest.gui, AssetFormat.RPM, machine="x86_64", fedora=fedora)
        assert choice is AssetChoice.FOUND and asset is not None and asset.fedora == fedora
        assert asset.name.endswith(f".fc{fedora}.noarch.rpm")
    unbuilt = builds[-1] + 1
    choice, asset = select_asset(manifest.gui, AssetFormat.RPM, machine="x86_64", fedora=unbuilt)
    assert (choice, asset) == (AssetChoice.NO_FEDORA_BUILD, None)
    choice, asset = select_asset(manifest.daemon, AssetFormat.RPM, machine="x86_64", fedora=unbuilt)
    assert choice is AssetChoice.FOUND and asset is not None and asset.fedora is None


def test_a_missing_format_is_reported(manifest):
    from dataclasses import replace

    no_deb = replace(
        manifest.gui,
        assets=tuple(a for a in manifest.gui.assets if a.format is not AssetFormat.DEB),
    )
    assert select_asset(no_deb, AssetFormat.DEB, machine="x86_64") == (AssetChoice.MISSING, None)
