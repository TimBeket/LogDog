"""Поиск по окну логов (Ctrl+F).

Быстродействие (на Windows с полным окном логов поиск подвешивал программу):
- никаких QTextCursor на каждое совпадение. Документ держит живые курсоры в
  хеш-таблице, которая не сжимается: если однажды одновременно жили сотни
  тысяч курсоров (старый поиск «a»), каждая правка документа — вставка логов,
  фильтр — навсегда, до перезапуска, становится в разы медленнее (замер:
  36 тыс. курсоров → перестроение окна 7 с вместо 0,3 с). Текст забирается
  один раз и ищется регуляркой, совпадения хранятся числами;
- подсвечиваются только совпадения на экране и не больше MAX_PAINTED сразу
  (у каждой подсветки свой курсор — см. выше);
- при наборе ищем после паузы, Enter — сразу;
- новые логи досматриваются с конца, срезанные сверху — просто отбрасываются;
  целиком текст ищется заново, только если он поменялся в середине
  (фильтр, очистка, перекраска).

Позиции — в единицах QTextDocument (UTF-16), «виртуальные»: позиция в
документе + сколько символов срезано сверху с начала поиска (_shift), так
срез начала не требует пересчитывать весь список.
"""
import re
from bisect import bisect_left, bisect_right

from PySide6.QtCore import Qt, QTimer, QEvent, QSize, QPoint
from PySide6.QtGui import QTextCursor, QColor, QShortcut, QKeySequence, QIcon
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLineEdit, QToolButton, QLabel, QTextEdit
)

from gui import icons, theme
from gui.theme import theme_signals

_ASTRAL = re.compile("[\U00010000-\U0010FFFF]")
TYPING_DELAY_MS = 250      # пауза в наборе, после которой ищем
RESCAN_DELAY_MS = 150      # как часто досматривать новые логи (не чаще)
MAX_PAINTED = 300          # подсветок за раз: курсоры, см. выше; хватает на экран обычного поиска


def _utf16_len(text: str) -> int:
    return len(text) + len(_ASTRAL.findall(text))


