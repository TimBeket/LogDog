"""Лог диагностики: повторы схлопываются, зависания окна записываются."""
import logging

import pytest

from utils.logger import RepeatFilter


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def log():
    clock = Clock()
    flt = RepeatFilter(window_sec=600, clock=clock)
    lg = logging.getLogger("test-repeat")
    lg.handlers, lg.filters, lg.propagate = [], [], False
    lg.setLevel(logging.DEBUG)
    records = []
    handler = logging.Handler()
    handler.emit = records.append
    lg.addHandler(handler)
    lg.addFilter(flt)
    lg.clock, lg.flt, lg.records = clock, flt, records
    yield lg
    lg.handlers, lg.filters = [], []


def texts(log):
    return [r.getMessage() for r in log.records]


def test_repeats_are_counted_not_written(log):
    """Без iPhone одно и то же шло каждые 3–4 с часами — пишем раз, остальное считаем."""
    for _ in range(100):
        log.warning("Failed to list ios devices: %s", "ConnectionFailedToUsbmuxdError")
        log.clock.t += 4
    assert texts(log) == ["Failed to list ios devices: ConnectionFailedToUsbmuxdError"]
    log.clock.t += 600
    log.warning("Failed to list ios devices: %s", "ConnectionFailedToUsbmuxdError")
    assert texts(log)[-1] == ("Failed to list ios devices: ConnectionFailedToUsbmuxdError"
                              " [повторилось ещё 99 раз за 10 мин]")


def test_interleaved_messages_each_written_once(log):
    for _ in range(10):
        log.warning("Syslog connection lost: X")
        log.debug("Crash watcher: Y")
        log.warning("Failed to list ios devices: Z")
    assert texts(log) == ["Syslog connection lost: X", "Crash watcher: Y", "Failed to list ios devices: Z"]


def test_different_text_is_not_a_repeat(log):
    log.info("filter: a")
    log.info("filter: ab")
    log.warning("filter: a")       # другой уровень — другое сообщение
    assert len(log.records) == 3


def test_repeated_exception_stack_written_once(log):
    for _ in range(5):
        try:
            raise ValueError("boom")
        except ValueError:
            log.exception("Processor thread error")
    assert len(log.records) == 1 and log.records[0].exc_info
    try:
        raise KeyError("other")
    except KeyError:
        log.exception("Processor thread error")   # другая ошибка — со своим стеком
    assert len(log.records) == 2


def test_flush_reports_pending_repeats(log):
    for _ in range(3):
        log.warning("Syslog connection lost: X")
    log.flt.flush(log)
    assert texts(log)[-1] == "Syslog connection lost: X [повторилось ещё 2 раз до выхода]"
    log.flt.flush(log)
    assert len(log.records) == 2                   # второй раз — нечего


def test_ui_stall_is_logged(qtbot, monkeypatch, caplog):
    from core.settings import settings
    from gui import main_window as mw
    for name in ("IosDevicePoller", "UpdaterThread", "IosSyslogReader"):
        monkeypatch.setattr(getattr(mw, name), "start", lambda self: None)
    monkeypatch.setattr(settings, "help_shown", lambda: True)
    w = mw.MainWindow()
    qtbot.addWidget(w)
    try:
        now = [w._stall_last]
        import types   # подменяем часы только главному окну, не всему процессу (фоновым потокам)
        monkeypatch.setattr(mw, "time", types.SimpleNamespace(monotonic=lambda: now[0]))
        with caplog.at_level(logging.WARNING, logger="LogDog"):
            now[0] += 0.3
            w._check_stall()
            assert not caplog.records                # обычный такт
            now[0] += 2.5
            w._check_stall()
            now[0] += 3600
            w._check_stall()                         # сон компьютера — не зависание
        (record,) = caplog.records
        assert record.getMessage().startswith("UI stalled for 2.5 s (entries=0")
    finally:
        w.processor.stop()
        w.processor.wait(2000)
