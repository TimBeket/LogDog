"""Запуск действий с устройством (transports.device_tools.DeviceTask) из окон.

TaskRunner держит ссылки на запущенные потоки (иначе Qt удалит их на ходу),
блокирует кнопки на время действия и останавливает потоки тем же порядком
stop() → quit() → wait() → terminate(), что и везде в LogDog.
"""
from PySide6.QtWidgets import QMessageBox

from transports.device_tools import DeviceTask


class TaskRunner:
    def __init__(self, owner):
        self._owner = owner
        self._tasks = []

    def run(self, serial: str, job, on_done, on_failed=None, busy=(), error_prefix="Ошибка",
            error_title="Ошибка", connect: bool = True) -> DeviceTask:
        task = DeviceTask(serial, job, error_prefix=error_prefix, connect=connect, parent=self._owner)
        for widget in busy:
            widget.setEnabled(False)

        def finish():
            self._dispose(task)
            for widget in busy:
                try:
                    widget.setEnabled(True)
                except RuntimeError:
                    pass  # окно уже закрыли

        def done(result):
            finish()
            on_done(result)

        def failed(message):
            finish()
            if on_failed is not None:
                on_failed(message)
            else:
                QMessageBox.critical(self._owner, error_title, message)

        task.done.connect(done)
        task.failed.connect(failed)
        self._tasks.append(task)
        task.start()
        return task

    def busy(self) -> bool:
        return any(t.isRunning() for t in self._tasks)

    def _dispose(self, task):
        try:
            task.done.disconnect()
            task.failed.disconnect()
        except (RuntimeError, TypeError):
            pass
        task.stop()
        task.quit()
        task.wait(2000)
        if task.isRunning():
            task.terminate()
            task.wait()
        if task in self._tasks:
            self._tasks.remove(task)

    def stop_all(self):
        for task in list(self._tasks):
            self._dispose(task)
