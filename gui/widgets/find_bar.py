from PySide6.QtCore import Qt, QTimer, QEvent, QSize
from PySide6.QtGui import QTextCursor, QColor, QTextDocument, QShortcut, QKeySequence, QIcon
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLineEdit, QToolButton, QLabel, QTextEdit
)

from gui import icons, theme
from gui.theme import theme_signals


class FindBar(QWidget):
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.setObjectName("FindBar")
        self._editor = editor
        self._matches = []
        self._current_idx = -1
        self._search_text = ""

        self._debounce_timer = QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.timeout.connect(self._on_debounced_search)

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
        self._editor.document().contentsChanged.connect(self._on_document_changed)

    def eventFilter(self, obj, event):
        if obj is self.input and event.type() == QEvent.KeyPress:
            key = event.key()
            if key in (Qt.Key_Return, Qt.Key_Enter):
                if event.modifiers() & Qt.ShiftModifier:
                    self._find_prev()
                else:
                    self._find_next()
                return True
            elif key == Qt.Key_Down:
                self._find_next()
                return True
            elif key == Qt.Key_Up:
                self._find_prev()
                return True
            elif key == Qt.Key_Escape:
                self.hide()
                return True
        return super().eventFilter(obj, event)

    def _on_text_changed(self, text):
        self._search_text = text
        self._search()

    def _on_document_changed(self):
        if self.isVisible() and self._search_text:
            self._debounce_timer.start(200)

    def _search(self):
        self._debounce_timer.stop()
        self._do_search()

    def _on_debounced_search(self):
        self._do_search(jump_to_first=False)

    def _do_search(self, jump_to_first=True):
        text = self._search_text

        prev_cursor = None
        if not jump_to_first and 0 <= self._current_idx < len(self._matches):
            prev_cursor = self._matches[self._current_idx]

        self._matches.clear()
        self._current_idx = -1

        if not text:
            self._clear_highlights()
            self.lbl_count.setText("0/0")
            self._set_normal_style()
            return

        doc = self._editor.document()
        cursor = QTextCursor(doc)

        while True:
            cursor = doc.find(text, cursor, QTextDocument.FindFlags())
            if cursor.isNull():
                break
            self._matches.append(QTextCursor(cursor))

        self._highlight_all()

        if not self._matches:
            self._set_red_style()
            self.lbl_count.setText("0/0")
            return

        if prev_cursor is not None:
            target_pos = prev_cursor.selectionStart()
            idx = next((i for i, m in enumerate(self._matches) if m.selectionStart() == target_pos), None)
            if idx is None:
                idx = next((i for i, m in enumerate(self._matches) if m.selectionStart() >= target_pos),
                           len(self._matches) - 1)
            self._current_idx = idx
            self._update_counter()
            self._set_normal_style()
            self._highlight_all()
            return

        self._current_idx = 0
        self._go_to_match(0)

    def _highlight_all(self):
        selections = []
        for i, cursor in enumerate(self._matches):
            sel = QTextEdit.ExtraSelection()
            sel.cursor = QTextCursor(cursor)
            if i == self._current_idx:
                sel.format.setBackground(QColor(255, 165, 0, 180))
            else:
                sel.format.setBackground(QColor(255, 235, 59, 80))
            selections.append(sel)
        self._editor.setExtraSelections(selections)

    def _clear_highlights(self):
        self._editor.setExtraSelections([])

    def _find_next(self):
        if not self._matches:
            return
        idx = (self._current_idx + 1) % len(self._matches)
        self._current_idx = idx
        self._go_to_match(idx)

    def _find_prev(self):
        if not self._matches:
            return
        idx = (self._current_idx - 1) % len(self._matches)
        self._current_idx = idx
        self._go_to_match(idx)

    def _go_to_match(self, idx):
        cursor = self._matches[idx]
        self._editor.setTextCursor(cursor)
        self._editor.centerCursor()
        self._update_counter()
        self._set_normal_style()
        self._highlight_all()

    def _update_counter(self):
        current = self._current_idx + 1 if self._current_idx >= 0 else 0
        total = len(self._matches)
        self.lbl_count.setText(f"{current}/{total}")

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
        self._clear_highlights()
        self._matches.clear()
        self._current_idx = -1
        self._search_text = ""
        self.input.clear()
        self.lbl_count.setText("0/0")
        self._set_normal_style()
        self._debounce_timer.stop()
        self._editor.setFocus()