class FindBar(QWidget):
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.setObjectName("FindBar")
        self._editor = editor
        self._search_text = ""
        self._pattern = None
        self._needle_len = 0       # длина совпадения в UTF-16
        self._starts = []          # виртуальные позиции совпадений, по возрастанию
        self._shift = 0
        self._current = None       # виртуальная позиция текущего совпадения
        self._dirty_from = None    # виртуальная позиция, с которой текст надо досмотреть

        self._typing_timer = QTimer(self)
        self._typing_timer.setSingleShot(True)
        self._typing_timer.setInterval(TYPING_DELAY_MS)
        self._typing_timer.timeout.connect(self._search)

        self._rescan_timer = QTimer(self)
        self._rescan_timer.setSingleShot(True)
        self._rescan_timer.setInterval(RESCAN_DELAY_MS)
        self._rescan_timer.timeout.connect(self._rescan)

        # Подсветку меняем не прямо из прокрутки, а следующим тактом: так
        # склеиваются частые события, а главное — setExtraSelections изнутри
        # valueChanged полосы прокрутки сразу после вставки логов ронял Qt (segfault).
        self._paint_timer = QTimer(self)
        self._paint_timer.setSingleShot(True)
        self._paint_timer.setInterval(15)
        self._paint_timer.timeout.connect(self._paint_visible)

        self._setup_ui()
        self._connect_signals()

        self._escape_shortcut = QShortcut(QKeySequence(Qt.Key_Escape), self, self._on_escape)
        # F3 / Shift+F3 — как в браузерах и редакторах: работают и когда фокус
        # ушёл из поля поиска в логи (там ↑/↓ прокручивают текст). Пока панель
        # скрыта, её сочетания клавиш не действуют.
        for seq, handler in (("F3", self._find_next), ("Shift+F3", self._find_prev)):
            QShortcut(QKeySequence(seq), self, handler).setContext(Qt.WindowShortcut)

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(6)

        self.input = QLineEdit()
        self.input.setObjectName("FindBarInput")
        self.input.setPlaceholderText("Найти в логах…  ↓ / Enter — следующее, ↑ — предыдущее")
        self.input.setMaximumWidth(460)
        self._search_action = self.input.addAction(QIcon(), QLineEdit.LeadingPosition)
        self.input.installEventFilter(self)
        layout.addWidget(self.input, 1)

        self.lbl_count = QLabel("0/0")
        self.lbl_count.setObjectName("FindBarCount")
        self.lbl_count.setMinimumWidth(48)
        self.lbl_count.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.lbl_count)

        def tool(tooltip):
            btn = QToolButton()
            btn.setToolTip(tooltip)
            btn.setFixedSize(28, 28)
            btn.setIconSize(QSize(16, 16))
            layout.addWidget(btn)
            return btn

        self.btn_up = tool("Предыдущее совпадение (↑, Shift+Enter, Shift+F3)")
        self.btn_down = tool("Следующее совпадение (↓, Enter, F3)")
        layout.addStretch()
        self.btn_close = tool("Закрыть поиск (Esc)")

        self._apply_icons()
        theme_signals.theme_changed.connect(self._apply_icons)
        self.setHidden(True)

    def _apply_icons(self, *_):
        self._search_action.setIcon(icons.icon("search"))
        self.btn_up.setIcon(icons.icon("chevron_up"))
        self.btn_down.setIcon(icons.icon("chevron_down"))
        self.btn_close.setIcon(icons.icon("close"))

    def _connect_signals(self):
        self.btn_close.clicked.connect(self.hide)
        self.btn_up.clicked.connect(self._find_prev)
        self.btn_down.clicked.connect(self._find_next)
        self.input.textChanged.connect(self._on_text_changed)
        self._editor.document().contentsChange.connect(self._on_contents_change)
        self._editor.verticalScrollBar().valueChanged.connect(self._schedule_paint)
        self._editor.viewport().installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self.input and event.type() == QEvent.KeyPress:
            key = event.key()
            if key in (Qt.Key_Return, Qt.Key_Enter):
                searched = self._flush_typing()
                if event.modifiers() & Qt.ShiftModifier:
                    self._find_prev()
                elif not searched:   # только что нашли — уже стоим на первом
                    self._find_next()
                return True
            elif key == Qt.Key_Down:
                if not self._flush_typing():
                    self._find_next()
                return True
            elif key == Qt.Key_Up:
                self._flush_typing()
                self._find_prev()
                return True
            elif key == Qt.Key_Escape:
                self.hide()
                return True
        elif event.type() == QEvent.Resize and obj is self._editor.viewport():
            self._schedule_paint()
        return super().eventFilter(obj, event)

    # ── Свойства для тестов и отладки ────────────────────────────────────

    @property
    def match_count(self) -> int:
        return len(self._starts)

    @property
    def current_index(self) -> int:
        """Номер текущего совпадения с 0, -1 — нет."""
        if self._current is None:
            return -1
        i = bisect_left(self._starts, self._current)
        return i if i < len(self._starts) and self._starts[i] == self._current else -1

    def match_positions(self) -> list:
        """Позиции совпадений в документе."""
        return [s - self._shift for s in self._starts]

    # ── Поиск ────────────────────────────────────────────────────────────

    def _on_text_changed(self, text):
        self._search_text = text
        self._typing_timer.start()

    def _flush_typing(self) -> bool:
        """Enter/↑/↓ во время паузы набора — ищем сразу, без ожидания."""
        if self._typing_timer.isActive():
            self._search()
            return True
        return False

    def _search(self):
        """Новый текст поиска: найти всё и перейти к первому совпадению."""
        self._typing_timer.stop()
        self._rescan_timer.stop()
        self._dirty_from = None
        text = self._search_text
        self._starts = []
        self._shift = 0
        self._current = None
        if not text:
            self._pattern = None
            self._clear_highlights()
            self.lbl_count.setText("0/0")
            self._set_normal_style()
            return
        self._pattern = re.compile(re.escape(text), re.IGNORECASE)
        self._needle = text.lower()
        self._needle_len = _utf16_len(text)
        self._scan_from(0)
        if self._starts:
            self._current = self._starts[0]
            self._go_to_current()
        else:
            self._update_view()

    def _scan_from(self, pos: int):
        """Досмотреть документ с начала строки, где позиция pos, до конца."""
        doc = self._editor.document()
        start = doc.findBlock(pos).position() if pos > 0 else 0
        if start == 0:
            text = doc.toPlainText()   # весь текст — так вдвое быстрее, длина та же
        else:
            cursor = QTextCursor(doc)
            cursor.setPosition(start)
            cursor.movePosition(QTextCursor.End, QTextCursor.KeepAnchor)
            text = cursor.selectedText()   # переводы строк — U+2029, длина та же
        del self._starts[bisect_left(self._starts, start + self._shift):]
        base = start + self._shift
        found = self._find_all(text)
        if found and not text.isascii():
            astral = [m.start() for m in _ASTRAL.finditer(text)]
            if astral:
                found = [i + bisect_left(astral, i) for i in found]
        self._starts.extend(base + i for i in found)

    def _find_all(self, text: str) -> list:
        """Позиции (в символах Python) всех совпадений без учёта регистра.
        lower() + str.find в разы быстрее регулярки с IGNORECASE (у неё нет
        быстрого поиска подстроки). Если lower() меняет длину текста (редкие
        буквы вроде «İ»), позиции бы съехали — тогда регулярка."""
        low = text.lower()
        if len(low) != len(text):
            return [m.start() for m in self._pattern.finditer(text)]
        needle, step, found = self._needle, len(self._needle), []
        i = low.find(needle)
        while i != -1:
            found.append(i)
            i = low.find(needle, i + step)
        return found

    def _on_contents_change(self, pos: int, removed: int, added: int):
        if self._pattern is None or not self.isVisible():
            return
        if pos == 0 and added == 0 and removed > 0:
            # срезали старые логи сверху — их совпадения просто уходят
            self._shift += removed
            del self._starts[:bisect_left(self._starts, self._shift)]
            if self._dirty_from is not None and self._dirty_from < self._shift:
                self._dirty_from = self._shift
        else:
            virtual = pos + self._shift
            self._dirty_from = virtual if self._dirty_from is None else min(self._dirty_from, virtual)
        if not self._rescan_timer.isActive():
            self._rescan_timer.start()   # не перезапускаем: при потоке логов иначе не сработал бы никогда

    def _rescan(self):
        if self._pattern is None:
            return
        if self._dirty_from is not None:
            self._scan_from(max(0, self._dirty_from - self._shift))
            self._dirty_from = None
        if self._current is not None and self.current_index < 0:
            # текущее совпадение пропало (срезано или текст поменялся) — следующее за ним
            i = bisect_left(self._starts, self._current)
            self._current = self._starts[min(i, len(self._starts) - 1)] if self._starts else None
        elif self._current is None and self._starts:
            # искомое появилось в новых логах — показать его, как и при наборе
            self._current = self._starts[0]
            self._go_to_current()
            return
        self._update_view()

    # ── Навигация и подсветка ───────────────────────────────────────────

    def _find_next(self):
        self._step(1)

    def _find_prev(self):
        self._step(-1)

    def _step(self, direction: int):
        if self._rescan_timer.isActive():
            self._rescan_timer.stop()
            self._rescan()
        if not self._starts:
            return
        idx = self.current_index
        if idx < 0:
            idx = 0 if direction > 0 else len(self._starts) - 1
        else:
            idx = (idx + direction) % len(self._starts)
        self._current = self._starts[idx]
        self._go_to_current()

    def _cursor_for(self, virtual: int) -> QTextCursor:
        doc = self._editor.document()
        last = doc.characterCount() - 1
        cursor = QTextCursor(doc)
        pos = min(virtual - self._shift, last)
        cursor.setPosition(pos)
        cursor.setPosition(min(pos + self._needle_len, last), QTextCursor.KeepAnchor)
        return cursor

    def _go_to_current(self):
        self._editor.setTextCursor(self._cursor_for(self._current))
        self._editor.centerCursor()
        self._update_view()

    def _update_view(self):
        self._update_counter()
        if self._pattern is not None and not self._starts:
            self._set_red_style()
        else:
            self._set_normal_style()
        self._paint_visible()

    def _visible_range(self):
        """Позиции первого и последнего символа на экране."""
        ed = self._editor
        vp = ed.viewport()
        first = ed.firstVisibleBlock()
        if not first.isValid():
            return 0, 0
        bottom_block = ed.cursorForPosition(QPoint(vp.width(), vp.height())).block()
        return first.position(), bottom_block.position() + bottom_block.length()

    def _schedule_paint(self, *_):
        if self._pattern is not None and not self._paint_timer.isActive():
            self._paint_timer.start()

    def _paint_visible(self, *_):
        """Подсветить совпадения на экране. Вызывается и при прокрутке."""
        self._paint_timer.stop()
        if self._pattern is None or not self.isVisible():
            return
        start, end = self._visible_range()
        end += self._shift
        if self._dirty_from is not None:
            end = min(end, self._dirty_from - 1)   # дальше позиции устарели до досмотра
        lo = bisect_left(self._starts, start + self._shift)
        hi = min(bisect_right(self._starts, end), lo + MAX_PAINTED)
        selections = []
        for virtual in self._starts[lo:hi]:
            if virtual == self._current:
                continue
            sel = QTextEdit.ExtraSelection()
            sel.cursor = self._cursor_for(virtual)
            sel.format.setBackground(QColor(255, 235, 59, 80))
            selections.append(sel)
        if self.current_index >= 0 and (self._dirty_from is None or self._current < self._dirty_from):
            sel = QTextEdit.ExtraSelection()
            sel.cursor = self._cursor_for(self._current)
            sel.format.setBackground(QColor(255, 165, 0, 180))
            selections.append(sel)
        self._editor.setExtraSelections([])   # старые курсоры — до новых, меньше живут одновременно
        self._editor.setExtraSelections(selections)

    def _clear_highlights(self):
        self._editor.setExtraSelections([])

    def _update_counter(self):
        self.lbl_count.setText(f"{self.current_index + 1}/{len(self._starts)}")

    def _set_red_style(self):
        self._set_not_found(True)

    def _set_normal_style(self):
        self._set_not_found(False)

    def _set_not_found(self, value: bool):
        for widget in (self.input, self.lbl_count):
            if widget.property("notFound") != value:
                widget.setProperty("notFound", value)
                theme.repolish(widget)

    def _on_escape(self):
        if self.isVisible():
            self.hide()

    def show(self):
        super().show()
        self.input.setFocus()
        self.input.selectAll()

    def hide(self):
        super().hide()
        self._typing_timer.stop()
        self._rescan_timer.stop()
        self._paint_timer.stop()
        self._clear_highlights()
        self._starts = []
        self._shift = 0
        self._current = None
        self._dirty_from = None
        self._pattern = None
        self._search_text = ""
        self.input.blockSignals(True)
        self.input.clear()
        self.input.blockSignals(False)
        self.lbl_count.setText("0/0")
        self._set_normal_style()
        self._editor.setFocus()
