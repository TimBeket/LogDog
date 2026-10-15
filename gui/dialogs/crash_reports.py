from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QLabel,
)

from gui import icons
from gui.theme import theme_signals, tokens
from gui.widgets.dialog_parts import SUBTITLE_ROLE, DialogHeader, TwoLineDelegate
from transports.crash_reporter import CrashReportItem


class CrashReportDialog(QDialog):
    """Dialog to view and choose crash reports downloaded from an iOS device."""

    def __init__(self, items: list, parent=None):
        super().__init__(parent)
        self.items = items
        self.setWindowTitle("Краш-отчёты iOS")
        self.resize(640, 480)
        self._init_ui()
        self._populate(self.items)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(10)
        layout.addLayout(DialogHeader(
            "bug", "Краш-отчёты",
            "Выберите отчёты (Ctrl/Shift — несколько): сохранится оригинал .ips и читаемый .log"))

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Поиск по приложению или имени файла")
        self.search_input.textChanged.connect(self._on_search_changed)
        self.search_input.setClearButtonEnabled(True)
        self._search_action = self.search_input.addAction(QIcon(), QLineEdit.LeadingPosition)
        layout.addWidget(self.search_input)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.ExtendedSelection)
        self.list_widget.setIconSize(QSize(28, 28))
        self.list_widget.setItemDelegate(TwoLineDelegate(self.list_widget, icon_size=28))
        self.list_widget.setMouseTracking(True)
        self.list_widget.itemDoubleClicked.connect(lambda _item: self._on_save())
        layout.addWidget(self.list_widget, 1)

        btn_row = QHBoxLayout()
        self.lbl_count = QLabel("")
        self.lbl_count.setProperty("role", "muted")
        btn_row.addWidget(self.lbl_count)
        btn_row.addStretch()

        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        self.save_btn = QPushButton("Сохранить выбранные")
        self.save_btn.setProperty("variant", "primary")
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(self.save_btn)

        layout.addLayout(btn_row)
        self.list_widget.itemSelectionChanged.connect(self._update_save_state)
        self._apply_icons()
        theme_signals.theme_changed.connect(self._apply_icons)
        self._update_save_state()

    def _apply_icons(self, *_):
        self._search_action.setIcon(icons.icon("search"))
        self._crash_icon = QIcon(icons.pixmap("bug", tokens()["danger"], 28))
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole) is not None:
                item.setIcon(self._crash_icon)

    def _populate(self, items: list):
        self.list_widget.clear()
        if not items:
            item = QListWidgetItem("Краш-отчётов не найдено")
            item.setFlags(Qt.NoItemFlags)
            self.list_widget.addItem(item)
        else:
            for crash in items:
                it = QListWidgetItem(crash.name or Path(crash.path).name)
                it.setData(SUBTITLE_ROLE, self._subtitle(crash))
                it.setData(Qt.UserRole, crash)
                it.setIcon(self._crash_icon)
                it.setToolTip(crash.path)
                self.list_widget.addItem(it)
        self._update_count_label()

    @staticmethod
    def _subtitle(crash: CrashReportItem) -> str:
        parts = [crash.timestamp, f"тип {crash.bug_type}" if crash.bug_type else "",
                 f"#{crash.incident_id}" if crash.incident_id else ""]
        return " · ".join(p for p in parts if p) or Path(crash.path).name

    def _on_search_changed(self, text: str):
        needle = text.strip().lower()
        if not needle:
            self._populate(self.items)
            return
        filtered = [c for c in self.items if needle in (c.name + " " + c.path).lower()]
        self._populate(filtered)

    def _update_count_label(self):
        shown = sum(1 for i in range(self.list_widget.count()) if self.list_widget.item(i).data(Qt.UserRole))
        selected = len(self.list_widget.selectedItems())
        text = f"Выбрано {selected} из {shown}" if selected else f"Отчётов: {shown}"
        if shown != len(self.items):
            text += f" (всего {len(self.items)})"
        self.lbl_count.setText(text)

    def _update_save_state(self):
        self.save_btn.setEnabled(len(self.list_widget.selectedItems()) > 0)
        self._update_count_label()

    def _on_save(self):
        if self.selected_items():
            self.accept()

    def selected_items(self) -> list:
        return [it.data(Qt.UserRole) for it in self.list_widget.selectedItems()]