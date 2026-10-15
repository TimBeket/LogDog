"""Поле фильтра с подсветкой синтаксиса, проверкой и списком подсказок.

Обычный однострочный QLineEdit — со всем его поведением (выделение, отмена,
кнопка очистки, иконки). Цвет накладывается форматами QInputMethodEvent (так
QLineEdit умеет раскрашивать отдельные символы).

Подсказки — список под полем, как в редакторе кода: появляется при наборе
и по Ctrl+Space; ↑/↓ — выбор, Enter/Tab — вставить, Esc — закрыть. Список —
дочерний виджет главного окна, а не отдельное всплывающее окно: на Wayland
окну-подсказке, открытому не по щелчку, композитор отказывает или ставит
его куда попало (так было в первой попытке подсказок), а клавиатура остаётся в
поле.
"""
from typing import Callable, Iterable, List, Optional

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QInputMethodEvent, QTextCharFormat
from PySide6.QtWidgets import (
    QApplication, QFrame, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QStyle, QStyledItemDelegate, QVBoxLayout,
)

from core.filter_syntax import Analysis, Completion, analyze, complete
from gui import theme
from gui.theme import theme_signals

_SPAN_COLORS = {"field": "syn_field", "value": "syn_value", "operator": "syn_operator",
                "string": "syn_string", "paren": "muted"}
_HINT_ROLE = Qt.UserRole + 1


class _SuggestionDelegate(QStyledItemDelegate):
    """Строка списка: вариант слева, пояснение справа серым — как в IDE."""

    def paint(self, painter, option, index):
        t = theme.tokens()
        painter.save()
        rect = option.rect.adjusted(4, 1, -4, -1)
        if option.state & QStyle.State_Selected:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(t["accent_soft"]))
            painter.drawRoundedRect(rect, 5, 5)
        text = index.data(Qt.DisplayRole)
        hint = index.data(_HINT_ROLE) or ""
        fm = option.fontMetrics
        inner = rect.adjusted(8, 0, -8, 0)
        painter.setPen(QColor(t["text"]))
        painter.drawText(inner, Qt.AlignLeft | Qt.AlignVCenter, text)
        text_w = fm.horizontalAdvance(text) + 24
        if hint and inner.width() - text_w > 40:
            painter.setPen(QColor(t["muted"]))
            hint = fm.elidedText(hint, Qt.ElideRight, inner.width() - text_w)
            painter.drawText(inner, Qt.AlignRight | Qt.AlignVCenter, hint)
        painter.restore()

    def sizeHint(self, option, index):
        return QSize(0, option.fontMetrics.height() + 10)


