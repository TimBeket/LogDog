import pytest
from pathlib import Path
from PySide6.QtCore import QSettings
from core.settings import Settings


@pytest.fixture
def temp_settings(monkeypatch, tmp_path):
    ini_path = tmp_path / "test_settings.ini"
    monkeypatch.setattr(
        "core.settings.Settings.__init__",
        lambda self: setattr(self, "store", QSettings(str(ini_path), QSettings.IniFormat)),
    )
    return Settings()


def test_default_color_comes_from_theme(temp_settings):
    assert temp_settings.custom_color("color_error") is None


def test_set_get_and_reset_color(temp_settings):
    temp_settings.set_color("color_error", "#000000")
    assert temp_settings.custom_color("color_error") == "#000000"
    temp_settings.reset_colors()
    assert temp_settings.custom_color("color_error") is None


def test_old_shared_default_color_is_not_custom(temp_settings):
    temp_settings.set_color("color_warn", "#ffeb3b")  # прежний жёлтый «по умолчанию»
    assert temp_settings.custom_color("color_warn") is None


def test_default_theme(temp_settings):
    assert temp_settings.theme() == "Dark"


def test_set_and_get_theme(temp_settings):
    temp_settings.set_theme("Light")
    assert temp_settings.theme() == "Light"


def test_invalid_theme_not_saved(temp_settings):
    temp_settings.set_theme("Invalid")
    assert temp_settings.theme() == "Dark"


def test_default_int(temp_settings):
    assert temp_settings.font_size() == 10


def test_set_and_get_int(temp_settings):
    temp_settings.set_font_size(14)
    assert temp_settings.font_size() == 14


def test_restore_last_filter_default(temp_settings):
    assert temp_settings.restore_last_filter() is True


def test_last_filter_persistence(temp_settings):
    temp_settings.set_last_filter("level:error")
    assert temp_settings.last_filter() == "level:error"


def test_help_shown_default_and_persistence(temp_settings):
    assert temp_settings.help_shown() is False
    temp_settings.set_help_shown(True)
    assert temp_settings.help_shown() is True


def test_corrupted_int_falls_back_to_default(temp_settings):
    temp_settings.store.setValue("font_size", "abc")
    assert temp_settings.font_size() == 10
