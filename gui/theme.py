"""Тёмная и светлая темы: палитра цветов (TOKENS) и одна таблица стилей на обе.

Цвета задаются только здесь. Виджеты берут их через tokens() / log_color(),
а иконки (gui/icons.py) перекрашиваются по сигналу theme_changed — без
этого после смены темы они остались бы цвета старой темы.
"""
import tempfile
from pathlib import Path
from string import Template

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

TOKENS = {
    "Dark": {
        "window": "#2B2D30",      # шапка, боковая панель, окна
        "base": "#1E1F22",        # поле логов, поля ввода
        "raised": "#393B40",      # кнопки
        "hover": "#43454A",
        "border": "#393B40",
        "border_strong": "#4E5157",
        "text": "#DFE1E5",
        "muted": "#9DA0A8",
        "faint": "#6F737A",
        "accent": "#3DD68C",      # мятный — из иконки
        "accent_hover": "#5FE3A3",
        "on_accent": "#0F2A1D",
        "accent_soft": "#24493A",
        "selection": "#2E5D49",
        "danger": "#F2676B",
        "danger_soft": "#4A2328",
        "warn": "#E5C07B",
        # подсветка синтаксиса фильтра
        "syn_field": "#56A8F5",
        "syn_value": "#C77DBB",
        "syn_operator": "#CF8E6D",
        "syn_string": "#6AAB73",
    },
    "Light": {
        "window": "#F2F3F5",
        "base": "#FFFFFF",
        "raised": "#FFFFFF",
        "hover": "#E6E8EB",
        "border": "#DCDFE4",
        "border_strong": "#C4C7CE",
        "text": "#1F2328",
        "muted": "#5F6670",
        "faint": "#8C929B",
        "accent": "#0F9D63",
        "accent_hover": "#0B8553",
        "on_accent": "#FFFFFF",
        "accent_soft": "#DDF3E9",
        "selection": "#C9ECDC",
        "danger": "#CF222E",
        "danger_soft": "#FBE3E4",
        "warn": "#9A6700",
        "syn_field": "#0B5FB0",
        "syn_value": "#871094",
        "syn_operator": "#B34700",
        "syn_string": "#067D17",
    },
}

# Цвета уровней логов по умолчанию — свои у каждой темы: жёлтый и ярко-зелёный
# тёмной темы на белом фоне не читаются.
LOG_COLORS = {
    "Dark": {"error": "#FF6B6B", "warn": "#E5C07B", "info": "#7AA2F7",
             "debug": "#9ECE6A", "system": "#8B8F97"},
    "Light": {"error": "#C9252D", "warn": "#9A6700", "info": "#1F5FBF",
              "debug": "#2F7D32", "system": "#6E7781"},
}

_current = "Dark"


class _ThemeSignals(QObject):
    theme_changed = Signal(str)


theme_signals = _ThemeSignals()


def current() -> str:
    return _current


def tokens() -> dict:
    return TOKENS[_current]


def log_color(level: str) -> str:
    return LOG_COLORS[_current].get(level, LOG_COLORS[_current]["info"])


def _arrow_files(t: dict) -> dict:
    """Стрелки для выпадающих списков и галочка — файлами: в таблице стилей
    Qt картинку можно задать только путём."""
    folder = Path(tempfile.gettempdir()) / "logdog-theme"
    folder.mkdir(exist_ok=True)
    shapes = {
        "down": '<path d="M6 9l6 6 6-6"/>',
        "up": '<path d="M6 15l6-6 6 6"/>',
        "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    }
    files = {}
    for name, shape in shapes.items():
        color = t["on_accent"] if name == "check" else t["muted"]
        width = 3 if name == "check" else 2
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
               f'stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round">{shape}</svg>')
        path = folder / f"{name}-{color.lstrip('#')}.svg"
        if not path.exists():
            path.write_text(svg, encoding="utf-8")
        files[name] = path.as_posix()
    return files


