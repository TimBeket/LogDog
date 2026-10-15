"""Профили на iPhone: профили подготовки (кто подписал сборки, до какого
числа) и конфигурационные профили (сертификат прокси, VPN, MDM)."""
from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from gui import theme


def _date(value) -> str:
    return f"{value:%d.%m.%Y}" if isinstance(value, datetime) else ""


def _expired(value, now=None) -> bool:
    if not isinstance(value, datetime):
        return False
    now = now or datetime.now(timezone.utc)
    value = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return value < now


class TableDialog(QDialog):
    def __init__(self, title: str, hint: str, headers: list, rows: list, danger_rows=(), empty_text="",
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(980, 460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        head = QLabel(title)
        head.setProperty("role", "title")
        layout.addWidget(head)
        sub = QLabel(hint)
        sub.setProperty("role", "muted")
        sub.setWordWrap(True)
        layout.addWidget(sub)

        if rows:
            self.table = QTableWidget(len(rows), len(headers))
            self.table.setHorizontalHeaderLabels(headers)
            self.table.verticalHeader().setVisible(False)
            self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.table.setWordWrap(False)
            danger = QColor(theme.tokens()["danger"])
            for r, row in enumerate(rows):
                for c, value in enumerate(row):
                    item = QTableWidgetItem(str(value))
                    item.setToolTip(str(value))
                    if r in danger_rows:
                        item.setForeground(danger)
                    self.table.setItem(r, c, item)
            # По содержимому, но не шире 320: длинные App ID иначе выдавливали
            # из окна первую колонку с названием.
            self.table.resizeColumnsToContents()
            header = self.table.horizontalHeader()
            header.setSectionResizeMode(QHeaderView.Interactive)
            for c in range(len(headers)):
                self.table.setColumnWidth(c, min(self.table.columnWidth(c) + 12, 320))
            header.setStretchLastSection(True)
            layout.addWidget(self.table, 1)
        else:
            self.table = None
            empty = QLabel(empty_text)
            empty.setAlignment(Qt.AlignCenter)
            empty.setProperty("role", "muted")
            layout.addWidget(empty, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        close = QPushButton("Закрыть")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)


def provisioning_dialog(profiles: list, parent=None, now=None) -> TableDialog:
    profiles = sorted(profiles, key=lambda p: (p.get("expires") is None, p.get("expires") or datetime.max))
    rows, danger = [], set()
    for i, p in enumerate(profiles):
        kind = "Enterprise" if p.get("all_devices") else (f"{p['devices']} устр." if p.get("devices") else "")
        expired = _expired(p.get("expires"), now)
        if expired:
            danger.add(i)
        rows.append([p.get("name", ""), _date(p.get("expires")) + (" — истёк" if expired else ""),
                     p.get("team", ""), kind, p.get("app_id", "")])
    return TableDialog("Профили подготовки",
                       "Кто подписал установленные сборки и до какого числа они будут запускаться. "
                       "Истёкшие — красным: такие сборки не откроются, нужна новая.",
                       ["Профиль", "Действует до", "Команда", "Устройства", "App ID"],
                       rows, danger, "Профилей подготовки нет", parent)


def configuration_dialog(profiles: list, parent=None) -> TableDialog:
    rows = [[p.get("name", ""), p.get("organization", ""), p.get("description", ""), p.get("id", "")]
            for p in profiles]
    return TableDialog("Конфигурационные профили",
                       "Сертификаты прокси (Charles, Proxyman), VPN, MDM — то, что установлено в "
                       "Настройки → Основные → VPN и управление устройством.",
                       ["Профиль", "Организация", "Описание", "Идентификатор"],
                       rows, (), "Конфигурационных профилей нет", parent)
