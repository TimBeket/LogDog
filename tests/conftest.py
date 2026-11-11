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




_exit_status = {}


def pytest_sessionfinish(session, exitstatus):
    _exit_status["code"] = int(exitstatus)


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config):
    """После тестов — сразу выход с кодом pytest, без финального закрытия Qt и
    Python: на Windows в CI оно иногда висело до таймаута в 20 минут (2 из 6
    прогонов, уже после «N passed»; на Linux и macOS не бывало). Тестам оно
    ничего не даёт, а релизная сборка из-за него падала бы по таймауту."""
    import os
    import sys
    if "code" in _exit_status and os.environ.get("LOGDOG_TESTS_NORMAL_EXIT") != "1":
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(_exit_status["code"])
