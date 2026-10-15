"""Правая панель окна логов: подробности строки, отслеживание, подсветка слов."""
import json
import re
from typing import List, Optional, Tuple

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QPlainTextEdit, QPushButton, QTabWidget,
    QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from core.log_entry import message_body, message_key
from core.watch import WatchList
from gui import icons, theme
from gui.theme import theme_signals
from gui.widgets.filter_edit import FilterLineEdit
from gui.widgets.log_view import HIGHLIGHT_COLORS

_PAIR_RE = re.compile(r'([A-Za-z_][\w.\-]*)\s*[:=]\s*("[^"]*"|[^\s;,]+)')


def find_json(text: str):
    """Самый длинный кусок JSON в строке (объект или массив) или None."""
    decoder = json.JSONDecoder()
    best = None
    for i, ch in enumerate(text):
        if ch in "{[":
            try:
                value, end = decoder.raw_decode(text, i)
            except ValueError:
                continue
            meaningful = isinstance(value, dict) and value or (
                isinstance(value, list) and (len(value) > 1 or any(isinstance(v, (dict, list)) for v in value)))
            if meaningful and (best is None or end - i > best[1]):
                best = (value, end - i)
    return best[0] if best else None


def find_pairs(text: str) -> List[Tuple[str, str]]:
    """«AVAILABLE:True; isTimeout:False» → [(AVAILABLE, True), …] — если пар хотя бы две."""
    pairs = [(k, v.strip('"')) for k, v in _PAIR_RE.findall(text)]
    return pairs if len(pairs) >= 2 else []


def _small_button(tooltip: str) -> QToolButton:
    btn = QToolButton()
    btn.setToolTip(tooltip)
    btn.setFixedSize(26, 26)
    btn.setIconSize(QSize(14, 14))
    return btn