class SuggestionPopup(QFrame):
    """Список подсказок + строка про ошибку фильтра. Без фокуса: клавиатура
    остаётся в поле, щелчок по варианту фокус не забирает."""

    chosen = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FilterPopup")
        self.setFocusPolicy(Qt.NoFocus)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        self.list = QListWidget()
        self.list.setObjectName("FilterPopupList")
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.viewport().setFocusPolicy(Qt.NoFocus)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setItemDelegate(_SuggestionDelegate(self.list))
        self.list.clicked.connect(lambda index: self.chosen.emit(index.row()))
        layout.addWidget(self.list)
        self.footer = QLabel()
        self.footer.setObjectName("FilterPopupFooter")
        self.footer.setWordWrap(True)
        layout.addWidget(self.footer)
        self.hide()

    def show_for(self, edit: QLineEdit, anchor: int, items, problem: Optional[tuple], keys_hint: str):
        """items — [(текст, пояснение)], problem — (текст, ключ цвета) или None."""
        window = edit.window()
        if self.parentWidget() is not window:
            self.setParent(window)
        self.list.clear()
        for text, hint in items:
            item = QListWidgetItem(text)
            item.setData(_HINT_ROLE, hint)
            self.list.addItem(item)
        self.list.setVisible(bool(items))
        if items:
            self.list.setCurrentRow(0)

        t = theme.tokens()
        if problem:
            message, color_key = problem
            self.footer.setText(f'<span style="color:{t[color_key]}">● {message}</span>')
        else:
            self.footer.setText(f'<span style="color:{t["faint"]}">{keys_hint}</span>')
        self.footer.setVisible(bool(problem) or bool(items))

        fm = self.list.fontMetrics()
        widest = max([fm.horizontalAdvance(text) + fm.horizontalAdvance(hint) + 64 for text, hint in items] or [0])
        width = min(max(300, widest), max(300, window.width() - 24))
        row_h = fm.height() + 10
        rows = min(len(items), 8)
        self.list.setFixedHeight(rows * row_h + 4 if items else 0)
        self.footer.setFixedWidth(width - 16)
        self.resize(width, self.sizeHint().height())

        # под полем, от начала подсказываемого слова; не выходя за окно
        x = edit.cursorRect().left() - edit.fontMetrics().horizontalAdvance(edit.text()[anchor:edit.cursorPosition()])
        pos = edit.mapTo(window, QPoint(max(0, x), edit.height() + 2))
        pos.setX(max(8, min(pos.x(), window.width() - width - 8)))
        self.move(pos)
        self.show()
        self.raise_()

    def move_selection(self, step: int):
        count = self.list.count()
        if count:
            self.list.setCurrentRow((self.list.currentRow() + step) % count)

    def current_row(self) -> int:
        return self.list.currentRow() if self.list.isVisible() else -1


