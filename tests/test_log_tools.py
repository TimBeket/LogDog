"""Окно логов: схлопывание повторов, маркеры, колонка времени, отслеживание, открытие файла."""
import pytest
from PySide6.QtWidgets import QInputDialog

from core.settings import settings
from gui import main_window as mw

PING = "Oct 15 16:04:{:02d} iPhone-QA MyGame(UnityFramework)[2438] <Notice>: [INTERNET_CHECKER] AVAILABLE:True"
ERR = "Oct 15 16:05:{:02d} iPhone-QA game[1] <Error>: Failed to fetch remote config: timeout"


@pytest.fixture
def window(qtbot, monkeypatch, tmp_path):
    for name in ("IosDevicePoller", "UpdaterThread", "IosSyslogReader"):
        monkeypatch.setattr(getattr(mw, name), "start", lambda self: None)
    monkeypatch.setattr(settings, "help_shown", lambda: True)
    w = mw.MainWindow()
    qtbot.addWidget(w)
    yield w
    w.processor.stop()
    w.processor.wait(2000)


def feed(w, lines):
    w._on_blocks_processed([{"raw": l, "props": w.filter_obj.extract_props(l)} for l in lines])


def lines(w):
    return [l for l in w.log_display.toPlainText().split("\n") if l]


def test_repeats_collapse_ignoring_time(window):
    feed(window, [PING.format(1), PING.format(11)])
    feed(window, [PING.format(21)])
    feed(window, [ERR.format(1), PING.format(31)])
    shown = lines(window)
    assert shown[0].endswith("AVAILABLE:True  ×3")
    assert shown[1].startswith("Oct 15 16:05:01") and shown[2].endswith("AVAILABLE:True")
    assert len(shown) == 3 and len(window._entries) == 5
    window.btn_collapse.setChecked(False)  # выключили — все строки как есть
    assert len(lines(window)) == 5
    window.btn_collapse.setChecked(True)   # перестроение схлопывает так же
    assert lines(window)[0].endswith("×3")


def test_marker_named_and_never_filtered(window, monkeypatch):
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("покупка No Ads", True)))
    feed(window, [PING.format(1)])
    window._add_marker()
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("", True)))
    window._add_marker()
    window.filter_obj.set_filter("level:error")
    window._reapply_filter_to_history()
    assert [l.split(" ", 2)[2] for l in lines(window)] == ["══ покупка No Ads ══", "══ Шаг 2 ══"]


def test_time_delta_stored_for_gutter(window):
    window.btn_collapse.setChecked(False)
    feed(window, [PING.format(1), PING.format(11), ERR.format(1)])
    doc = window.log_display.document()
    assert [doc.findBlockByNumber(i).userState() for i in range(3)] == [-1, 10, 50]


def test_watch_counts_and_jumps_to_last(window):
    window.btn_collapse.setChecked(False)
    window._watch.add("timeout OR revenue")
    feed(window, [PING.format(1), ERR.format(1), PING.format(2), ERR.format(9), PING.format(3)])
    rule = window._watch.rules[0]
    assert rule.count == 2
    window._jump_to_entry(rule.last_entry_id)
    assert window.log_display.textCursor().blockNumber() == 3
    assert not window.chk_auto_scroll.isChecked()


def test_open_log_file(window, qtbot, tmp_path, monkeypatch):
    path = tmp_path / "saved.log"
    path.write_text("\n".join([PING.format(1), ERR.format(1), "  at Player.Update ()", PING.format(2)]), encoding="utf-8")
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(path), "")))
    window._open_log_file()
    qtbot.waitUntil(lambda: len(window._entries) == 3, timeout=3000)
    window._file_loader.wait(2000)
    assert "at Player.Update" in window._entries[1]["raw"]   # многострочная запись — одна


def _unity_mode(window, monkeypatch):
    monkeypatch.setattr(mw.GameDiscovery, "start", lambda self: None)
    monkeypatch.setattr(mw.UnityTCPReader, "start", lambda self: None)
    window.mode_combo.setCurrentIndex(window.mode_combo.findData("unity"))


USB_IPHONE = {"via": "usb", "serial": "00008140-TEST", "device": "iPhone QA", "port": None,
              "ip": "", "project": "", "platform": "iPhone"}


def test_unity_list_shows_targets_and_manual_ip(window, monkeypatch):
    _unity_mode(window, monkeypatch)
    wifi = {"via": "wifi", "ip": "192.168.1.7", "port": 55376, "project": "My Game", "platform": "Android"}
    window._on_games_changed([dict(USB_IPHONE, serial="A", device="iPhone A"),
                              dict(USB_IPHONE, serial="B", device="iPhone B", port=55000, project="My Game"), wifi])
    titles = [window.unity_combo.itemText(i) for i in range(window.unity_combo.count())]
    assert "iPhone A  ·  по USB" in titles
    assert "iPhone B  ·  по USB  —  My Game запущена" in titles
    assert "My Game  ·  Android  ·  192.168.1.7" in titles and titles[-1] == "Ввести IP вручную…"
    assert not window._is_connected            # два iPhone — сами не выбираем
    window.unity_combo.setCurrentIndex(titles.index("Ввести IP вручную…"))
    window._on_unity_target_chosen(window.unity_combo.currentIndex())
    assert window.ip_input.isVisibleTo(window) and not window._is_connected
    window.ip_input.setText("192.168.1.50")
    window._connect_unity(auto=False)
    assert window.transport_thread.target_ip == "192.168.1.50"


def test_single_iphone_by_usb_is_armed_automatically(window, monkeypatch):
    """Один iPhone по кабелю — подключаемся сами и ждём игру: логи с самого запуска."""
    _unity_mode(window, monkeypatch)
    window._on_games_changed([USB_IPHONE])
    assert window._is_connected and window.transport_thread.usb_serial == "00008140-TEST"
    window._toggle_connection()                 # «стоп»
    assert not window._is_connected
    window._on_games_changed([USB_IPHONE])      # и не подключаемся снова сами
    assert not window._is_connected


def test_pause_counter_shows_queue_not_total(window):
    feed(window, [ERR.format(1), PING.format(2)])
    window.btn_pause.setChecked(True)
    assert window.lbl_line_count.text() == "Показано 2 · пауза"
    window._clear_logs()
    feed(window, [PING.format(i) for i in range(3)])
    # экран пуст и заморожен, а счётчик говорит, сколько логов ждёт
    assert lines(window) == [] and window.lbl_line_count.text() == "Показано 0 · ещё 3 после паузы"
    window.btn_pause.setChecked(False)
    assert len(lines(window)) == 1 and window.lbl_line_count.text() == "Показано 1 из 3"
