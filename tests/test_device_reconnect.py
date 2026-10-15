"""Отключение и возврат подключённого iPhone: статус сразу, без перезапуска чтения."""
import pytest

from core.settings import settings
from gui import main_window as mw

DEVICE = {"serial": "00008110-AAA", "name": "iPhone QA", "model": "iPhone 14"}


@pytest.fixture
def window(qtbot, monkeypatch):
    monkeypatch.setattr(mw.IosDevicePoller, "start", lambda self: None)
    monkeypatch.setattr(mw.UpdaterThread, "start", lambda self: None)
    monkeypatch.setattr(mw.IosSyslogReader, "start", lambda self: None)
    monkeypatch.setattr(settings, "help_shown", lambda: True)
    monkeypatch.setattr(settings, "last_mode", lambda: "ios")
    monkeypatch.setattr(settings, "set_last_mode", lambda mode: None)
    w = mw.MainWindow()
    qtbot.addWidget(w)
    yield w
    w.processor.stop()
    w.processor.wait(2000)


def test_unplug_shows_waiting_and_replug_does_not_restart_reader(window):
    window._on_devices_updated([DEVICE])
    reader = window.transport_thread
    assert reader is not None and window._connected_serial == DEVICE["serial"]
    window._on_link_state("streaming")
    assert "Логи идут" in window.lbl_connection.text()

    window._on_devices_updated(["Нет подключенных устройств"])
    assert "Нет связи" in window.lbl_connection.text()
    assert "отключено" in window.status_bar.currentMessage()
    assert window.transport_thread is reader          # поток жив и переподключится сам

    window._on_devices_updated([DEVICE])
    assert window.transport_thread is reader          # без перезапуска и вопроса «очистить логи?»
    assert window.device_combo.currentData() == DEVICE["serial"]