class FilterLineEdit(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._procs: Callable[[], Iterable[str]] = lambda: []
        self._analysis = Analysis()
        self._completion: Optional[Completion] = None
        self._forced = False      # Ctrl+Space — показывать и без набранного начала
        self._formatting = False
        self.popup = SuggestionPopup()
        self.popup.chosen.connect(self._accept)
        # Ошибку показываем, когда набор замер: пока печатаешь «(level:…»,
        # «скобка не закрыта» — не ошибка, а ещё не дописанный фильтр.
        self._problem_timer = QTimer(self)
        self._problem_timer.setSingleShot(True)
        self._problem_timer.setInterval(800)
        self._problem_timer.timeout.connect(lambda: self._refresh_popup(show_problem=True))
        self.textEdited.connect(self._on_text_edited)
        self.textChanged.connect(self._on_text_changed)
        self.cursorPositionChanged.connect(self._on_cursor_moved)
        theme_signals.theme_changed.connect(self._apply_formats)

    def set_proc_source(self, procs: Callable[[], Iterable[str]]) -> None:
        """Откуда брать имена процессов для proc: (из полученных логов)."""
        self._procs = procs

    @property
    def analysis(self) -> Analysis:
        return self._analysis

    def has_errors(self) -> bool:
        return any(p.severity == "error" for p in self._analysis.problems)

    # ── Разбор и подсветка ───────────────────────────────────────────────

    def _on_text_changed(self, _text: str):
        if self._formatting:
            return
        self._analysis = analyze(self.text())
        self._apply_formats()
        if self.popup.isVisible():
            self._refresh_popup()

    def _on_text_edited(self, _text: str):
        """Набор с клавиатуры (не setText из истории) — показать подсказки."""
        self._refresh_popup()
        self._problem_timer.start()

    def _on_cursor_moved(self, *_):
        if not self._formatting and self.popup.isVisible():
            self._refresh_popup()

    def _apply_formats(self, *_):
        """Цвет по символам: сначала токены, поверх — волнистое подчёркивание
        ошибок. Соседние символы с одинаковым видом — одним отрезком."""
        text = self.text()
        t = theme.tokens()
        chars: List[tuple] = [(None, False, None)] * len(text)
        for span in self._analysis.spans:
            color = t[_SPAN_COLORS[span.kind]]
            for i in range(span.start, min(span.end, len(text))):
                chars[i] = (color, span.kind == "operator", None)
        for problem in self._analysis.problems:
            wave = t["danger"] if problem.severity == "error" else t["warn"]
            for i in range(problem.start, min(problem.end, len(text))):
                color, bold, _ = chars[i]
                chars[i] = (color, bold, wave)

        cursor = self.cursorPosition()
        attributes = []
        i = 0
        while i < len(chars):
            j = i
            while j < len(chars) and chars[j] == chars[i]:
                j += 1
            color, bold, wave = chars[i]
            if color or bold or wave:
                fmt = QTextCharFormat()
                if color:
                    fmt.setForeground(QColor(color))
                if bold:
                    fmt.setFontWeight(QFont.DemiBold)
                if wave:
                    fmt.setUnderlineStyle(QTextCharFormat.WaveUnderline)
                    fmt.setUnderlineColor(QColor(wave))
                attributes.append(QInputMethodEvent.Attribute(
                    QInputMethodEvent.TextFormat, i - cursor, j - i, fmt))
            i = j
        self._formatting = True
        try:
            QApplication.sendEvent(self, QInputMethodEvent("", attributes))
        finally:
            self._formatting = False
        self.setToolTip("\n".join(p.message for p in self._analysis.problems))

    # ── Подсказки ────────────────────────────────────────────────────────

    def _problem_near_cursor(self) -> Optional[tuple]:
        cursor = self.cursorPosition()
        problems = sorted(self._analysis.problems,
                          key=lambda p: (p.severity != "error", abs(p.start - cursor)))
        if not problems:
            return None
        p = problems[0]
        return p.message, ("danger" if p.severity == "error" else "warn")

    def _refresh_popup(self, show_problem: bool = False):
        c = complete(self.text(), self.cursorPosition(), list(self._procs()))
        self._completion = c
        items = [(i.text.strip(), i.hint) for i in c.items] if c else []
        typed = bool(c) and c.end > c.start
        after_colon = bool(c) and c.start > 0 and self.text()[c.start - 1] == ":"
        want_list = bool(items) and (self._forced or typed or after_colon)
        problem = self._problem_near_cursor() if show_problem else None
        if not self.hasFocus() or self.hasSelectedText() or not (want_list or problem):
            self.popup.hide()
            return
        self.popup.show_for(self, c.start if c else self.cursorPosition(), items if want_list else [],
                            problem, "↵ / Tab — вставить  ·  Esc — закрыть")

    def _accept(self, row: int = -1) -> bool:
        c = self._completion
        row = row if row >= 0 else self.popup.current_row()
        if not c or row < 0 or row >= len(c.items):
            return False
        self.setSelection(c.start, c.end - c.start)
        self.insert(c.items[row].text)  # через insert — работает отмена (Ctrl+Z)
        self._forced = False
        self.setFocus()
        self._refresh_popup()
        return True

    def hide_popup(self):
        self._forced = False
        self.popup.hide()

    def event(self, event):
        # Tab обычно переводит фокус — его ловим раньше keyPressEvent.
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Tab and self.popup.current_row() >= 0:
            return self._accept() or True
        return super().event(event)

    def keyPressEvent(self, event):
        key = event.key()
        if self.popup.isVisible():
            if key == Qt.Key_Down and self.popup.current_row() >= 0:
                self.popup.move_selection(1)
                return
            if key == Qt.Key_Up and self.popup.current_row() >= 0:
                self.popup.move_selection(-1)
                return
            if key in (Qt.Key_Return, Qt.Key_Enter) and self.popup.current_row() >= 0:
                self._accept()
                return
            if key == Qt.Key_Escape:
                self.hide_popup()
                return
        if key == Qt.Key_Space and event.modifiers() & Qt.ControlModifier:
            self._forced = True
            self._refresh_popup(show_problem=True)
            return
        if key in (Qt.Key_Return, Qt.Key_Enter):
            self.hide_popup()
        super().keyPressEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self._problem_timer.stop()
        self.hide_popup()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.hide_popup()  # окно меняет размер — список встал бы не там
