"""Окно логов: QPlainTextEdit + колонка «+N с» слева + подсветка слов + меню.

Колонка времени — как номера строк в редакторе: рисуется рядом с текстом и
в текст (и в копирование) не попадает. Разница хранится в userState первой
строки (QTextBlock) записи: секунды от предыдущей показанной записи, -1 —
продолжение записи или нет времени.
"""
from typing import List, Tuple

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QMenu, QPlainTextEdit, QWidget

from core.log_entry import format_delta
from gui import theme

HIGHLIGHT_COLORS = ["#F2C94C", "#6FCF97", "#56CCF2", "#BB6BD9", "#F2994A", "#EB5757"]


class _Gutter(QWidget):
    def __init__(self, view: "LogView"):
        super().__init__(view)
        self.view = view

    def sizeHint(self):
        return QSize(self.view.gutter_width(), 0)

    def paintEvent(self, event):
        self.view.paint_gutter(event)


class _Highlighter(QSyntaxHighlighter):
    """Цветная заливка выбранных слов поверх цвета уровня (без учёта регистра)."""

    def __init__(self, document):
        super().__init__(document)
        self.rules: List[Tuple[str, QTextCharFormat]] = []

    def set_rules(self, rules: List[Tuple[str, str]]):
        self.rules = []
        for text, color in rules:
            fmt = QTextCharFormat()
            bg = QColor(color)
            bg.setAlpha(110 if theme.current() == "Dark" else 90)
            fmt.setBackground(bg)
            self.rules.append((text.lower(), fmt))
        self.rehighlight()

    def highlightBlock(self, text: str):
        if not self.rules:
            return
        low = text.lower()
        for needle, fmt in self.rules:
            start = low.find(needle)
            while start != -1 and needle:
                self.setFormat(start, len(needle), fmt)
                start = low.find(needle, start + len(needle))


class LogView(QPlainTextEdit):
    highlight_requested = Signal(str, str)   # текст, цвет
    watch_requested = Signal(str)            # текст для отслеживания
    marker_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LogView")
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        self._gutter = _Gutter(self)
        self._show_gutter = False
        self._highlighter = _Highlighter(self.document())
        self.blockCountChanged.connect(self._update_margins)
        self.updateRequest.connect(self._on_update_request)
        self._update_margins()

    # ── Колонка времени ──────────────────────────────────────────────────

    def set_gutter_visible(self, visible: bool):
        self._show_gutter = visible
        self._gutter.setVisible(visible)
        self._update_margins()

    def gutter_width(self) -> int:
        return self.fontMetrics().horizontalAdvance("+59м59с") + 14 if self._show_gutter else 0

    def _update_margins(self, *_):
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _on_update_request(self, rect, dy):
        if not self._show_gutter:
            return
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def paint_gutter(self, event):
        t = theme.tokens()
        painter = QPainter(self._gutter)
        painter.fillRect(event.rect(), QColor(t["base"]))
        painter.setPen(QColor(t["faint"]))
        font = self.font()
        font.setPointSizeF(max(6.0, font.pointSizeF() - 1))
        painter.setFont(font)
        block = self.firstVisibleBlock()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        width = self._gutter.width() - 6
        while block.isValid() and top <= event.rect().bottom():
            height = round(self.blockBoundingRect(block).height())
            if block.isVisible() and block.userState() > 0 and top + height >= event.rect().top():
                line_h = self.fontMetrics().height()
                painter.drawText(QRect(0, top, width, line_h), Qt.AlignRight | Qt.AlignVCenter,
                                 format_delta(block.userState()))
            top += height
            block = block.next()
        painter.end()

    # ── Подсветка слов ───────────────────────────────────────────────────

    def set_highlights(self, rules: List[Tuple[str, str]]):
        self._highlighter.set_rules(rules)

    # ── Меню по правой кнопке ────────────────────────────────────────────

    def _selected_or_word(self, pos) -> str:
        text = self.textCursor().selectedText().replace(" ", " ").strip()
        if text:
            return text
        cursor = self.cursorForPosition(pos)
        cursor.select(QTextCursor.WordUnderCursor)
        return cursor.selectedText().strip()

    def contextMenuEvent(self, event):
        menu = self.createStandardContextMenu(event.pos())
        word = self._selected_or_word(event.pos())
        menu.addSeparator()
        if word:
            short = word if len(word) <= 32 else word[:30] + "…"
            sub = QMenu(f"Подсветить «{short}»", menu)
            for color in HIGHLIGHT_COLORS:
                action = sub.addAction("")
                pm = self._swatch(color)
                action.setIcon(pm)
                action.triggered.connect(lambda _=False, c=color: self.highlight_requested.emit(word, c))
            menu.addMenu(sub)
            menu.addAction(f"Отслеживать «{short}»", lambda: self.watch_requested.emit(word))
        menu.addAction("Вставить маркер шага…\tCtrl+M", self.marker_requested.emit)
        menu.exec(event.globalPos())

    @staticmethod
    def _swatch(color: str):
        from PySide6.QtGui import QIcon, QPixmap
        pm = QPixmap(28, 14)
        pm.fill(QColor(color))
        return QIcon(pm)
