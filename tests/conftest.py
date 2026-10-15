import pytest
from PySide6.QtWidgets import QApplication
from core.filter import LogFilter
from utils.logger import logger


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def filter_obj():
    f = LogFilter()
    f.set_filter("")
    return f


@pytest.fixture(autouse=True)
def disable_logger(monkeypatch):
    monkeypatch.setattr(logger, "handlers", [])
    monkeypatch.setattr(logger, "setLevel", lambda x: None)


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    """Каждый тест — со своим пустым settings.ini и историей фильтров: иначе
    тесты главного окна читали (и могли менять) настоящие настройки LogDog
    на машине разработчика — например, восстанавливали его последний фильтр."""
    from PySide6.QtCore import QSettings
    from core.settings import settings
    import gui.widgets.filter_history as filter_history
    monkeypatch.setattr(settings, "store", QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat))
    monkeypatch.setattr(filter_history, "get_app_data_dir", lambda: tmp_path)
