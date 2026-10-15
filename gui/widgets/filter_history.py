from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QToolButton, QHBoxLayout, QScrollArea
from PySide6.QtCore import Qt, QPoint, QSize
from PySide6.QtGui import QColor, QPainter
from core.filter_syntax import analyze
from gui import icons, theme
from gui.widgets.filter_edit import _SPAN_COLORS
from utils.helpers import get_app_data_dir
from utils.logger import logger

class _HistoryText(QWidget):
    """Фильтр из истории — с той же подсветкой, что в поле, и с «…» в конце,
    если не влезает (вместо горизонтальной прокрутки)."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.text = text
        self._spans = analyze(text).spans
        self.setToolTip(text)
        self.setMinimumWidth(40)
        self.setFixedHeight(self.fontMetrics().height() + 6)

    def paintEvent(self, event):
        t = theme.tokens()
        painter = QPainter(self)
        fm = self.fontMetrics()
        elided = fm.elidedText(self.text, Qt.ElideRight, self.width())
        visible = len(elided) - 1 if elided != self.text else len(self.text)
        colors = [t["text"]] * len(self.text)
        for span in self._spans:
            for i in range(span.start, span.end):
                colors[i] = t[_SPAN_COLORS[span.kind]]
        x = 0
        baseline = (self.height() + fm.ascent() - fm.descent()) // 2
        i = 0
        while i < visible:
            j = i
            while j < visible and colors[j] == colors[i]:
                j += 1
            chunk = self.text[i:j]
            painter.setPen(QColor(colors[i]))
            painter.drawText(x, baseline, chunk)
            x += fm.horizontalAdvance(chunk)
            i = j
        if visible < len(self.text):
            painter.setPen(QColor(t["muted"]))
            painter.drawText(x, baseline, "…")
        painter.end()


class HistoryItemWidget(QWidget):
    def __init__(self, filter_text, parent_widget, main_window):
        super().__init__()
        self.filter_text = filter_text
        self.parent_widget = parent_widget
        self.main_window = main_window
        self.is_hovered = False

        self.setObjectName("HistoryItem")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setCursor(Qt.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 8, 2)
        layout.setSpacing(4)

        # Крестик слева: справа он уезжал за край у длинных фильтров.
        delete_btn = QToolButton()
        delete_btn.setIcon(icons.icon("close"))
        delete_btn.setIconSize(QSize(14, 14))
        delete_btn.setFixedSize(24, 24)
        delete_btn.setToolTip("Удалить из истории")
        delete_btn.setCursor(Qt.ArrowCursor)
        delete_btn.clicked.connect(lambda: self.parent_widget.remove_filter(self.filter_text))

        self.label = _HistoryText(filter_text)

        layout.addWidget(delete_btn, 0)
        layout.addWidget(self.label, 1)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.main_window.apply_history_filter(self.filter_text)
            self.parent_widget.hide()
        super().mousePressEvent(event)

    def enterEvent(self, event):
        self.is_hovered = True
        self.update_style()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.is_hovered = False
        self.update_style()
        super().leaveEvent(event)

    def update_style(self):
        self.setProperty("hovered", self.is_hovered)
        theme.repolish(self)

class FilterHistoryWidget(QWidget):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window
        self.setWindowFlags(Qt.Popup)
        self.setObjectName("FilterHistory")
        self.setAttribute(Qt.WA_StyledBackground)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.content_widget = QWidget()
        self.content_widget.setObjectName("HistoryContent")
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(1)

        self.scroll_area.setWidget(self.content_widget)
        layout.addWidget(self.scroll_area)

        self.history_items = []
        self.history_file = get_app_data_dir() / "filter_history.txt"
        self.load_history()
        self.update_display()

    def load_history(self):
        try:
            if self.history_file.exists():
                with open(self.history_file, "r", encoding="utf-8") as f:
                    self.history_items = f.read().splitlines()[:50]
        except Exception as e:
            logger.error("Failed to load filter history: %r", e)

    def save_history(self):
        try:
            with open(self.history_file, "w", encoding="utf-8") as f:
                for item in self.history_items:
                    f.write(item + "\n")
        except Exception as e:
            logger.error("Failed to save filter history: %r", e)

    def add_filter(self, filter_text):
        if not filter_text.strip(): return
        if filter_text in self.history_items:
            self.history_items.remove(filter_text)
        self.history_items.insert(0, filter_text)
        self.history_items = self.history_items[:50]
        self.save_history()
        self.update_display()

    def remove_filter(self, filter_text):
        if filter_text in self.history_items:
            self.history_items.remove(filter_text)
            self.save_history()
            self.update_display()

    def update_display(self):
        for i in reversed(range(self.content_layout.count())):
            widget = self.content_layout.itemAt(i).widget()
            if widget:
                # убрать сразу: deleteLater сработает только в цикле событий,
                # а до этого старые строки стояли бы рядом с новыми
                self.content_layout.removeWidget(widget)
                widget.hide()
                widget.deleteLater()

        for filter_text in self.history_items:
            item_widget = HistoryItemWidget(filter_text, self, self.main_window)
            self.content_layout.addWidget(item_widget)
        if not self.history_items:
            empty = QLabel("Здесь появятся последние фильтры — введите фильтр и нажмите Enter")
            empty.setProperty("role", "muted")
            empty.setContentsMargins(8, 8, 8, 8)
            empty.setWordWrap(True)
            self.content_layout.addWidget(empty)

    def show_below_widget(self, widget):
        pos = widget.mapToGlobal(QPoint(0, widget.height()))
        self.move(pos)
        popup_width = max(360, widget.width())
        self.resize(popup_width, self._calculate_height())
        self.show()
        self.raise_()
        self.activateWindow()

    def _calculate_height(self):
        if not self.history_items:
            return 64
        content_height = self.content_layout.sizeHint().height()
        return min(220, max(50, content_height + 4))
