"""Уведомление о новом краше — маленькая карточка в правом верхнем углу окна.

Дочерний виджет главного окна, а не отдельное окно: не забирает фокус и не
всплывает поверх других программ (на Wayland отдельные всплывающие окна ещё и
ставятся куда попало). Сама исчезает через HIDE_AFTER_MS; пока над ней мышь —
не исчезает.
"""
from datetime import datetime

from PySide6.QtCore import QElapsedTimer, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QBoxLayout, QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout

from core.crash_alerts import FREQUENT_CRASHES, CrashReport
from gui import icons, theme

HIDE_AFTER_MS = 8000
WIDTH = 400
# ширина колонки с текстом: WIDTH − поля (12 + 8) − значок (22) − промежутки (2×10) − «×» (24)
_TEXT_WIDTH = WIDTH - 12 - 8 - 22 - 2 * 10 - 24


def _times(n: int) -> str:
    """«раз» / «раза» к числу: 1 раз, 3 раза, 5 раз, 22 раза."""
    return "раза" if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14) else "раз"


class CrashToast(QFrame):
    download_requested = Signal(object)   # CrashReport
    mute_requested = Signal(str)          # процесс
    closed = Signal(object)               # сам тост

    def __init__(self, report: CrashReport, parent=None):
        super().__init__(parent)
        self.report = report
        self.reports = [report]  # с «ещё N»: скачиваем последний
        self.setObjectName("CrashToast")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedWidth(WIDTH)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 8, 10)
        row.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(icons.pixmap("bug", theme.tokens()["danger"], 22))
        row.addWidget(icon, 0, Qt.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(4)
        # «Новый краш» отдельно, имя процесса — одной строкой: раньше
        # «SFA-transparency.json» переносилось посреди имени по дефису. Не
        # влезает — «…» в середине (видно и начало, и конец), полностью — в подсказке.
        head, sep, rest = report.title.partition(": ")
        self.title = QLabel(head if sep else report.title)
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-weight: 600;")
        col.addWidget(self.title)
        self.name = QLabel()
        self.name.setToolTip(rest)
        self.name.setVisible(bool(sep))
        if sep:
            self.name.setText(QFontMetrics(self.name.font()).elidedText(rest, Qt.ElideMiddle, _TEXT_WIDTH))
        col.addWidget(self.name)
        self.subtitle = QLabel()
        self.subtitle.setTextFormat(Qt.RichText)
        self.subtitle.setWordWrap(True)   # на крупном шрифте строка может не влезть
        self.subtitle.setProperty("role", "muted")
        col.addWidget(self.subtitle)
        buttons = QBoxLayout(QBoxLayout.LeftToRight)
        buttons.setSpacing(6)
        self.download_btn = QPushButton("Скачать")
        self.download_btn.setProperty("variant", "primary")
        self.download_btn.clicked.connect(lambda: self.download_requested.emit(self.reports[-1]))
        buttons.addWidget(self.download_btn)
        # Без имени процесса: оно полностью строкой выше, а в кнопке длинное
        # имя приходилось обрезать («…от com.apple.We…» — выглядит сломанным).
        self.mute_btn = QPushButton("Больше не показывать")
        self.mute_btn.setProperty("variant", "ghost")
        self.mute_btn.setToolTip(f"Больше не уведомлять о крашах {report.process}. Вернуть — в Настройках.")
        self.mute_btn.clicked.connect(lambda: self.mute_requested.emit(report.process))
        buttons.addWidget(self.mute_btn)
        buttons.addStretch()
        col.addLayout(buttons)
        for b in (self.download_btn, self.mute_btn):
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
        row.addLayout(col, 1)
        # Меряем, когда кнопки уже в карточке и со шрифтом окна (до этого у них
        # шрифт по умолчанию). Широкий шрифт или крупный масштаб экрана — кнопка
        # не влезла бы рядом и сжалась (поймали тесты на Windows): вторая строка.
        download_w, mute_w = self._button_widths()
        if download_w + buttons.spacing() + mute_w > _TEXT_WIDTH:
            buttons.setDirection(QBoxLayout.TopToBottom)
            for b in (self.download_btn, self.mute_btn):
                buttons.setAlignment(b, Qt.AlignLeft)
            # и одна кнопка не влезает (очень широкий шрифт) — карточка шире, а не обрезанная кнопка
            self.setFixedWidth(WIDTH + max(0, max(download_w, mute_w) - _TEXT_WIDTH))

        close = QToolButton()
        close.setIcon(icons.icon("close"))
        close.setIconSize(QSize(14, 14))
        close.setFixedSize(24, 24)
        close.setFocusPolicy(Qt.NoFocus)
        close.setToolTip("Закрыть")
        close.clicked.connect(self.dismiss)
        row.addWidget(close, 0, Qt.AlignTop)

        self._first = datetime.now()
        self._update_subtitle()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(HIDE_AFTER_MS)
        self._timer.timeout.connect(self.dismiss)
        self._timer.start()
        self._shown = QElapsedTimer()
        self._shown.start()

    def _button_widths(self):
        """Нужная ширина «Скачать» и «Больше не показывать» — у второй с запасом на
        заметный вид, который она получает, когда процесс часто падает."""
        self.ensurePolished()   # шрифт и стиль окна — до замеров, иначе меряем не тем шрифтом
        widths = []
        for variant in ("ghost", ""):
            self.mute_btn.setProperty("variant", variant)
            theme.repolish(self.mute_btn)
            self.mute_btn.ensurePolished()
            widths.append(self.mute_btn.sizeHint().width())
        self.mute_btn.setProperty("variant", "ghost")
        theme.repolish(self.mute_btn)
        self.download_btn.ensurePolished()
        return self.download_btn.sizeHint().width(), max(widths)

    def _update_subtitle(self):
        extra = len(self.reports) - 1
        text = f"{self._first:%H:%M:%S}"
        if extra:
            text += f"  ·  упал ещё {extra} {_times(extra)}"
        if len(self.reports) >= FREQUENT_CRASHES:
            # часто падает — подсказать, что от него можно отписаться
            text += "<br>Часто падает — можно не показывать"
            if self.mute_btn.property("variant") != "":
                self.mute_btn.setProperty("variant", "")
                theme.repolish(self.mute_btn)
        self.subtitle.setText(text)

    def bump(self, report: CrashReport):
        """Тот же процесс упал снова — счётчик вместо нового уведомления."""
        self.reports.append(report)
        self._update_subtitle()
        self._timer.start()
        self.adjustSize()

    def enterEvent(self, event):
        # Пауза — только если на уведомление навели мышь. Появилось под
        # неподвижным курсором — не в счёт, иначе оно не исчезло бы никогда.
        if self._shown.isValid() and self._shown.elapsed() > 500:
            self._timer.stop()
        super().enterEvent(event)

    def make_sticky(self):
        """Не исчезать самой (демо в обучении)."""
        self._sticky = True
        self._timer.stop()

    def leaveEvent(self, event):
        if not getattr(self, "_sticky", False):
            self._timer.start()
        super().leaveEvent(event)

    def dismiss(self):
        self._timer.stop()
        self.hide()
        self.closed.emit(self)
        self.deleteLater()
