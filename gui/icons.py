"""Иконки интерфейса — свои SVG одной толщины линий, цвет берётся из темы.

Вместо эмодзи: те рисует шрифт системы, и на Windows, macOS и Linux они
выглядят по-разному (и не перекрашиваются под тему).
"""
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from gui import theme

# viewBox 24×24, линии толщиной 2 со скруглёнными концами
_SHAPES = {
    "pause": '<path d="M9 5v14M15 5v14"/>',
    "play": '<path d="M8 5.5v13l10.5-6.5z"/>',
    "stop": '<rect x="6.5" y="6.5" width="11" height="11" rx="2"/>',
    "save": '<path d="M5 4h11l3 3v13H5z"/><path d="M8 4v5h7V4M8 20v-6h8v6"/>',
    "trash": '<path d="M4 7h16M9.5 7V4.5h5V7M6 7l1 13h10l1-13M10 11v5.5M14 11v5.5"/>',
    "toolbox": '<rect x="3" y="8" width="18" height="12" rx="2"/><path d="M9 8V5h6v3M3 13.5h18"/>',
    "settings": '<path d="M4 6h9M17 6h3M4 12h3M11 12h9M4 18h11M19 18h1"/>'
                '<circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.6 9.4a2.5 2.5 0 1 1 3.4 2.4c-.6.3-1 .8-1 1.5v.4"/>'
            '<circle cx="12" cy="17" r=".6" fill="currentColor"/>',
    "history": '<path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1M3.5 4v4.5H8"/><path d="M12 8v4.5l3 2"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.4-4.4"/>',
    "close": '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
    "chevron_up": '<path d="M6 15l6-6 6 6"/>',
    "chevron_down": '<path d="M6 9l6 6 6-6"/>',
    "phone": '<rect x="7" y="2.5" width="10" height="19" rx="2.5"/><path d="M11 18.5h2"/>',
    "gamepad": '<rect x="2.5" y="7" width="19" height="10.5" rx="5"/><path d="M7.5 10.5v4M5.5 12.5h4"/>'
               '<circle cx="15.5" cy="11.2" r=".9" fill="currentColor"/><circle cx="17.6" cy="13.6" r=".9" fill="currentColor"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><circle cx="12" cy="7.6" r=".6" fill="currentColor"/>',
    "apps": '<rect x="4" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5"/>'
            '<rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5"/>',
    "package": '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/>',
    "bug": '<rect x="8" y="8" width="8" height="12" rx="4"/><path d="M12 12v8M9.5 4.5L11 7M14.5 4.5L13 7'
           'M4 13h4M16 13h4M5 19l3-1.5M19 19l-3-1.5M5 7.5l3 1.5M19 7.5l-3 1.5"/>',
    "code": '<path d="M8.5 7.5L4 12l4.5 4.5M15.5 7.5L20 12l-4.5 4.5M13.5 5l-3 14"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "alert": '<path d="M12 3.5l9 16H3z"/><path d="M12 10v4"/><circle cx="12" cy="17" r=".6" fill="currentColor"/>',
    "download": '<path d="M12 4v11M7 10.5l5 5 5-5M5 20h14"/>',
    "external": '<path d="M14 4h6v6M20 4l-8.5 8.5M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
    "scroll_down": '<path d="M12 4v12M7 11l5 5 5-5M5 20h14"/>',
    "flag": '<path d="M5 21V4M5 4h11l-2 4 2 4H5"/>',
    "layers": '<path d="M12 4l9 4.5-9 4.5-9-4.5z"/><path d="M3 13l9 4.5 9-4.5"/>',
    "clock": '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
    "panel_right": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/>',
}

_RENDER_PX = 64  # рисуем крупно, QIcon сам уменьшит без потери чёткости


def _pixmap(name: str, color: str, px: int = _RENDER_PX) -> QPixmap:
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
           f'stroke="{color}" color="{color}" stroke-width="1.9" stroke-linecap="round" '
           f'stroke-linejoin="round">{_SHAPES[name]}</svg>')
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(0, 0, px, px))
    painter.end()
    return pm


def icon(name: str, color: str | None = None, checked_name: str | None = None,
         checked_color: str | None = None) -> QIcon:
    """Иконка цвета темы. checked_* — вид во включённом состоянии
    (например, «пауза» → «продолжить» у нажатой кнопки)."""
    t = theme.tokens()
    result = QIcon()
    normal = color or t["muted"]
    result.addPixmap(_pixmap(name, normal), QIcon.Normal, QIcon.Off)
    result.addPixmap(_pixmap(name, t["text"]), QIcon.Active, QIcon.Off)
    result.addPixmap(_pixmap(name, t["faint"]), QIcon.Disabled, QIcon.Off)
    on_name = checked_name or name
    on_color = checked_color or t["accent"]
    result.addPixmap(_pixmap(on_name, on_color), QIcon.Normal, QIcon.On)
    result.addPixmap(_pixmap(on_name, on_color), QIcon.Active, QIcon.On)
    return result


def pixmap(name: str, color: str | None = None, size: int = 24) -> QPixmap:
    """Картинка для QLabel (с запасом под экраны HiDPI)."""
    pm = _pixmap(name, color or theme.tokens()["accent"], size * 2)
    pm.setDevicePixelRatio(2)
    return pm


# Инструменты устройства (окно «Инструменты», список приложений)
_SHAPES.update({
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.7 3.8 5.7 3.8 9s-1.3 6.3-3.8 9'
             'c-2.5-2.7-3.8-5.7-3.8-9S9.5 5.7 12 3z"/>',
    "power": '<path d="M12 3v8.5"/><path d="M7 6.5a7.5 7.5 0 1 0 10 0"/>',
    "shield": '<path d="M12 3l7.5 3v5.5c0 4.6-3.2 8.2-7.5 9.5-4.3-1.3-7.5-4.9-7.5-9.5V6z"/><path d="M9 12l2.2 2.2L15.5 10"/>',
    "profile": '<rect x="4.5" y="3" width="15" height="18" rx="2"/><circle cx="12" cy="10" r="2.6"/>'
               '<path d="M8 17c.8-1.8 2.2-2.6 4-2.6s3.2.8 4 2.6"/>',
    "link": '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1.2 1.2"/>'
            '<path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1.2-1.2"/>',
    "folder": '<path d="M3.5 7a2 2 0 0 1 2-2h4l2 2.5h7a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
    "eraser": '<path d="M8.5 20H20M4.6 14.6l8.5-8.5a2 2 0 0 1 2.8 0l3 3a2 2 0 0 1 0 2.8L11 20H8.5'
              'l-3.9-3.9a1 1 0 0 1 0-1.5z"/><path d="M9.5 9.5l5.5 5.5"/>',
    "file_text": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h6"/>',
    "bell": '<path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z"/><path d="M10 20.5a2 2 0 0 0 4 0"/>',
    "copy": '<rect x="8.5" y="8.5" width="11.5" height="11.5" rx="2"/>'
            '<path d="M15.5 8.5V5.5a2 2 0 0 0-2-2H5.5a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h3"/>',
})
