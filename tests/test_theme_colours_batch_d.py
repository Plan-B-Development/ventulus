"""GUI audit 2026-10-14, batch D: theme and series colours.

- Apply Theme Globally handed the editor's own tokens to the app, so edits made
  afterwards, never applied, reached ``active_theme()`` readers.
- The Theme page never re-read what Settings changes: a moved themes folder
  (Load then raised ``FileNotFoundError``), imported themes, an imported card size.
- Export ignored the font controls that Save and Apply write.
- G-14: importing a theme replaced a same-named file without asking (Theme page
  and Settings ▸ Import Config).
- Settings ▸ Reset colours (and Remove, and the memory id re-key) wrote
  ``series_colors`` but the Dashboard chart and rail kept their own copy.
- A series' default colour came from ``hash(key)``, salted per process.
- The rail swatches kept the old palette after a theme switch.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QColorDialog, QMessageBox, QPushButton

from ventulus.api.models import SensorReading
from ventulus.paths import set_path_overrides, themes_dir
from ventulus.services.history_store import HistoryStore
from ventulus.services.series_selection import SeriesSelectionModel
from ventulus.ui.pages.theme_page import ThemePage
from ventulus.ui.theme import ThemeTokens, default_dark_theme, load_theme, save_theme
from ventulus.ui.widgets.timeline_chart import TimelineChart

CPU_KEY = "sensor:cpu0"


@pytest.fixture(autouse=True)
def _clear_path_overrides():
    set_path_overrides()
    yield
    set_path_overrides()


@pytest.fixture
def restore_app_theme(qtbot):
    """Save/restore everything ``apply_theme`` mutates (as in test_theme_system.py)."""
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication

    from ventulus.ui import theme as theme_mod

    app = QApplication.instance()
    saved = (QPalette(app.palette()), app.styleSheet(), app.font(), theme_mod._active_theme)
    try:
        yield app
    finally:
        app.setPalette(saved[0])
        app.setStyleSheet(saved[1])
        app.setFont(saved[2])
        theme_mod._active_theme = saved[3]


def _theme_page(qtbot, settings_service) -> ThemePage:
    page = ThemePage(settings_service=settings_service)
    qtbot.addWidget(page)
    return page


def _write_theme(path: Path, name: str, accent: str = "#123456") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tokens = ThemeTokens()
    tokens.name = name
    tokens.accent_primary = accent
    save_theme(tokens, path)


def _click(page, name: str) -> None:
    btn = page.findChild(QPushButton, name)
    assert btn is not None, name
    btn.click()


def _cpu() -> SensorReading:
    return SensorReading(
        id="cpu0", kind="cpu_temp", label="Tctl", value_c=50.0, source="hwmon", chip_name="k10temp"
    )


# ── #12: Apply hands the app a copy ──────────────────────────────────────────


class TestApplyHandsOutACopy:
    def test_edits_after_apply_do_not_reach_the_applied_theme(self, qtbot, settings_service):
        page = _theme_page(qtbot, settings_service)
        editor = page._theme_editor
        editor._hex_inputs["accent_primary"].setText("#112233")
        editor._hex_inputs["accent_primary"].editingFinished.emit()
        editor._series_hex_inputs[0].setText("#223344")
        editor._series_hex_inputs[0].editingFinished.emit()

        with qtbot.waitSignal(page.theme_changed) as blocker:
            _click(page, "Settings_Btn_applyThemeToApp")
        applied = blocker.args[0]
        # What was edited before Apply is what was applied.
        assert applied.accent_primary == "#112233"
        assert applied.chart_series[0] == "#223344"

        # Edits nobody applies — a scalar token and a chart-series slot, which is
        # written into the list in place (a shallow copy would still share it).
        editor._hex_inputs["accent_primary"].setText("#445566")
        editor._hex_inputs["accent_primary"].editingFinished.emit()
        editor._series_hex_inputs[0].setText("#556677")
        editor._series_hex_inputs[0].editingFinished.emit()
        assert editor.tokens.accent_primary == "#445566"  # the edit landed in the editor

        assert applied.accent_primary == "#112233"
        assert applied.chart_series[0] == "#223344"

    def test_editor_does_not_edit_the_tokens_it_was_given(self, qtbot, settings_service):
        page = _theme_page(qtbot, settings_service)
        given = default_dark_theme()
        original = given.accent_primary
        page._theme_editor.set_tokens(given)
        page._theme_editor._hex_inputs["accent_primary"].setText("#ABCDEF")
        page._theme_editor._hex_inputs["accent_primary"].editingFinished.emit()

        assert page._theme_editor.tokens.accent_primary == "#ABCDEF"
        assert given.accent_primary == original


# ── Export carries the font controls ────────────────────────────────────────


def test_export_writes_the_font_controls(qtbot, settings_service, tmp_path, monkeypatch):
    page = _theme_page(qtbot, settings_service)
    target_size = 14
    assert page._theme_editor.tokens.base_font_size_pt != target_size  # precondition
    page._font_combo.setCurrentIndex(0)  # "(System Default)" → ""
    page._font_size_spin.setValue(target_size)
    out = tmp_path / "exported.json"
    monkeypatch.setattr(
        "ventulus.ui.pages.theme_page.QFileDialog.getSaveFileName",
        lambda *a, **k: (str(out), ""),
    )

    _click(page, "Settings_Btn_exportTheme")

    data = json.loads(out.read_text())
    assert data["base_font_size_pt"] == target_size
    assert data["font_family"] == ""


# ── #13: the Theme page re-reads what Settings changes ──────────────────────


class TestThemePageFollowsSettings:
    def test_a_moved_themes_folder_is_followed_and_load_works(
        self, qtbot, settings_service, tmp_path
    ):
        old = themes_dir() / "mine.json"
        _write_theme(old, "Mine", accent="#13579b")
        page = _theme_page(qtbot, settings_service)
        page._theme_combo.setCurrentIndex(page._theme_combo.findText("Mine"))

        # Settings ▸ Themes folder ▸ Browse ▸ "Yes, move" — files and override.
        new_dir = tmp_path / "moved-themes"
        new_dir.mkdir()
        shutil.move(str(old), str(new_dir / "mine.json"))
        set_path_overrides(themes_dir=str(new_dir))

        page.show()  # arriving on the page

        assert page._theme_combo.currentData() == str(new_dir / "mine.json")
        _click(page, "Settings_Btn_applyTheme")
        assert page._theme_editor.tokens.accent_primary == "#13579b"
        assert "loaded" in page._status_label.text()

    def test_a_theme_added_elsewhere_is_listed_on_arrival(self, qtbot, settings_service):
        page = _theme_page(qtbot, settings_service)
        assert page._theme_combo.findText("Imported") == -1
        _write_theme(themes_dir() / "imported.json", "Imported")

        page.show()

        assert page._theme_combo.findText("Imported") >= 0

    def test_load_of_a_vanished_file_reports_instead_of_raising(self, qtbot, settings_service):
        path = themes_dir() / "gone.json"
        _write_theme(path, "Gone")
        page = _theme_page(qtbot, settings_service)
        page._theme_combo.setCurrentIndex(page._theme_combo.findText("Gone"))
        path.unlink()

        _click(page, "Settings_Btn_applyTheme")

        assert page._status_label.text().startswith("Could not load theme 'Gone'")
        assert page._theme_combo.findText("Gone") == -1  # the list was re-read

    def test_an_imported_card_size_is_shown_on_arrival(self, qtbot, settings_service):
        settings_service.update(card_size="compact")
        page = _theme_page(qtbot, settings_service)
        assert page._card_size_combo.currentData() == "compact"
        settings_service.update(card_size="large")  # Settings ▸ Import Config

        page.show()

        assert page._card_size_combo.currentData() == "large"

    def test_a_card_size_picked_here_survives_a_visit_elsewhere(self, qtbot, settings_service):
        settings_service.update(card_size="compact")
        page = _theme_page(qtbot, settings_service)
        page.show()
        page._card_size_combo.setCurrentIndex(page._card_size_combo.findData("large"))

        page.hide()
        page.show()

        assert page._card_size_combo.currentData() == "large"
        assert settings_service.settings.card_size == "compact"  # not applied yet


# ── G-14: an import asks before replacing a theme ───────────────────────────


class TestThemePageImportAsksBeforeReplacing:
    def _import(self, page, monkeypatch, source: Path) -> None:
        monkeypatch.setattr(
            "ventulus.ui.pages.theme_page.QFileDialog.getOpenFileName",
            lambda *a, **k: (str(source), ""),
        )
        _click(page, "Settings_Btn_importTheme")

    def _record_questions(self, monkeypatch, answer) -> list:
        asked: list = []

        def question(*args, **kwargs):
            asked.append(args)
            return answer

        monkeypatch.setattr(QMessageBox, "question", question)
        return asked

    def test_cancel_keeps_the_existing_theme(self, qtbot, settings_service, tmp_path, monkeypatch):
        existing = themes_dir() / "mine.json"
        _write_theme(existing, "Mine", accent="#111111")
        source = tmp_path / "incoming" / "mine.json"
        _write_theme(source, "Theirs", accent="#222222")
        page = _theme_page(qtbot, settings_service)
        asked = self._record_questions(monkeypatch, QMessageBox.StandardButton.Cancel)

        self._import(page, monkeypatch, source)

        assert len(asked) == 1
        assert load_theme(existing).accent_primary == "#111111"
        assert "cancelled" in page._status_label.text()

    def test_yes_replaces_it(self, qtbot, settings_service, tmp_path, monkeypatch):
        existing = themes_dir() / "mine.json"
        _write_theme(existing, "Mine", accent="#111111")
        source = tmp_path / "incoming" / "mine.json"
        _write_theme(source, "Theirs", accent="#222222")
        page = _theme_page(qtbot, settings_service)
        asked = self._record_questions(monkeypatch, QMessageBox.StandardButton.Yes)

        self._import(page, monkeypatch, source)

        assert len(asked) == 1
        assert load_theme(existing).accent_primary == "#222222"
        assert page._theme_combo.findText("Theirs") >= 0

    def test_no_prompt_without_a_clash_or_onto_itself(
        self, qtbot, settings_service, tmp_path, monkeypatch
    ):
        page = _theme_page(qtbot, settings_service)
        asked = self._record_questions(monkeypatch, QMessageBox.StandardButton.Cancel)
        source = tmp_path / "incoming" / "fresh.json"
        _write_theme(source, "Fresh")

        self._import(page, monkeypatch, source)
        assert (themes_dir() / "fresh.json").exists()
        # The same file again is now in the folder: importing it onto itself.
        self._import(page, monkeypatch, themes_dir() / "fresh.json")

        assert asked == []
        assert page._status_label.text() == "Theme 'Fresh' imported"


class TestSettingsImportAsksBeforeReplacingThemes:
    def _import_config(self, qtbot, settings_service, tmp_path, monkeypatch):
        from ventulus.ui.pages.settings_page import SettingsPage

        theme = ThemeTokens()
        theme.name = "Mine"
        theme.accent_primary = "#222222"
        from dataclasses import asdict

        src = tmp_path / "config.json"
        src.write_text(json.dumps({"export_version": 1, "themes": {"mine": asdict(theme)}}))
        page = SettingsPage(settings_service=settings_service)
        qtbot.addWidget(page)
        monkeypatch.setattr(
            "ventulus.ui.pages.settings_page.QFileDialog.getOpenFileName",
            lambda *a, **k: (str(src), ""),
        )
        _click(page, "Settings_Btn_importConfig")
        return page

    def test_a_clash_is_kept_unless_confirmed(self, qtbot, settings_service, tmp_path, monkeypatch):
        existing = themes_dir() / "mine.json"
        _write_theme(existing, "Mine", accent="#111111")
        # conftest answers every question No.
        page = self._import_config(qtbot, settings_service, tmp_path, monkeypatch)
        assert page is not None
        assert load_theme(existing).accent_primary == "#111111"

    def test_a_confirmed_clash_is_replaced(self, qtbot, settings_service, tmp_path, monkeypatch):
        existing = themes_dir() / "mine.json"
        _write_theme(existing, "Mine", accent="#111111")
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
        page = self._import_config(qtbot, settings_service, tmp_path, monkeypatch)
        assert page is not None
        assert load_theme(existing).accent_primary == "#222222"


# ── #14: colour changes made in Settings reach the chart ────────────────────


class TestSettingsColourWritersNotifyTheChart:
    def test_remove_orphans_emits_the_kept_colours(self, qtbot, settings_service, app_state):
        from ventulus.ui.pages.settings_page import SettingsPage

        settings_service.update(series_colors={CPU_KEY: "#111111", "sensor:gone": "#222222"})
        app_state.set_sensors([_cpu()])
        page = SettingsPage(state=app_state, settings_service=settings_service)
        qtbot.addWidget(page)

        with qtbot.waitSignal(page.series_colors_changed) as blocker:
            _click(page, "Settings_Btn_pruneChartOrphans")

        assert blocker.args[0] == {CPU_KEY: "#111111"}

    def test_reset_colours_reaches_the_dashboard_chart_and_rail(
        self, qtbot, settings_service, profile_service, monkeypatch
    ):
        from ventulus.ui.main_window import MainWindow

        w = MainWindow(settings_service=settings_service, profile_service=profile_service)
        qtbot.addWidget(w)
        w._state.set_sensors([_cpu()])
        dash = w.dashboard_page
        row = dash._sensor_panel._sensor_items["cpu0"]

        # Pick a colour on the rail, the real way.
        monkeypatch.setattr(QColorDialog, "exec", lambda self: 1)
        monkeypatch.setattr(QColorDialog, "currentColor", lambda self: QColor("#abcdef"))
        dash._sensor_panel._on_item_clicked(row, 2)
        assert dash._chart.color_for_key(CPU_KEY) == "#abcdef"
        assert settings_service.settings.series_colors == {CPU_KEY: "#abcdef"}

        w.settings_page._refresh_reset_buttons()  # as arriving on the page does
        _click(w.settings_page, "Settings_Btn_resetSeriesColors")

        palette_default = TimelineChart(HistoryStore())
        qtbot.addWidget(palette_default)
        expected = palette_default.color_for_key(CPU_KEY)
        assert expected != "#abcdef"
        assert dash._chart.color_for_key(CPU_KEY) == expected
        assert row.background(2).color().name() == QColor(expected).name()


def test_replacing_overrides_repaints_drawn_series(qtbot):
    history = HistoryStore()
    selection = SeriesSelectionModel()
    chart = TimelineChart(history, selection=selection, color_overrides={CPU_KEY: "#abcdef"})
    qtbot.addWidget(chart)
    now = history.now()
    for i in range(5):
        history._append(CPU_KEY, now - (5 - i), 40.0 + i)
    selection.update_known_keys([CPU_KEY])
    selection.set_visible(CPU_KEY, True)
    chart.update_chart()
    assert chart._temp_items[CPU_KEY].opts["pen"].color().name() == "#abcdef"

    chart.replace_color_overrides({})

    default = chart.color_for_key(CPU_KEY)
    assert default != "#abcdef"
    assert chart._temp_items[CPU_KEY].opts["pen"].color().name() == QColor(default).name()
    dot_brush = chart._latest_items[CPU_KEY].opts["brush"]
    assert dot_brush.color().name() == QColor(default).name()


# ── Default series colours are the same in every process ────────────────────

_COLOUR_PROBE = """
import json, sys
from PySide6.QtWidgets import QApplication
app = QApplication([])
from ventulus.services.history_store import HistoryStore
from ventulus.ui.widgets.timeline_chart import TimelineChart
chart = TimelineChart(HistoryStore())
print(json.dumps([chart.color_for_key(k) for k in json.loads(sys.argv[1])]))
"""


def test_default_series_colours_do_not_depend_on_the_hash_seed():
    keys = [f"sensor:hwmon{i}:temp{i}" for i in range(6)] + [
        f"fan:openfan:ch0{i}:rpm" for i in range(6)
    ]
    src = str(Path(__file__).resolve().parents[1] / "src")

    def colours(seed: str) -> list[str]:
        env = {
            **os.environ,
            "PYTHONHASHSEED": seed,
            "QT_QPA_PLATFORM": "offscreen",
            "PYTHONPATH": src,
        }
        out = subprocess.run(
            [sys.executable, "-c", _COLOUR_PROBE, json.dumps(keys)],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        return json.loads(out.stdout.strip().splitlines()[-1])

    first = colours("1")
    assert len(set(first)) > 1  # the keys spread over the palette
    assert colours("2") == first


# ── Rail swatches follow a theme switch ─────────────────────────────────────


def test_rail_swatches_follow_a_theme_switch(
    qtbot, settings_service, profile_service, restore_app_theme
):
    from ventulus.ui.main_window import MainWindow

    w = MainWindow(settings_service=settings_service, profile_service=profile_service)
    qtbot.addWidget(w)
    w._state.set_sensors([_cpu()])
    dash = w.dashboard_page
    row = dash._sensor_panel._sensor_items["cpu0"]
    before = row.background(2).color().name()

    tokens = default_dark_theme()
    tokens.chart_series = ["#0f0f0f"] * len(tokens.chart_series)
    w.theme_page._theme_editor.set_tokens(tokens)
    _click(w.theme_page, "Settings_Btn_applyThemeToApp")

    assert before != "#0f0f0f"  # precondition: the swatch had to move
    assert dash._chart.color_for_key(CPU_KEY) == "#0f0f0f"
    assert row.background(2).color().name() == "#0f0f0f"


def test_rail_swatch_refresh_does_not_emit_item_changed(qtbot, app_state):
    """Painting a swatch is an item change; the refresh must not feed the
    rail's checkbox handler (the G-19 storm)."""
    from ventulus.ui.widgets.sensor_series_panel import SensorSeriesPanel

    panel = SensorSeriesPanel(SeriesSelectionModel(), state=app_state)
    qtbot.addWidget(panel)
    chart = TimelineChart(HistoryStore())
    qtbot.addWidget(chart)
    panel.set_chart(chart)
    panel.update_sensors([_cpu()])
    changed: list = []
    panel._tree.itemChanged.connect(lambda *a: changed.append(a))

    chart.replace_color_overrides({CPU_KEY: "#abcdef"})
    panel.refresh_swatches()

    assert panel._sensor_items["cpu0"].background(2).color().name() == "#abcdef"
    assert changed == []


def test_swatch_rows_carry_their_series_key(qtbot, app_state):
    """refresh_swatches reads each row's key from its UserRole data."""
    from ventulus.ui.widgets.sensor_series_panel import SensorSeriesPanel

    panel = SensorSeriesPanel(SeriesSelectionModel(), state=app_state)
    qtbot.addWidget(panel)
    panel.update_sensors([_cpu()])
    assert panel._sensor_items["cpu0"].data(0, Qt.ItemDataRole.UserRole) == CPU_KEY