_STYLESHEET = Template("""
QWidget {
    background-color: $window;
    color: $text;
    selection-background-color: $selection;
    selection-color: $text;
}
QToolTip {
    background-color: $base;
    color: $text;
    border: 1px solid $border_strong;
    padding: 4px 6px;
}

/* Поля ввода */
QLineEdit, QComboBox, QSpinBox {
    background-color: $base;
    border: 1px solid $border_strong;
    border-radius: 6px;
    padding: 4px 8px;
    min-height: 20px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: $accent; }
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled { color: $faint; background-color: $window; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: url($arrow_down); width: 14px; height: 14px; }
QComboBox QAbstractItemView {
    background-color: $base;
    border: 1px solid $border_strong;
    selection-background-color: $accent_soft;
    outline: none;
    padding: 4px;
}
QSpinBox::up-button, QSpinBox::down-button { border: none; width: 18px; background: transparent; }
QSpinBox::up-arrow { image: url($arrow_up); width: 12px; height: 12px; }
QSpinBox::down-arrow { image: url($arrow_down); width: 12px; height: 12px; }

QTextEdit, QTextBrowser, QPlainTextEdit, QListWidget, QTableWidget, QTreeWidget {
    background-color: $base;
    border: 1px solid $border;
    border-radius: 8px;
}
QPlainTextEdit#LogView {
    border: none;
    border-radius: 0;
    padding: 4px 8px;
}
QListWidget::item, QTableWidget::item { padding: 4px 6px; border-radius: 4px; }
QListWidget::item:selected, QTableWidget::item:selected { background-color: $accent_soft; color: $text; }
QListWidget::item:hover { background-color: $hover; }
QHeaderView::section {
    background-color: $window;
    color: $muted;
    border: none;
    border-bottom: 1px solid $border;
    padding: 4px 6px;
}

/* Кнопки */
QPushButton {
    background-color: $raised;
    border: 1px solid $border_strong;
    border-radius: 6px;
    padding: 5px 14px;
    min-height: 20px;
}
QPushButton:hover { background-color: $hover; }
QPushButton:pressed { background-color: $border_strong; }
QPushButton:disabled { color: $faint; background-color: $window; border-color: $border; }
QPushButton:default { border-color: $accent; }
QPushButton[variant="primary"] {
    background-color: $accent;
    border: 1px solid $accent;
    color: $on_accent;
    font-weight: 600;
}
QPushButton[variant="primary"]:hover { background-color: $accent_hover; border-color: $accent_hover; }
QPushButton[variant="primary"]:disabled { background-color: $accent_soft; border-color: $accent_soft; color: $faint; }
QPushButton[variant="danger"] { color: $danger; }
QPushButton[variant="ghost"] { background: transparent; border-color: transparent; color: $muted; }
QPushButton[variant="ghost"]:hover { background-color: $hover; color: $text; }

QToolButton {
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 4px;
}
QToolButton:hover { background-color: $hover; }
QToolButton:pressed { background-color: $border_strong; }
QToolButton:checked { background-color: $accent_soft; }
QToolButton:disabled { background: transparent; }

/* Карточки инструментов */
QPushButton[variant="card"] {
    background-color: $base;
    border: 1px solid $border;
    border-radius: 10px;
    padding: 0;
    text-align: left;
    min-height: 60px;
    max-height: 60px;
}
QPushButton[variant="card"]:hover { border-color: $accent; background-color: $base; }
QPushButton[variant="card"]:disabled { background-color: $window; border-color: $border; }
QPushButton[variant="card"] QLabel { background: transparent; }
QPushButton[variant="card"] QLabel:disabled { color: $faint; }
QPushButton[variant="card"] QLabel[role="cardIcon"] { background-color: $accent_soft; border-radius: 8px; }
QPushButton[variant="card"] QLabel[role="cardIcon"]:disabled { background-color: $hover; }

/* Уведомление о новом краше (gui/widgets/crash_toast.py) */
QFrame#CrashToast { background-color: $base; border: 1px solid $border_strong; border-left: 3px solid $danger; border-radius: 10px; }
QFrame#CrashToast QLabel { background: transparent; }

/* Флажки */
QCheckBox { spacing: 8px; background: transparent; }
QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 1px solid $border_strong;
    border-radius: 4px;
    background-color: $base;
}
QCheckBox::indicator:hover { border-color: $accent; }
QCheckBox::indicator:checked { background-color: $accent; border-color: $accent; image: url($check); }

/* Группы настроек */
QGroupBox {
    border: 1px solid $border;
    border-radius: 10px;
    margin-top: 22px;
    padding: 10px 12px 8px 12px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 4px;
    top: 2px;
    color: $muted;
}
QGroupBox QLabel { font-weight: normal; }

/* Прогресс */
QProgressBar {
    background-color: $raised;
    border: none;
    border-radius: 3px;
    max-height: 6px;
    min-height: 6px;
}
QProgressBar::chunk { background-color: $accent; border-radius: 3px; }

/* Полосы прокрутки */
QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px; }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background-color: $border_strong;
    border-radius: 4px;
    min-height: 28px;
    min-width: 28px;
    margin: 1px;
}
QScrollBar::handle:hover { background-color: $faint; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; border: none; background: none; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }

/* Шапка, боковая панель, строка состояния */
QWidget#HeaderBar { border-bottom: 1px solid $border; }
QWidget#SideBar { border-right: 1px solid $border; }
QFrame#SideBarSeparator { background-color: $border; max-height: 1px; min-height: 1px; border: none; }
QLabel#AppTitle { font-size: 15px; font-weight: 700; }
QLabel[role="muted"] { color: $muted; background: transparent; }
QLabel[role="title"] { font-size: 18px; font-weight: 700; background: transparent; }
QLabel[role="chip"] {
    background-color: $accent_soft;
    color: $accent;
    border-radius: 9px;
    padding: 2px 10px;
    font-weight: 600;
}
QStatusBar { border-top: 1px solid $border; color: $muted; }
QStatusBar QLabel { background: transparent; color: $muted; padding: 0 6px; }
QStatusBar::item { border: none; }

/* Поиск по логам */
QWidget#FindBar { border-bottom: 1px solid $border; }
QLineEdit#FindBarInput[notFound="true"] { border-color: $danger; background-color: $danger_soft; color: $danger; }
QLabel#FindBarCount[notFound="true"] { color: $danger; }

/* История фильтров */
QWidget#FilterHistory { background-color: $base; border: 1px solid $border_strong; border-radius: 8px; }
QWidget#FilterHistory QScrollArea, QWidget#FilterHistory QWidget#HistoryContent { background-color: $base; border: none; }
QWidget#HistoryItem { background-color: $base; border-radius: 6px; }
QWidget#HistoryItem[hovered="true"] { background-color: $hover; }
QWidget#HistoryItem QLabel { background: transparent; }

QDialog QTextBrowser#Changelog { padding: 6px 10px; }

/* Вкладки правой панели */
QTabWidget#SidePanel::pane { border: none; border-left: 1px solid $border; }
QTabWidget#SidePanel QTabBar::tab {
    background: transparent;
    color: $muted;
    padding: 7px 12px;
    border: none;
    border-bottom: 2px solid transparent;
}
QTabWidget#SidePanel QTabBar::tab:selected { color: $text; border-bottom-color: $accent; }
QTabWidget#SidePanel QTabBar::tab:hover { color: $text; }
QSplitter::handle { background-color: $border; width: 1px; }

/* Окна инструментов: секции-карточки и плашка иконки в шапке */
QFrame#Section { background-color: $base; border: 1px solid $border; border-radius: 10px; }
QFrame#Section QLabel { background: transparent; }
QLabel#SectionTitle { color: $faint; font-size: 11px; font-weight: 700; letter-spacing: 1px; }
QLabel#HeaderIcon { background-color: $accent_soft; border-radius: 10px; }
QLabel[role="key"] { color: $muted; background: transparent; }
QLabel[role="value"] { background: transparent; }

/* Обучение */
QFrame#TourBubble { background-color: $base; border: 1px solid $accent; border-radius: 12px; }
QFrame#TourBubble QLabel { background: transparent; }
QLabel#TourTitle { font-size: 15px; font-weight: 700; }

/* Подсказки под полем фильтра */
QFrame#FilterPopup { background-color: $base; border: 1px solid $border_strong; border-radius: 8px; }
QFrame#FilterPopup QListWidget { border: none; background: transparent; outline: none; }
QFrame#FilterPopup QLabel { background: transparent; padding: 2px 8px 2px 8px; }
""")


