"""Обучение по приложению: затемнение, «окошко» вокруг нужного элемента,
пузырь с объяснением. Листать — кнопками, ← / → или PageUp / PageDown,
выйти — Esc. «▶ Авто» — шаги идут сами и сами показывают действие
(презентация).

Затемнение — дочерний виджет окна, а не отдельное окно: на Wayland так
надёжнее (см. gui/widgets/filter_edit.py). Сквозь «окошко» (маска) можно
нажимать: на шагах «Попробуйте…» пользователь делает действие сам.
"""
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from gui import theme

_PAD = 6


@dataclass
class Step:
    title: str
    text: str
    target: Optional[Callable[[], object]] = None  # → QWidget или (QWidget, QRect внутри него); None — по центру
    enter: Optional[Callable[[], None]] = None      # подготовить экран (и в ручном режиме, и в «Авто»)
    demo: List[tuple] = field(default_factory=list)  # «Авто»: [(через сколько мс, действие), …]
    try_hint: str = ""                              # «Попробуйте: …»
    done: Optional[Callable[[], bool]] = None       # пользователь сделал — отметить шаг
    leave: Optional[Callable[[], None]] = None      # убрать за собой при уходе с шага
    also: Optional[Callable[[], list]] = None       # всплывающее рядом (список подсказок) — поверх затемнения
    reserve_below: int = 0                          # место под «окошком» для всплывающего: пузырь — ниже
    duration_ms: int = 0                            # «Авто»: сколько показывать (0 — по длине текста)


class _Overlay(QWidget):
    def __init__(self, window: QWidget):
        super().__init__(window)
        self.hole = QRect()
        self.setAttribute(Qt.WA_NoSystemBackground)
        window.installEventFilter(self)
        self.setGeometry(window.rect())

    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Resize:
            self.setGeometry(self.parentWidget().rect())
            self._update_mask()
        return False

    def set_hole(self, rect: QRect):
        self.hole = rect
        self._update_mask()
        self.update()

    def _update_mask(self):
        region = QRegion(self.rect())
        if not self.hole.isNull():
            region = region.subtracted(QRegion(self.hole.adjusted(2, 2, -2, -2)))
        self.setMask(region)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRect(QRectF(self.rect()))
        if not self.hole.isNull():
            hole = QPainterPath()
            hole.addRoundedRect(QRectF(self.hole), 8, 8)
            path = path.subtracted(hole)
        painter.fillPath(path, QColor(0, 0, 0, 150))
        if not self.hole.isNull():
            painter.setPen(QPen(QColor(theme.tokens()["accent"]), 2))
            painter.drawRoundedRect(QRectF(self.hole), 8, 8)
        painter.end()


class _Bubble(QFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("TourBubble")
        self.setFixedWidth(400)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(8)
        top = QHBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("TourTitle")
        self.title.setWordWrap(True)
        top.addWidget(self.title, 1)
        self.progress = QLabel()
        self.progress.setProperty("role", "muted")
        top.addWidget(self.progress, 0, Qt.AlignTop)
        layout.addLayout(top)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.RichText)
        layout.addWidget(self.text)
        self.hint = QLabel()
        self.hint.setObjectName("TourHint")
        self.hint.setWordWrap(True)
        self.hint.setTextFormat(Qt.RichText)
        layout.addWidget(self.hint)
        buttons = QHBoxLayout()
        self.close = QPushButton("Выйти")
        self.close.setProperty("variant", "ghost")
        buttons.addWidget(self.close)
        buttons.addStretch()
        self.auto = QPushButton("▶ Авто")
        self.auto.setToolTip("Шаги пойдут сами и покажут действия")
        buttons.addWidget(self.auto)
        self.back = QPushButton("Назад")
        buttons.addWidget(self.back)
        self.next = QPushButton("Далее")
        self.next.setProperty("variant", "primary")
        buttons.addWidget(self.next)
        layout.addLayout(buttons)
        for btn in (self.close, self.auto, self.back, self.next):
            btn.setFocusPolicy(Qt.NoFocus)  # фокус остаётся там, где пробует пользователь
            btn.setCursor(Qt.PointingHandCursor)


