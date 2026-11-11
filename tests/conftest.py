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



@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config):
    """Тесты кончились, а процесс не выходит (на Windows в CI висел до таймаута
    в 20 минут) — через минуту стеки всех потоков в вывод и выход с ошибкой:
    видно, что держит, и прогон не ждёт впустую. Отдельный поток, а не
    faulthandler.dump_traceback_later: его pytest отключает на выходе."""
    import os
    import sys
    import threading
    import time
    import traceback

    def watchdog():
        time.sleep(60)
        out = sys.__stderr__ or sys.stderr
        out.write("\n=== Тесты кончились, а процесс не вышел за 60 с. Потоки: ===\n")
        names = {t.ident: t.name for t in threading.enumerate()}
        for ident, frame in sys._current_frames().items():
            out.write(f"\n--- {names.get(ident, '?')} ({ident}) ---\n")
            out.write("".join(traceback.format_stack(frame)))
        out.flush()
        os._exit(3)

    threading.Thread(target=watchdog, name="exit-watchdog", daemon=True).start()