def apply_theme(app: QApplication, theme_name: str):
    global _current
    _current = "Dark" if theme_name == "Dark" else "Light"
    t = TOKENS[_current]
    app.setStyle("Fusion")

    palette = QPalette()
    for role, key in [(QPalette.Window, "window"), (QPalette.WindowText, "text"),
                      (QPalette.Base, "base"), (QPalette.AlternateBase, "window"),
                      (QPalette.ToolTipBase, "base"), (QPalette.ToolTipText, "text"),
                      (QPalette.Text, "text"), (QPalette.Button, "raised"),
                      (QPalette.ButtonText, "text"), (QPalette.BrightText, "danger"),
                      (QPalette.Link, "accent"), (QPalette.Highlight, "selection"),
                      (QPalette.HighlightedText, "text"), (QPalette.PlaceholderText, "faint"),
                      (QPalette.Mid, "border_strong"), (QPalette.Midlight, "hover"),
                      (QPalette.Dark, "border_strong")]:
        palette.setColor(role, QColor(t[key]))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(t["faint"]))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(t["faint"]))
    palette.setColor(QPalette.Disabled, QPalette.WindowText, QColor(t["faint"]))
    app.setPalette(palette)

    arrows = _arrow_files(t)
    app.setStyleSheet(_STYLESHEET.substitute(
        t, arrow_down=arrows["down"], arrow_up=arrows["up"], check=arrows["check"]))
    theme_signals.theme_changed.emit(_current)


def clear_stale_hover(window) -> None:
    """Окно заблокировал модальный диалог (открылся по щелчку по карточке или
    кнопке) — сбросить у кнопок «мышь над ней». Qt не присылает им «мышь ушла»,
    и подсветка наведения оставалась висеть, пока по кнопке снова не проведут
    мышью (на скриншоте её не видно: окно теряет фокус и перерисовывается)."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QAbstractButton
    for button in window.findChildren(QAbstractButton):
        if button.testAttribute(Qt.WA_UnderMouse):
            button.setAttribute(Qt.WA_UnderMouse, False)
            button.update()


def repolish(widget) -> None:
    """После смены свойства, по которому выбирается стиль (variant, notFound…)."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
