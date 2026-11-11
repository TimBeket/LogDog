"""Долгая работа в окне — по шагам между событиями, чтобы окно не зависало.

Работа — генератор: каждый `yield` — место, где можно отдать управление.
Шаг длится не дольше STEP_SEC (но хотя бы один `next`), потом окно
обрабатывает события (ввод, перерисовку, новые логи) и работа продолжается.
Так на слабом компьютере перестроение 50 тыс. строк не подвешивает окно на
полторы секунды, а новая команда (следующая буква фильтра) просто отменяет
недоделанную работу. Без потоков: QTextDocument и виджеты можно трогать только
из главного потока.
"""
import time
from typing import Callable, Generator, Optional

from PySide6.QtCore import QObject, QTimer

STEP_SEC = 0.025


class SteppedJob(QObject):
    def __init__(self, parent=None, on_done: Optional[Callable[[], None]] = None,
                 on_step: Optional[Callable[[], None]] = None):
        super().__init__(parent)
        self.step_sec = STEP_SEC
        self._job: Optional[Generator] = None
        self._on_done = on_done
        self._on_step = on_step
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self.step)

    @property
    def running(self) -> bool:
        return self._job is not None

    def start(self, job: Generator):
        """Отменить прежнюю работу и начать новую; первый шаг — сразу:
        небольшая работа так и закончится, не дожидаясь событий."""
        self.cancel()
        self._job = job
        self.step()

    def step(self):
        job = self._job
        if job is None:
            return
        deadline = time.perf_counter() + self.step_sec
        try:
            next(job)   # хотя бы шаг — даже если время уже вышло
            while time.perf_counter() < deadline:
                next(job)
        except StopIteration:
            self._job = None
            if self._on_done:
                self._on_done()
            return
        if self._on_step:
            self._on_step()
        self._timer.start()

    def finish(self):
        """Доделать сразу (нужен готовый результат)."""
        job, self._job = self._job, None
        self._timer.stop()
        if job is not None:
            for _ in job:
                pass
            if self._on_done:
                self._on_done()

    def cancel(self):
        self._timer.stop()
        job, self._job = self._job, None
        if job is not None:
            job.close()
