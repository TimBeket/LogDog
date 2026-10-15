"""Общие части окон: шапка (иконка в плашке, заголовок, подзаголовок),
строка списка в две строки, карточка-секция — чтобы окна инструментов
выглядели одинаково."""
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QStyle, QStyledItemDelegate, QVBoxLayout,
)

from gui import icons, theme

SUBTITLE_ROLE = Qt.UserRole + 20


class DialogHeader(QHBoxLayout):
    """[иконка] Заголовок / подзаголовок."""

    def __init__(self, icon_name: str, title: str, subtitle: str = ""):
        super().__init__()
        self.setSpacing(12)
        self.icon_name = icon_name
        self.icon = QLabel()
        self.icon.setProperty("role", "cardIcon")
        self.icon.setObjectName("HeaderIcon")
        self.icon.setFixedSize(44, 44)
        self.icon.setAlignment(Qt.AlignCenter)
        self.addWidget(self.icon, 0, Qt.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        self.title = QLabel(title)
        self.title.setProperty("role", "title")
        texts.addWidget(self.title)
        self.subtitle = QLabel(subtitle)
        self.subtitle.setProperty("role", "muted")
        self.subtitle.setWordWrap(True)
        self.subtitle.setVisible(bool(subtitle))
        texts.addWidget(self.subtitle)
        self.addLayout(texts, 1)
        self.apply_icons()
        theme.theme_signals.theme_changed.connect(self.apply_icons)

    def apply_icons(self, *_):
        self.icon.setPixmap(icons.pixmap(self.icon_name, theme.tokens()["accent"], 24))

    def set_subtitle(self, text: str):
        self.subtitle.setText(text)
        self.subtitle.setVisible(bool(text))


class Section(QFrame):
    """Карточка с подписью сверху: «Система», «Батарея»…"""

    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("Section")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(6)
        caption = QLabel(title.upper())
        caption.setObjectName("SectionTitle")
        layout.addWidget(caption)
        self.body = layout


class TwoLineDelegate(QStyledItemDelegate):
    """Строка списка: иконка, название жирным и серая подпись под ним."""

    def __init__(self, parent=None, icon_size: int = 32):
        super().__init__(parent)
        self.icon_size = icon_size

    def sizeHint(self, option, index):
        return QSize(0, max(self.icon_size + 14, option.fontMetrics.height() * 2 + 16))

    def paint(self, painter, option, index):
        t = theme.tokens()
        painter.save()
        rect = option.rect.adjusted(2, 1, -2, -1)
        selected = option.state & QStyle.State_Selected
        hovered = option.state & QStyle.State_MouseOver
        if selected or hovered:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(t["accent_soft"] if selected else t["hover"]))
            painter.drawRoundedRect(rect, 6, 6)
        x = rect.left() + 10
        icon = index.data(Qt.DecorationRole)
        if icon is not None and not icon.isNull():
            size = self.icon_size
            icon.paint(painter, QRect(x, rect.center().y() - size // 2, size, size))
            x += size + 12
        title = index.data(Qt.DisplayRole) or ""
        subtitle = index.data(SUBTITLE_ROLE) or ""
        enabled = bool(index.flags() & Qt.ItemIsEnabled)
        bold = QFont(option.font)
        bold.setWeight(QFont.DemiBold)
        text_rect = QRect(x, rect.top() + 6, rect.right() - x - 10, rect.height() - 12)
        painter.setFont(bold)
        painter.setPen(QColor(t["text"] if enabled else t["muted"]))
        top = text_rect.adjusted(0, 0, 0, -text_rect.height() // 2) if subtitle else text_rect
        painter.drawText(top, Qt.AlignLeft | Qt.AlignVCenter,
                         painter.fontMetrics().elidedText(title, Qt.ElideRight, top.width()))
        if subtitle:
            painter.setFont(option.font)
            painter.setPen(QColor(t["muted"]))
            bottom = text_rect.adjusted(0, text_rect.height() // 2, 0, 0)
            painter.drawText(bottom, Qt.AlignLeft | Qt.AlignVCenter,
                             painter.fontMetrics().elidedText(subtitle, Qt.ElideRight, bottom.width()))
        painter.restore()
