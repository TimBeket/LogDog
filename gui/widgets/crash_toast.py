"""Уведомление о новом краше — маленькая карточка в правом верхнем углу окна.

Дочерний виджет главного окна, а не отдельное окно: не забирает фокус и не
всплывает поверх других программ (на Wayland отдельные всплывающие окна ещё и
ставятся куда попало). Сама исчезает через HIDE_AFTER_MS; пока над ней мышь —
не исчезает.
"""
from datetime import datetime

from PySide6.QtCore import QElapsedTimer, QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout

from core.crash_alerts import FREQUENT_CRASHES, CrashReport
from gui import icons, theme

HIDE_AFTER_MS = 8000


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
        self.setFixedWidth(360)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 8, 10)
        row.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(icons.pixmap("bug", theme.tokens()["danger"], 22))
        row.addWidget(icon, 0, Qt.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(4)
        self.title = QLabel(report.title)
        self.title.setWordWrap(True)
        self.title.setStyleSheet("font-weight: 600;")
        col.addWidget(self.title)
        self.subtitle = QLabel()
        self.subtitle.setTextFormat(Qt.RichText)
        self.subtitle.setProperty("role", "muted")
        col.addWidget(self.subtitle)
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.download_btn = QPushButton("Скачать")
        self.download_btn.setProperty("variant", "primary")
        self.download_btn.clicked.connect(lambda: self.download_requested.emit(self.reports[-1]))
        buttons.addWidget(self.download_btn)
        name = report.process if len(report.process) <= 18 else report.process[:17] + "…"
        self.mute_btn = QPushButton(f"Не показывать от {name}")
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

    def _update_subtitle(self):
        extra = len(self.reports) - 1
        text = f"{self._first:%H:%M:%S}"
        if extra:
            text += f"  ·  и ещё {extra} — процесс падает снова"
        if len(self.reports) >= FREQUENT_CRASHES:
            # часто падает — подсказать, что от него можно отписаться
            text += "<br>Часто падает — можно не показывать ↓"
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
