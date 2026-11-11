"""Окно логов: QPlainTextEdit + колонка «+N с» слева + подсветка слов + меню.

Колонка времени — как номера строк в редакторе: рисуется рядом с текстом и
в текст (и в копирование) не попадает. Разница хранится в userState первой
строки (QTextBlock) записи: секунды от предыдущей показанной записи, -1 —
продолжение записи или нет времени.

Подсветка слов и совпадения поиска — extraSelections только видимых строк,
пересчёт при прокрутке и новых логах. Раньше слова красил QSyntaxHighlighter:
смена слов перекрашивала весь документ (50 тыс. строк — треть секунды на
слабом компьютере), а каждая вставленная строка — вызов Python. Слои
(слова снизу, поиск сверху) собираются здесь: setExtraSelections у окна один.
У каждой подсветки свой QTextCursor — поэтому не больше MAX_WORD_SELECTIONS
(почему много курсоров вредно — gui/widgets/find_bar.py).
"""
from typing import List, Tuple

from PySide6.QtCore import QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QTextCursor
from PySide6.QtWidgets import QMenu, QPlainTextEdit, QTextEdit, QWidget

from core.log_entry import format_delta
from core.text_search import find_all, utf16_len, utf16_positions
from gui import theme

HIGHLIGHT_COLORS = ["#F2C94C", "#6FCF97", "#56CCF2", "#BB6BD9", "#F2994A", "#EB5757"]
MAX_WORD_SELECTIONS = 300


class _Gutter(QWidget):
    def __init__(self, view: "LogView"):
        super().__init__(view)
        self.view = view

    def sizeHint(self):
        return QSize(self.view.gutter_width(), 0)

    def paintEvent(self, event):
        self.view.paint_gutter(event)


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
        self._words: List[Tuple[str, QColor, int]] = []   # (слово, цвет, длина в UTF-16)
        self._layers = {"words": [], "find": []}
        # Не прямо из прокрутки: setExtraSelections изнутри valueChanged сразу
        # после вставки логов ронял Qt (segfault) — следующим тактом.
        self._words_timer = QTimer(self)
        self._words_timer.setSingleShot(True)
        self._words_timer.setInterval(15)
        self._words_timer.timeout.connect(self._paint_words)
        self.verticalScrollBar().valueChanged.connect(self._schedule_words)
        self.document().contentsChange.connect(self._schedule_words)
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
        self._schedule_words()
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
        alpha = 110 if theme.current() == "Dark" else 90
        self._words = []
        for text, color in rules:
            if text:
                bg = QColor(color)
                bg.setAlpha(alpha)
                self._words.append((text, bg, utf16_len(text)))
        self._paint_words()

    def set_selection_layer(self, name: str, selections: list):
        """Слой подсветки («words», «find»); показываются все слои, find — сверху."""
        self._layers[name] = selections
        self.setExtraSelections([])   # старые курсоры — до новых, меньше живут одновременно
        self.setExtraSelections(self._layers["words"] + self._layers["find"])

    def _schedule_words(self, *_):
        if self._words and not self._words_timer.isActive():
            self._words_timer.start()

    def visible_blocks(self):
        """Строки (QTextBlock), видимые сейчас."""
        block = self.firstVisibleBlock()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = self.viewport().height()
        while block.isValid() and top <= bottom:
            if block.isVisible():
                yield block
            top += self.blockBoundingRect(block).height()
            block = block.next()

    def _paint_words(self):
        self._words_timer.stop()
        selections = []
        if self._words:
            doc = self.document()
            for block in self.visible_blocks():
                text, base = block.text(), block.position()
                for needle, bg, size in self._words:
                    for start in utf16_positions(text, find_all(text, needle)):
                        sel = QTextEdit.ExtraSelection()
                        cursor = QTextCursor(doc)
                        cursor.setPosition(base + start)
                        cursor.setPosition(base + start + size, QTextCursor.KeepAnchor)
                        sel.cursor = cursor
                        sel.format.setBackground(bg)
                        selections.append(sel)
                if len(selections) >= MAX_WORD_SELECTIONS:
                    del selections[MAX_WORD_SELECTIONS:]
                    break
        if selections or self._layers["words"]:
            self.set_selection_layer("words", selections)

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
