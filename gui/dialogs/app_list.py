"""Установленные приложения: поиск, иконки и действия с выбранным —
скопировать bundle id, данные игры (очистить / скачать папку / лог Unity),
удалить."""
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QMessageBox, QPushButton, QVBoxLayout,
)

from core.settings import settings
from gui import icons
from gui.dialogs.device_tasks import TaskRunner
from gui.theme import theme_signals, tokens
from gui.widgets.dialog_parts import SUBTITLE_ROLE, DialogHeader, TwoLineDelegate
from transports import device_tools


class AppListDialog(QDialog):
    """Dialog to view the list of applications installed on an iOS device."""

    def __init__(self, items: list, parent=None, serial: str = ""):
        super().__init__(parent)
        self.items = list(items)
        self.serial = serial
        self._icons: dict = {}
        self._tasks = TaskRunner(self)
        self._icon_loader = None
        self.setWindowTitle("Установленные приложения")
        self.resize(680, 520)
        self._init_ui()
        self._populate(self.items)
        self._load_icons()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(10)

        self.header = DialogHeader("apps", "Приложения на iPhone")
        layout.addLayout(self.header)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Поиск по названию или bundle id")
        self.search_input.textChanged.connect(self._on_search_changed)
        self.search_input.setClearButtonEnabled(True)
        self._search_action = self.search_input.addAction(QIcon(), QLineEdit.LeadingPosition)
        layout.addWidget(self.search_input)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.SingleSelection)
        self.list_widget.setIconSize(QSize(36, 36))
        self.list_widget.setItemDelegate(TwoLineDelegate(self.list_widget, icon_size=36))
        self.list_widget.setMouseTracking(True)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._copy_selected())
        layout.addWidget(self.list_widget, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)

        self._copy_btn = QPushButton("Bundle id")
        self._copy_btn.setToolTip("Скопировать bundle id (или двойной щелчок по приложению)")
        self._copy_btn.clicked.connect(self._copy_selected)
        actions.addWidget(self._copy_btn)

        self._data_btn = QPushButton("Данные игры")
        self._data_btn.setToolTip("Очистить данные без переустановки, скачать папку, лог Unity")
        data_menu = QMenu(self._data_btn)
        self._act_clear = data_menu.addAction("Очистить данные…", self._clear_data)
        self._act_pull = data_menu.addAction("Скачать папку игры…", self._pull_data)
        self._act_log = data_menu.addAction("Лог Unity (output.log)…", self._pull_unity_log)
        self._data_btn.setMenu(data_menu)
        actions.addWidget(self._data_btn)

        self._uninstall_btn = QPushButton("Удалить…")
        self._uninstall_btn.setProperty("variant", "danger")
        self._uninstall_btn.clicked.connect(self._uninstall)
        actions.addWidget(self._uninstall_btn)
        actions.addStretch()

        close_btn = QPushButton("Готово")
        close_btn.setProperty("variant", "primary")
        close_btn.clicked.connect(self.reject)
        actions.addWidget(close_btn)
        layout.addLayout(actions)

        self.status = QLabel("")
        self.status.setProperty("role", "muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.list_widget.itemSelectionChanged.connect(self._update_actions)
        self._apply_icons()
        theme_signals.theme_changed.connect(self._apply_icons)
        self._update_actions()

    def _apply_icons(self, *_):
        self._search_action.setIcon(icons.icon("search"))
        self._copy_btn.setIcon(icons.icon("copy"))
        self._data_btn.setIcon(icons.icon("folder"))
        self._uninstall_btn.setIcon(icons.icon("trash"))
        self._act_clear.setIcon(icons.icon("eraser"))
        self._act_pull.setIcon(icons.icon("download"))
        self._act_log.setIcon(icons.icon("file_text"))
        # Пока настоящая иконка не загрузилась (или её нет) — нейтральная плашка
        self._placeholder = self._placeholder_icon()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole) and item.data(Qt.UserRole) not in self._icons:
                item.setIcon(self._placeholder)

    @staticmethod
    def _placeholder_icon() -> QIcon:
        t, size = tokens(), 72  # рисуем в 2x — чётко и на HiDPI
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(t["raised"]))
        p.drawRoundedRect(0, 0, size, size, 16, 16)
        glyph = icons.pixmap("apps", t["faint"], 18)  # 36 px в 2x
        glyph.setDevicePixelRatio(1)
        p.drawPixmap((size - glyph.width()) // 2, (size - glyph.height()) // 2, glyph)
        p.end()
        return QIcon(pm)

    # ── Список ───────────────────────────────────────────────────────────

    def _populate(self, items: list):
        self.list_widget.clear()
        if not items:
            item = QListWidgetItem("Приложения не найдены")
            item.setFlags(Qt.NoItemFlags)
            self.list_widget.addItem(item)
        else:
            for app in items:
                bid = app.get("bundle_id", "")
                it = QListWidgetItem(app.get("name") or bid or "?")
                it.setData(SUBTITLE_ROLE, self._subtitle(app))
                it.setData(Qt.UserRole, bid)
                it.setToolTip(bid)
                it.setIcon(self._icons.get(bid, self._placeholder))
                self.list_widget.addItem(it)
        self._update_count_label()
        self._update_actions()

    @staticmethod
    def _subtitle(app: dict) -> str:
        version, build = app.get("version") or "-", app.get("build") or "-"
        return f"{version} ({build}) · {app.get('bundle_id', '')}"

    def _on_search_changed(self, text: str):
        needle = text.strip().lower()
        if not needle:
            self._populate(self.items)
            return
        filtered = [
            a for a in self.items
            if needle in ((a.get("name") or "") + " " + a.get("bundle_id", "")).lower()
        ]
        self._populate(filtered)

    def _update_count_label(self):
        count = sum(1 for i in range(self.list_widget.count()) if self.list_widget.item(i).data(Qt.UserRole))
        total = len(self.items)
        self.header.set_subtitle(f"{total} шт." if count == total else f"Найдено {count} из {total}")

    def selected_bundle_id(self) -> str:
        items = self.list_widget.selectedItems()
        return str(items[0].data(Qt.UserRole) or "") if items else ""

    def selected_name(self) -> str:
        bid = self.selected_bundle_id()
        app = next((a for a in self.items if a.get("bundle_id") == bid), {})
        return app.get("name") or bid

    def _update_actions(self):
        has = bool(self.selected_bundle_id())
        busy = self._tasks.busy()
        self._copy_btn.setEnabled(has)
        for btn in (self._data_btn, self._uninstall_btn):
            btn.setEnabled(has and bool(self.serial) and not busy)

    def _set_status(self, text: str):
        self.status.setText(text)

    # ── Иконки ───────────────────────────────────────────────────────────

    def _load_icons(self):
        if not self.serial or not device_tools.HAS_PYMOBILEDEVICE3:
            return
        bundle_ids = [a.get("bundle_id") for a in self.items if a.get("bundle_id")]
        self._icon_loader = device_tools.IconLoader(self.serial, bundle_ids, parent=self)
        self._icon_loader.icon_ready.connect(self._on_icon)
        self._icon_loader.start()

    def _on_icon(self, bundle_id: str, png: bytes):
        pm = QPixmap()
        if not pm.loadFromData(png):
            return
        icon = QIcon(pm)
        self._icons[bundle_id] = icon
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole) == bundle_id:
                item.setIcon(icon)
                break

    # ── Действия ─────────────────────────────────────────────────────────

    def _copy_selected(self):
        bid = self.selected_bundle_id()
        if not bid:
            return
        QApplication.clipboard().setText(bid)
        self._set_status(f"Bundle id скопирован: {bid}")

    def _ask_dir(self, title: str) -> str:
        folder = QFileDialog.getExistingDirectory(self, title, settings.last_save_dir())
        if folder:
            settings.set_last_save_dir(folder)
        return folder

    def _run(self, job, on_done, prefix, busy_text):
        self._set_status(busy_text)
        self._tasks.run(self.serial, job, on_done, on_failed=self._on_failed,
                        busy=(self._data_btn, self._uninstall_btn), error_prefix=prefix)

    def _on_failed(self, message: str):
        self._set_status("")
        QMessageBox.critical(self, "Не получилось", message)

    def _clear_data(self):
        bid, name = self.selected_bundle_id(), self.selected_name()
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Очистить данные игры")
        box.setText(f"Удалить все данные «{name}»?")
        box.setInformativeText(
            "Сохранения, настройки (PlayerPrefs), кэш и файлы игры будут удалены — как после "
            "переустановки, но без неё.\n\nСначала закройте игру на iPhone (смахните из списка "
            "приложений): LogDog не может её остановить, а запущенная игра запишет данные заново.")
        ok = box.addButton("Очистить", QMessageBox.DestructiveRole)
        box.addButton("Отмена", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not ok:
            return
        self._run(lambda ld: device_tools.clear_app_data(ld, bid),
                  lambda failed: self._on_cleared(name, failed),
                  "Не удалось очистить данные", f"Очищаю данные «{name}»…")

    def _on_cleared(self, name: str, failed: list):
        self._set_status(f"Данные «{name}» очищены")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information if not failed else QMessageBox.Warning)
        box.setWindowTitle("Данные очищены")
        text = f"Данные «{name}» удалены. Запустите игру и проверьте, что она стартует как в первый раз."
        if failed:
            text += f"\n\nНе удалось удалить {len(failed)} файл(ов) — возможно, игра была запущена."
        box.setText(text)
        box.setInformativeText(
            "Если игра всё же помнит прогресс или настройки, iOS держит их в памяти — "
            "перезагрузка iPhone это сбросит.")
        reboot = box.addButton("Перезагрузить iPhone", QMessageBox.ActionRole)
        box.addButton("Готово", QMessageBox.AcceptRole)
        box.exec()
        if box.clickedButton() is reboot:
            self._run(device_tools.reboot, lambda _r: self._set_status("iPhone перезагружается…"),
                      "Не удалось перезагрузить", "Перезагружаю iPhone…")

    def _pull_data(self):
        bid, name = self.selected_bundle_id(), self.selected_name()
        folder = self._ask_dir("Куда сохранить папку игры")
        if not folder:
            return
        self._run(lambda ld: device_tools.pull_app_data(ld, bid, folder),
                  self._on_pulled, "Не удалось скачать папку", f"Скачиваю папку «{name}»…")

    def _on_pulled(self, path: str):
        self._set_status(f"Сохранено: {path}")
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _pull_unity_log(self):
        bid = self.selected_bundle_id()
        start = str(Path(settings.last_save_dir() or Path.home()) / f"{bid}-output.log")
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить лог Unity", start, "Log (*.log);;Все файлы (*)")
        if not path:
            return
        settings.set_last_save_dir(str(Path(path).parent))
        self._run(lambda ld: device_tools.pull_unity_log(ld, bid, path),
                  self._on_log_saved, "Не удалось скачать лог", "Скачиваю output.log…")

    def _on_log_saved(self, path: str):
        self._set_status(f"Лог сохранён: {path}")
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _uninstall(self):
        bid, name = self.selected_bundle_id(), self.selected_name()
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Удалить приложение")
        box.setText(f"Удалить «{name}» с iPhone?")
        box.setInformativeText(f"{bid}\n\nПриложение и все его данные будут удалены.")
        ok = box.addButton("Удалить", QMessageBox.DestructiveRole)
        box.addButton("Отмена", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not ok:
            return
        self._run(lambda ld: device_tools.uninstall_app(ld, bid), self._on_uninstalled,
                  "Не удалось удалить", f"Удаляю «{name}»…")

    def _on_uninstalled(self, bundle_id: str):
        self.items = [a for a in self.items if a.get("bundle_id") != bundle_id]
        self._on_search_changed(self.search_input.text())
        self._set_status(f"Удалено: {bundle_id}")

    def done(self, result: int):
        if self._icon_loader is not None:
            self._icon_loader.stop()
            self._icon_loader.quit()
            self._icon_loader.wait(2000)
            if self._icon_loader.isRunning():
                self._icon_loader.terminate()
                self._icon_loader.wait()
            self._icon_loader = None
        self._tasks.stop_all()
        super().done(result)
