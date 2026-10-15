"""Окна инструментов без устройства: список приложений, язык, профили, .ipa,
доступность карточек и перетаскивание .ipa."""
import time
from datetime import datetime, timedelta, timezone

from PySide6.QtCore import QMimeData, QUrl
from PySide6.QtWidgets import QWidget

from core import ipa_info
from gui.dialogs.app_list import AppListDialog
from gui.dialogs.ipa_check import IpaCheckDialog
from gui.dialogs.language import LanguageDialog, language_title, region_title
from gui.dialogs.profiles import provisioning_dialog
from gui.dialogs.tools import ToolsWindow

APPS = [{"bundle_id": "com.example.mygame", "name": "My Game", "version": "1.4", "build": "142"},
        {"bundle_id": "com.example.othergame", "name": "Other Game", "version": "2.0", "build": "7"}]


def test_app_list_actions_need_selection_and_device(qtbot):
    dlg = AppListDialog(APPS, serial="SERIAL")
    qtbot.addWidget(dlg)
    assert not dlg._data_btn.isEnabled() and not dlg._uninstall_btn.isEnabled()
    dlg.list_widget.setCurrentRow(0)
    assert dlg.selected_bundle_id() == "com.example.mygame"
    assert dlg._data_btn.isEnabled() and dlg._uninstall_btn.isEnabled()
    dlg.search_input.setText("web")
    assert dlg.list_widget.count() == 1

    no_device = AppListDialog(APPS, serial="")
    qtbot.addWidget(no_device)
    no_device.list_widget.setCurrentRow(0)
    assert no_device._copy_btn.isEnabled() and not no_device._uninstall_btn.isEnabled()


def test_app_list_drops_uninstalled_app(qtbot):
    dlg = AppListDialog(APPS, serial="SERIAL")
    qtbot.addWidget(dlg)
    dlg._on_uninstalled("com.example.mygame")
    assert [a["bundle_id"] for a in dlg.items] == ["com.example.othergame"]
    assert dlg.list_widget.count() == 1 and "Удалено" in dlg.status.text()


def test_language_titles_and_selection(qtbot):
    assert language_title("ru").startswith("Русский") and language_title("ru").endswith("— ru")
    assert "— en_RU" in region_title("en_RU")
    intl = {"language": "en-RU", "locale": "en_RU", "languages": ["en", "ru", "uk"], "locales": ["en_US", "ru_RU"]}
    dlg = LanguageDialog(intl)
    qtbot.addWidget(dlg)
    codes = [dlg.language_combo.itemData(i) for i in range(dlg.language_combo.count())]
    assert codes[:3] == ["en-RU", "en", "ru"]   # текущий — в списке, частые — сверху
    assert dlg.selection() == ("en-RU", "en_RU")
    dlg.language_combo.setCurrentIndex(codes.index("ru"))
    assert dlg.selection()[0] == "ru"


def test_expired_provisioning_profile_is_marked(qtbot):
    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    profiles = [{"name": "Old", "team": "T", "app_id": "T.a", "expires": datetime(2026, 1, 1), "devices": 1},
                {"name": "New", "team": "T", "app_id": "T.b", "expires": datetime(2027, 1, 1), "devices": 0,
                 "all_devices": True}]
    dlg = provisioning_dialog(profiles, now=now)
    qtbot.addWidget(dlg)
    assert dlg.table.item(0, 0).text() == "Old" and "истёк" in dlg.table.item(0, 1).text()
    assert dlg.table.item(1, 3).text() == "Enterprise"


def test_ipa_dialog_wording(qtbot, tmp_path):
    info = ipa_info.IpaInfo(path=tmp_path / "a.ipa", name="Art", bundle_id="a.b", version="1", build="2",
                            has_profile=True, devices=["X"], expires=datetime.now(timezone.utc) + timedelta(days=9))
    ok = IpaCheckDialog(info, [])
    bad = IpaCheckDialog(info, ipa_info.check(info, udid="SERIAL"))
    qtbot.addWidget(ok)
    qtbot.addWidget(bad)
    assert ok.install_button.text() == "Установить"
    assert bad.install_button.text() == "Всё равно установить"


class FakeMain(QWidget):
    def __init__(self, serial):
        super().__init__()
        self._ios_device_available = bool(serial)
        self._serial = serial

    def current_device_serial(self):
        return self._serial


def test_tools_cards_follow_device(qtbot):
    with_device = FakeMain("SERIAL")
    qtbot.addWidget(with_device)
    tools = ToolsWindow(with_device)
    from transports.device_tools import HAS_PYMOBILEDEVICE3
    assert all(getattr(tools, a).isEnabled() is HAS_PYMOBILEDEVICE3 for a in ToolsWindow._TASK_TOOLS)
    without = FakeMain("")
    qtbot.addWidget(without)
    tools2 = ToolsWindow(without)
    assert not any(getattr(tools2, a).isEnabled() for a in ToolsWindow._TASK_TOOLS)
    assert "Подключите iPhone" in tools2.device_hint.text()


def test_dropped_ipa_detection():
    class Event:
        def __init__(self, paths):
            self._m = QMimeData()
            self._m.setUrls([QUrl.fromLocalFile(p) for p in paths])

        def mimeData(self):
            return self._m

    assert ToolsWindow._dropped_ipa(Event(["/tmp/Game.IPA"])) == "/tmp/Game.IPA"
    assert ToolsWindow._dropped_ipa(Event(["/tmp/a.zip"])) == ""
    assert ToolsWindow._dropped_ipa(Event(["/tmp/a.ipa", "/tmp/b.ipa"])) == ""


def test_cards_lose_hover_when_a_dialog_blocks_the_window(qtbot):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtWidgets import QApplication
    win = ToolsWindow()
    qtbot.addWidget(win)
    card = win.btn_app_list
    card.setAttribute(Qt.WA_UnderMouse, True)   # мышь была над карточкой, по ней щёлкнули
    QApplication.sendEvent(win, QEvent(QEvent.WindowBlocked))  # открылось модальное окно
    assert not card.testAttribute(Qt.WA_UnderMouse)


def test_closing_app_list_stops_icon_loader(qtbot, monkeypatch):
    # окно удаляют закрытием, не через done(): поток иконок всё равно должен остановиться
    from transports import device_tools
    monkeypatch.setattr(device_tools, "HAS_PYMOBILEDEVICE3", True)
    def slow_run(self):  # как на Windows без службы Apple: долго ждёт подключения
        while self._is_running:
            time.sleep(0.01)
    monkeypatch.setattr(device_tools.IconLoader, "run", slow_run)
    dlg = AppListDialog(APPS, serial="SERIAL")
    qtbot.addWidget(dlg)
    loader = dlg._icon_loader
    qtbot.waitUntil(loader.isRunning)
    dlg.close()
    assert dlg._icon_loader is None and not loader.isRunning()
