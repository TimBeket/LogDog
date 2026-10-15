"""Уведомления о новых краш-отчётах, пока подключён iPhone.

CrashAlerts держит фоновый CrashWatcher (transports.device_tools), решает,
что показывать (core.crash_alerts.AlertPolicy: заглушённые процессы, повторы
одного процесса — счётчиком), и показывает не больше MAX_TOASTS карточек в
правом верхнем углу окна. Главное окно только вызывает start(serial) / stop().
"""
from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QFileDialog

from core.crash_alerts import AlertPolicy, CrashReport, describe
from core.settings import settings
from gui.widgets.crash_toast import CrashToast
from transports import device_tools
from transports.crash_reporter import CrashPuller, CrashReportItem
from utils.logger import logger

MAX_TOASTS = 3
_MARGIN = 12


class CrashAlerts(QObject):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.serial = ""
        self.watcher = None
        self.policy = AlertPolicy(lambda proc: proc in settings.muted_crash_processes())
        self.toasts: list = []
        self._pullers: list = []
        window.installEventFilter(self)

    # ── Жизненный цикл ───────────────────────────────────────────────────

    def start(self, serial: str):
        if serial == self.serial and self.watcher is not None:
            return
        self.stop()
        if not serial or not settings.crash_alerts_enabled() or not device_tools.HAS_PYMOBILEDEVICE3:
            return
        self.serial = serial
        self.watcher = device_tools.CrashWatcher(serial, parent=self)
        self.watcher.new_reports.connect(self.on_new_paths)
        self.watcher.start()

    def stop(self):
        if self.watcher is not None:
            try:
                self.watcher.new_reports.disconnect()
            except (RuntimeError, TypeError):
                pass
            self.watcher.stop()
            self.watcher.quit()
            self.watcher.wait(2000)
            if self.watcher.isRunning():
                self.watcher.terminate()
                self.watcher.wait()
            self.watcher = None
        self.serial = ""

    def shutdown(self):
        self.stop()
        for puller in list(self._pullers):
            puller.stop()
            puller.quit()
            puller.wait(2000)
            if puller.isRunning():
                puller.terminate()
                puller.wait()
        self._pullers.clear()

    # ── Новые отчёты ─────────────────────────────────────────────────────

    def on_new_paths(self, paths: list):
        for path in paths:
            report = describe(path)
            if report is not None:
                self.on_report(report)

    def on_report(self, report: CrashReport):
        if self.policy.decide(report) == "ignore":
            return
        existing = next((t for t in self.toasts if t.report.process == report.process and t.isVisible()), None)
        if existing is not None:
            existing.bump(report)  # карточка ещё на экране — счётчик, а не гора карточек
            self._layout()
            return
        self.show_toast(report)

    def show_toast(self, report: CrashReport, sticky: bool = False) -> CrashToast:
        """Показать карточку без проверки на повторы. sticky — не прятать
        саму (демо в обучении)."""
        toast = CrashToast(report, self.window)
        if sticky:
            toast.make_sticky()
        toast.download_requested.connect(self._download)
        toast.mute_requested.connect(self._mute)
        toast.closed.connect(self._on_closed)
        self.toasts.append(toast)
        while len(self.toasts) > MAX_TOASTS:
            self.toasts[0].dismiss()
        toast.show()
        toast.raise_()
        self._layout()
        return toast

    def _on_closed(self, toast):
        if toast in self.toasts:
            self.toasts.remove(toast)
        self._layout()

    def _layout(self):
        """Стопкой в правом верхнем углу, под шапкой окна."""
        top = _MARGIN + 56  # ниже панели с фильтром
        for toast in reversed(self.toasts):
            toast.adjustSize()
            toast.move(self.window.width() - toast.width() - _MARGIN, top)
            toast.raise_()
            top += toast.height() + 8

    def eventFilter(self, obj, event):
        if obj is self.window and event.type() == QEvent.Resize and self.toasts:
            self._layout()
        return False

    # ── Кнопки уведомления ───────────────────────────────────────────────

    def _mute(self, process: str):
        settings.mute_crash_process(process)
        for toast in [t for t in self.toasts if t.report.process == process]:
            toast.dismiss()
        self._status(f"Уведомления о крашах {process} отключены — вернуть можно в Настройках")

    def _download(self, report: CrashReport):
        folder = QFileDialog.getExistingDirectory(self.window, "Куда сохранить краш-отчёт",
                                                  settings.last_save_dir())
        if not folder or not self.serial:
            return
        settings.set_last_save_dir(folder)
        item = CrashReportItem(path=report.path, name=report.process)
        puller = CrashPuller(self.serial, [item], folder, parent=self)
        puller.done.connect(lambda msg, p=puller: self._pulled(p, msg))
        puller.failed.connect(lambda msg, p=puller: self._pulled(p, msg))
        self._pullers.append(puller)
        puller.start()
        self._status("Скачиваю краш-отчёт…")

    def _pulled(self, puller, message: str):
        logger.info("Crash pull: %s", message)
        self._status(message.replace("\n", " · "), 10000)
        puller.quit()
        puller.wait(2000)
        if puller in self._pullers:
            self._pullers.remove(puller)

    def _status(self, text: str, timeout: int = 8000):
        bar = getattr(self.window, "status_bar", None)
        if bar is not None:
            bar.showMessage(text, timeout)