class DetailsPage(QWidget):
    """Разбор записи под курсором."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        self.header = QLabel("Поставьте курсор на строку лога")
        self.header.setProperty("role", "muted")
        self.header.setWordWrap(True)
        self.header.setTextFormat(Qt.RichText)
        layout.addWidget(self.header)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Ключ", "Значение"])
        self.tree.setColumnWidth(0, 160)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        layout.addWidget(self.tree, 1)
        self.raw = QPlainTextEdit()
        self.raw.setReadOnly(True)
        self.raw.setMaximumHeight(120)
        layout.addWidget(self.raw)

    def show_entry(self, entry: Optional[dict], level_color: str = ""):
        self.tree.clear()
        if entry is None:
            self.header.setText("Поставьте курсор на строку лога")
            self.raw.clear()
            return
        props, raw = entry["props"], entry["raw"]
        t = theme.tokens()
        stamp = raw[:len(raw) - len(message_key(raw))].strip()
        parts = [f'<span style="color:{level_color or t["text"]}"><b>{props.get("level", "info")}</b></span>']
        if stamp:
            parts.append(stamp)
        if props.get("proc"):
            parts.append(f'процесс <b>{props["proc"]}</b>' + (f' · pid {props["pid"]}' if props.get("pid") else ""))
        self.header.setText(" · ".join(parts))
        self.raw.setPlainText(raw)

        body = message_body(raw)
        data = find_json(body)
        if data is not None:
            self.tree.setHeaderLabels(["JSON", "Значение"])
            self._fill(self.tree.invisibleRootItem(), data)
            self.tree.expandToDepth(1)
            return
        pairs = find_pairs(body)
        self.tree.setHeaderLabels(["Ключ", "Значение"])
        for key, value in pairs:
            QTreeWidgetItem(self.tree, [key, value])
        if not pairs:
            QTreeWidgetItem(self.tree, ["—", "в строке нет JSON и пар «ключ: значение»"])

    def _fill(self, parent, value):
        items = value.items() if isinstance(value, dict) else enumerate(value)
        for key, child in items:
            if isinstance(child, (dict, list)):
                node = QTreeWidgetItem(parent, [str(key), f"{len(child)} эл."])
                self._fill(node, child)
            else:
                QTreeWidgetItem(parent, [str(key), json.dumps(child, ensure_ascii=False)
                                         if not isinstance(child, str) else child])


class WatchPage(QWidget):
    """Отслеживание: правило — выражение фильтра; счётчик и последнее совпадение."""

    changed = Signal()            # правила изменились — сохранить, пересчитать
    jump_requested = Signal(int)  # id записи

    def __init__(self, watch: WatchList, parent=None):
        super().__init__(parent)
        self.watch = watch
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        hint = QLabel("Что ищете в логах — словами или выражением фильтра, например "
                      "<code>revenue OR adrevenue</code>. Считается по всем полученным логам.")
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        row = QHBoxLayout()
        self.input = FilterLineEdit()
        self.input.setPlaceholderText("Добавить: af_purchase, is_tester…")
        self.input.returnPressed.connect(self._add)
        row.addWidget(self.input, 1)
        add = QPushButton("Добавить")
        add.clicked.connect(self._add)
        row.addWidget(add)
        layout.addLayout(row)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Что", "Раз", "Последнее"])
        self.tree.setRootIsDecorated(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setStretchLastSection(False)
        self.tree.setColumnWidth(1, 48)
        self.tree.setColumnWidth(2, 80)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.setToolTip("Галочка — включить; двойной щелчок — к последнему совпадению; Delete — удалить")
        self.tree.installEventFilter(self)
        layout.addWidget(self.tree, 1)
        self.refresh()

    def add_expression(self, text: str):
        if text.strip():
            self.watch.add(text)
            self.changed.emit()
            self.refresh()

    def _add(self):
        if self.input.has_errors():
            return
        self.add_expression(self.input.text())
        self.input.clear()

    def refresh(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        t = theme.tokens()
        for rule in self.watch.rules:
            stamp = rule.last_raw[:len(rule.last_raw) - len(message_key(rule.last_raw))].strip()
            last = stamp.split()[-1] if stamp else ("—" if not rule.count else "")
            item = QTreeWidgetItem([rule.expression, str(rule.count) if rule.enabled else "", last])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(0, Qt.Checked if rule.enabled else Qt.Unchecked)
            item.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            if rule.enabled and rule.count:
                item.setForeground(1, QColor(t["accent"]))
            item.setToolTip(0, rule.last_raw or "Пока не встречалось")
            self.tree.addTopLevelItem(item)
        self.tree.blockSignals(False)

    def _on_item_changed(self, item, column):
        index = self.tree.indexOfTopLevelItem(item)
        if column == 0 and 0 <= index < len(self.watch.rules):
            self.watch.rules[index].enabled = item.checkState(0) == Qt.Checked
            self.changed.emit()

    def _on_double_click(self, item, _column):
        rule = self.watch.rules[self.tree.indexOfTopLevelItem(item)]
        if rule.last_entry_id is not None:
            self.jump_requested.emit(rule.last_entry_id)

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if obj is self.tree and event.type() == QEvent.KeyPress and event.key() == Qt.Key_Delete:
            index = self.tree.indexOfTopLevelItem(self.tree.currentItem()) if self.tree.currentItem() else -1
            if index >= 0:
                self.watch.remove(index)
                self.changed.emit()
                self.refresh()
            return True
        return super().eventFilter(obj, event)


class HighlightsPage(QWidget):
    """Подсветка слов: список «слово — цвет»."""

    changed = Signal()

    def __init__(self, rules: List[list], parent=None):
        super().__init__(parent)
        self.rules = rules  # [[текст, цвет], …] — общий список с главным окном
        self._color = HIGHLIGHT_COLORS[0]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        hint = QLabel("Слова заливаются цветом во всех логах. Быстрее — выделить слово в логах "
                      "и «Подсветить» в меню по правой кнопке.")
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        row = QHBoxLayout()
        from PySide6.QtWidgets import QLineEdit
        self.input = QLineEdit()
        self.input.setPlaceholderText("Слово или фраза")
        self.input.returnPressed.connect(self._add)
        row.addWidget(self.input, 1)
        self.swatches = []
        for color in HIGHLIGHT_COLORS:
            btn = QToolButton()
            btn.setCheckable(True)
            btn.setFixedSize(20, 20)
            btn.clicked.connect(lambda _=False, c=color: self._pick(c))
            self.swatches.append((btn, color))
            row.addWidget(btn)
        layout.addLayout(row)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        layout.addWidget(self.tree, 1)
        self._pick(self._color)
        self.refresh()
        theme_signals.theme_changed.connect(self.refresh)

    def _pick(self, color):
        self._color = color
        border = theme.tokens()["text"]
        for btn, c in self.swatches:
            btn.setChecked(c == color)
            btn.setStyleSheet(f"QToolButton {{ background-color: {c}; border-radius: 10px;"
                              f" border: 2px solid {border if c == color else c}; }}")

    def add_rule(self, text: str, color: str):
        text = text.strip()
        if not text:
            return
        self.rules[:] = [r for r in self.rules if r[0].lower() != text.lower()] + [[text, color]]
        self.changed.emit()
        self.refresh()

    def _add(self):
        self.add_rule(self.input.text(), self._color)
        self.input.clear()

    def refresh(self, *_):
        self.tree.clear()
        for index, (text, color) in enumerate(self.rules):
            item = QTreeWidgetItem(self.tree)
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(4, 0, 4, 0)
            remove = _small_button("Убрать подсветку")
            remove.setIcon(icons.icon("close"))
            remove.clicked.connect(lambda _=False, i=index: self._remove(i))
            lay.addWidget(remove)
            label = QLabel(text)
            fg = theme.TOKENS["Light"]["text"]  # заливки светлые — текст тёмный в обеих темах
            label.setStyleSheet(f"background-color: {color}; color: {fg}; border-radius: 4px; padding: 1px 6px;")
            lay.addWidget(label)
            lay.addStretch()
            self.tree.setItemWidget(item, 0, row)

    def _remove(self, index):
        del self.rules[index]
        self.changed.emit()
        self.refresh()


class SidePanel(QTabWidget):
    closed = Signal()

    def __init__(self, watch: WatchList, highlights: List[list], parent=None):
        super().__init__(parent)
        self.setObjectName("SidePanel")
        self.setDocumentMode(True)
        self.details = DetailsPage()
        self.watch_page = WatchPage(watch)
        self.highlights_page = HighlightsPage(highlights)
        self.addTab(self.details, "Подробности")
        self.addTab(self.watch_page, "Отслеживание")
        self.addTab(self.highlights_page, "Подсветка")
        close = _small_button("Закрыть панель")
        close.clicked.connect(self.closed.emit)
        self._close_button = close
        self.setCornerWidget(close, Qt.TopRightCorner)
        self._apply_icons()
        theme_signals.theme_changed.connect(self._apply_icons)

    def _apply_icons(self, *_):
        self._close_button.setIcon(icons.icon("close"))
