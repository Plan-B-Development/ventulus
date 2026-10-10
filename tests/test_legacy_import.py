"""DEC-493: a Control-OFC 4.x user's files come across to Ventulus once."""

from __future__ import annotations

import json
import os

import pytest

from ventulus import paths
from ventulus.services import legacy_import
from ventulus.services.legacy_import import import_dir, import_legacy_user_dirs


@pytest.fixture
def xdg(tmp_path, monkeypatch):
    config, data = tmp_path / "config", tmp_path / "data"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
    return config, data


def _old_install(config, data):
    """What Control-OFC 4.x left: settings naming its own dirs, a profile, a report."""
    old_cfg, old_data = config / "control-ofc", data / "control-ofc"
    (old_cfg / "profiles").mkdir(parents=True)
    (old_cfg / "app_settings.json").write_text(
        json.dumps(
            {
                "profiles_dir_override": f"{old_cfg}/profiles",
                "socket_path": "/run/control-ofc/control-ofc.sock",
                "export_default_dir": "/home/u/control-ofc-exports",
            }
        )
    )
    (old_cfg / "profiles" / "quiet.json").write_text('{"name": "Quiet"}')
    (old_data / "reports").mkdir(parents=True)
    (old_data / "reports" / "r1.json").write_text('{"kind": "control-ofc.pwm-test-report"}')
    return old_cfg, old_data


def test_settings_profiles_and_reports_come_across_with_paths_rewritten(xdg):
    config, data = xdg
    old_cfg, old_data = _old_install(config, data)

    assert import_legacy_user_dirs() == [paths.config_dir(), paths.data_dir()]

    settings = json.loads(paths.app_settings_path().read_text())
    assert settings["profiles_dir_override"] == f"{paths.config_dir()}/profiles"
    assert settings["socket_path"] == "/run/ventulus/ventulus.sock"
    # Only the moved directories are rewritten; a user's own folder name is not.
    assert settings["export_default_dir"] == "/home/u/control-ofc-exports"
    assert (paths.profiles_dir() / "quiet.json").read_text() == '{"name": "Quiet"}'
    # The report's own kind is a format marker the reader accepts, not a path.
    assert (paths.reports_dir() / "r1.json").read_text() == (
        '{"kind": "control-ofc.pwm-test-report"}'
    )
    assert os.stat(paths.config_dir()).st_mode & 0o777 == 0o700
    # The old directories are left exactly as they were.
    assert f"{old_cfg}/profiles" in (old_cfg / "app_settings.json").read_text()
    assert (old_data / "reports" / "r1.json").exists()
    # No staging directory is left behind.
    assert sorted(p.name for p in config.iterdir()) == ["control-ofc", "ventulus"]


def test_runs_once_and_never_into_a_directory_in_use(xdg):
    config, data = xdg
    _old_install(config, data)
    assert import_legacy_user_dirs()

    # A profile the user deletes after the upgrade must not come back.
    (paths.profiles_dir() / "quiet.json").unlink()
    assert import_legacy_user_dirs() == []
    assert not (paths.profiles_dir() / "quiet.json").exists()


def test_the_empty_directories_ensure_dirs_makes_do_not_block_the_import(xdg):
    config, data = xdg
    _old_install(config, data)
    paths.ensure_dirs()  # profiles/, themes/ - empty

    assert paths.config_dir() in import_legacy_user_dirs()
    assert (paths.profiles_dir() / "quiet.json").exists()


def test_a_failed_copy_leaves_no_new_directory_and_no_staging(xdg, caplog):
    config, data = xdg
    old_cfg, _ = _old_install(config, data)
    unreadable = old_cfg / "profiles" / "quiet.json"
    unreadable.chmod(0)
    if os.access(unreadable, os.R_OK):
        pytest.skip("running as root: an unreadable file cannot be modelled")
    try:
        imported = import_legacy_user_dirs()
    finally:
        unreadable.chmod(0o644)

    assert paths.config_dir() not in imported
    assert not paths.config_dir().exists()
    assert sorted(p.name for p in config.iterdir()) == ["control-ofc"]
    assert "Could not import Control-OFC files" in caplog.text
    # The next start tries again, and succeeds.
    assert paths.config_dir() in import_legacy_user_dirs()


def test_no_old_directory_is_a_no_op(tmp_path):
    assert import_dir(tmp_path / "control-ofc", tmp_path / "ventulus") is False
    assert not (tmp_path / "ventulus").exists()


def test_main_imports_before_it_creates_any_directory(monkeypatch):
    """The wiring: ensure_dirs() and everything after it write into the new dirs."""
    from ventulus import main as main_mod

    calls = []

    class Stop(Exception):
        pass

    def fake_ensure_dirs():
        calls.append("ensure_dirs")
        raise Stop

    monkeypatch.setattr(main_mod, "import_legacy_user_dirs", lambda: calls.append("import") or [])
    monkeypatch.setattr(main_mod, "ensure_dirs", fake_ensure_dirs)
    with pytest.raises(Stop):
        main_mod.main()
    assert calls == ["import", "ensure_dirs"]


def test_legacy_name_is_the_sibling_of_each_new_directory(xdg):
    for new in (paths.config_dir(), paths.data_dir()):
        assert new.name == "ventulus"
        assert new.with_name(legacy_import.LEGACY_APP).name == "control-ofc"