class Tour(QObject):
    finished = Signal()

    def __init__(self, main_window: QWidget, steps: List[Step], autoplay: bool = False):
        super().__init__(main_window)
        self.main_window = main_window
        self.steps = steps
        self.index = -1
        self.autoplay = autoplay
        self._overlay: Optional[_Overlay] = None
        self._bubble: Optional[_Bubble] = None
        self._timers: List[QTimer] = []
        self._done_timer = QTimer(self)
        self._done_timer.setInterval(200)
        self._done_timer.timeout.connect(self._check_done)
        self._follow = QTimer(self)        # окно и панели двигаются — «окошко» за ними
        self._follow.setInterval(250)
        self._follow.timeout.connect(self._place)

    # ── Управление ───────────────────────────────────────────────────────

    def start(self):
        QApplication.instance().installEventFilter(self)
        self._follow.start()
        self.go(0)

    def stop(self):
        if self.index < 0:
            return
        self._leave_step()
        self.index = -1
        self._follow.stop()
        self._done_timer.stop()
        QApplication.instance().removeEventFilter(self)
        if self._overlay:
            self._overlay.deleteLater()
            self._bubble.deleteLater()
            self._overlay = None
            self._bubble = None
        self.finished.emit()

    def go(self, index: int):
        if self.index >= 0:
            self._leave_step()
        if index >= len(self.steps):
            self.stop()
            return
        self.index = max(0, index)
        step = self.steps[self.index]
        if step.enter:
            step.enter()
        self._ensure_overlay()
        self._fill_bubble(step)
        self._place()
        self._done_timer.start()
        if self.autoplay:
            for delay, action in step.demo:
                self._later(delay, action)
            self._later(self._duration(step), lambda: self.go(self.index + 1))

    def toggle_auto(self):
        self.autoplay = not self.autoplay
        self.go(self.index)  # перезапустить шаг в новом режиме

    def _leave_step(self):
        for timer in self._timers:
            timer.stop()
        self._timers.clear()
        step = self.steps[self.index] if 0 <= self.index < len(self.steps) else None
        if step and step.leave:
            step.leave()

    def _later(self, delay_ms: int, action: Callable):
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(action)
        timer.start(delay_ms)
        self._timers.append(timer)

    @staticmethod
    def _duration(step: Step) -> int:
        if step.duration_ms:
            return step.duration_ms
        demo_end = max([d for d, _ in step.demo] or [0])
        reading = 2500 + 55 * len(step.text)  # ~ скорость спокойного чтения
        return max(reading, demo_end + 3000)

    def _check_done(self):
        step = self.steps[self.index] if 0 <= self.index < len(self.steps) else None
        if step and step.done and step.try_hint and not self.autoplay and step.done():
            self._bubble.hint.setText(f'<span style="color:{theme.tokens()["accent"]}">✓ Получилось!</span>')
            self._done_timer.stop()

    # ── Отрисовка ────────────────────────────────────────────────────────

    def _target(self):
        step = self.steps[self.index]
        if step.target is None:
            return None, QRect()
        target = step.target()
        if isinstance(target, tuple):
            widget, rect = target
        else:
            widget, rect = target, None
        if widget is None or not widget.isVisible():
            return None, QRect()
        return widget, rect if rect is not None else widget.rect()

    def _ensure_overlay(self):
        widget, _ = self._target()
        window = widget.window() if widget is not None else self.main_window
        if self._overlay is not None and self._overlay.parentWidget() is window:
            return
        if self._overlay is not None:
            self._overlay.deleteLater()
            self._bubble.deleteLater()
        self._overlay = _Overlay(window)
        # Пузырь — отдельно от затемнения: маска («окошко») обрезала бы и его.
        self._bubble = _Bubble(window)
        self._bubble.next.clicked.connect(lambda: self.go(self.index + 1))
        self._bubble.back.clicked.connect(lambda: self.go(self.index - 1))
        self._bubble.close.clicked.connect(self.stop)
        self._bubble.auto.clicked.connect(self.toggle_auto)
        self._overlay.show()
        self._overlay.raise_()
        self._bubble.show()
        self._bubble.raise_()

    def _fill_bubble(self, step: Step):
        b = self._bubble
        b.title.setText(step.title)
        b.text.setText(step.text)
        hint = (step.try_hint and not self.autoplay  # в «Авто» действие показывает сама программа
                and f'<span style="color:{theme.tokens()["accent"]}">Попробуйте:</span> {step.try_hint}')
        b.hint.setText(hint or "")
        b.hint.setVisible(bool(hint))
        b.progress.setText(f"{self.index + 1} / {len(self.steps)}")
        b.back.setEnabled(self.index > 0)
        b.next.setText("Готово" if self.index == len(self.steps) - 1 else "Далее")
        b.auto.setText("⏸ Пауза" if self.autoplay else "▶ Авто")
        b.adjustSize()

    def _place(self):
        if self._overlay is None or self.index < 0:
            return
        widget, rect = self._target()
        overlay = self._overlay
        if widget is not None and widget.window() is not overlay.parentWidget():
            self._ensure_overlay()
            self._fill_bubble(self.steps[self.index])
            overlay = self._overlay
        overlay.raise_()
        self._bubble.raise_()
        if widget is None:
            hole = QRect()
        else:
            top_left = widget.mapTo(overlay.parentWidget(), rect.topLeft())
            hole = QRect(top_left, rect.size()).adjusted(-_PAD, -_PAD, _PAD, _PAD).intersected(
                overlay.rect().adjusted(2, 2, -2, -2))
        step = self.steps[self.index]
        for extra in (step.also() if step.also else []):
            # Всплывающее у поля (список подсказок) — просто поверх затемнения:
            # «окошко» под него не расширяем, иначе оно прыгает на каждой букве.
            if extra is not None and extra.isVisible() and extra.window() is overlay.parentWidget():
                extra.raise_()
        if hole != overlay.hole:
            overlay.set_hole(hole)
        avoid = hole.adjusted(0, 0, 0, step.reserve_below) if not hole.isNull() else hole
        self._place_bubble(avoid)

    def _place_bubble(self, hole: QRect):
        """Рядом с «окошком», не заслоняя его: ниже, выше, справа, слева; если
        места нет нигде (узкое окно) — где заслоняет меньше всего."""
        b, area = self._bubble, self._bubble.parentWidget().rect()
        b.setFixedWidth(min(400, area.width() - 24))  # окно инструментов узкое
        b.adjustSize()
        w, h = b.width(), b.height()
        gap = 14

        def clamp(p: QPoint) -> QPoint:
            return QPoint(max(12, min(p.x(), area.width() - w - 12)),
                          max(12, min(p.y(), area.height() - h - 12)))

        if hole.isNull():
            pos = QPoint((area.width() - w) // 2, (area.height() - h) // 2)
        else:
            candidates = [clamp(p) for p in (
                QPoint(hole.left(), hole.bottom() + gap),     # ниже
                QPoint(hole.left(), hole.top() - h - gap),    # выше
                QPoint(hole.right() + gap, hole.top()),       # справа
                QPoint(hole.left() - w - gap, hole.top()),    # слева
            )]

            def overlap(p: QPoint) -> int:
                r = QRect(p, b.size()).intersected(hole)
                return r.width() * r.height() if r.isValid() else 0

            pos = min(candidates, key=overlap)  # min берёт первый из равных — порядок важен
        b.move(clamp(pos))
        b.raise_()

    # ── Клавиши ──────────────────────────────────────────────────────────

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress and self.index >= 0:
            key = event.key()
            typing = isinstance(QApplication.focusWidget(), QLineEdit)
            if key == Qt.Key_Escape and not QApplication.activePopupWidget():
                self.stop()
                return True
            if key == Qt.Key_PageDown or (key == Qt.Key_Right and not typing):
                self.go(self.index + 1)
                return True
            if key == Qt.Key_PageUp or (key == Qt.Key_Left and not typing):
                self.go(self.index - 1)
                return True
        return False
