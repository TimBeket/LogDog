"""Лог диагностики самого LogDog (logdog_diagnostic.log), не логи устройства.

Его присылают, когда что-то не так, поэтому в нём то, что помогает понять,
что было: версии и система при запуске, подключения, необработанные ошибки
со стеком, зависания окна (gui/main_window.py, сторож). А повторяющийся шум
схлопывается: без iPhone или со службой Apple, которая не отвечает, одно и то
же предупреждение шло каждые 3–4 секунды часами и вытесняло из 8 МБ лога
всё полезное.
"""
import atexit
import logging
import platform
import sys
import threading
import time
from logging.handlers import RotatingFileHandler

from utils.helpers import get_app_data_dir

# Internal logger for the LogDog Application itself, not the parsed logs.
logger = logging.getLogger("LogDog")
logger.setLevel(logging.DEBUG)

# Max 2 MB per file, keep 3 backup files = ~8 MB total max
LOG_MAX_BYTES = 2 * 1024 * 1024
LOG_BACKUP_COUNT = 3

REPEAT_WINDOW_SEC = 600   # одно и то же сообщение — не чаще раза в 10 минут
_MAX_TRACKED = 500


class RepeatFilter(logging.Filter):
    """Одинаковые сообщения (тот же уровень и текст) — первое пишется, следующие
    в течение REPEAT_WINDOW_SEC только считаются. Следующее после окна — с
    припиской «повторилось ещё N раз»; flush() — итог по тем, что ещё копятся
    (при выходе из программы). Чередование разных сообщений не мешает."""

    def __init__(self, window_sec: float = REPEAT_WINDOW_SEC, clock=time.monotonic):
        super().__init__()
        self.window = window_sec
        self.clock = clock
        self._seen = {}   # (уровень, текст, ошибка) -> [когда записали, сколько пропущено]
        self._lock = threading.Lock()

    def filter(self, record: logging.LogRecord) -> bool:
        # ошибка со стеком: первая — целиком, повторы той же ошибки — счётом
        # (падение на каждой пачке логов иначе писало бы стек 20 раз в секунду)
        exc = repr(record.exc_info[1]) if record.exc_info else ""
        key = (record.levelno, record.getMessage(), exc)
        now = self.clock()
        with self._lock:
            state = self._seen.get(key)
            if state is not None and now - state[0] < self.window:
                state[1] += 1
                return False
            skipped = state[1] if state else 0
            self._seen[key] = [now, 0]
            if len(self._seen) > _MAX_TRACKED:
                self._forget_old(now)
        if skipped:
            record.msg = f"{record.getMessage()} [повторилось ещё {skipped} раз за {self.window // 60:.0f} мин]"
            record.args = ()
            record.exc_info = record.exc_text = None   # стек уже был в первом
        return True

    def _forget_old(self, now: float):
        for key in [k for k, (t, n) in self._seen.items() if now - t >= self.window and not n]:
            del self._seen[key]

    def flush(self, target: logging.Logger):
        """Записать, сколько раз повторились сообщения, которые сейчас пропускаются."""
        with self._lock:
            pending = [(key, n) for key, (_, n) in self._seen.items() if n]
            for key, _ in pending:
                self._seen[key][1] = 0
        for (level, text, _exc), n in pending:
            target.log(level, "%s [повторилось ещё %d раз до выхода]", text, n)


repeat_filter = RepeatFilter()


def _log_uncaught(exc_type, exc, tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc, tb)
        return
    logger.critical("Unhandled exception", exc_info=(exc_type, exc, tb))
    sys.__excepthook__(exc_type, exc, tb)


def _log_uncaught_thread(args):
    if args.exc_type is SystemExit:
        return
    logger.critical("Unhandled exception in thread %s", getattr(args.thread, "name", "?"),
                    exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


def describe_environment() -> str:
    """Одной строкой: система, Python, Qt — для разбора присланного лога."""
    try:
        from PySide6 import __version__ as pyside_version
        from PySide6.QtCore import qVersion
        qt = f"Qt {qVersion()}, PySide6 {pyside_version}"
    except Exception:
        qt = "Qt ?"
    build = "frozen" if getattr(sys, "frozen", False) else "from sources"
    return f"{platform.platform()}, Python {platform.python_version()}, {qt}, {build}"


def setup_logger(debug_mode: bool = False):
    """Initializes the backend logger specifically for LogDog diagnostics."""
    if logger.handlers:
        for h in logger.handlers[:]:
            logger.removeHandler(h)

    log_file = get_app_data_dir() / "logdog_diagnostic.log"
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    try:
        fh = RotatingFileHandler(
            log_file, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
        )
        fh.setLevel(logging.DEBUG if debug_mode else logging.INFO)
        fh.setFormatter(formatter)
        logger.addHandler(fh)

        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG if debug_mode else logging.INFO)
        ch.setFormatter(formatter)
        logger.addHandler(ch)

        logger.info("LogDog logger initialized -> %s (rotation: %d MB, %d backups)",
                     log_file, LOG_MAX_BYTES // (1024 * 1024), LOG_BACKUP_COUNT)
    except Exception as e:
        logging.basicConfig(level=logging.DEBUG if debug_mode else logging.INFO)
        logger.error("Failed to open diagnostic log file %s: %s", log_file, e)

    # Фильтр на логгере, а не на обработчиках: файл и консоль видят одно и то же.
    if repeat_filter not in logger.filters:
        logger.addFilter(repeat_filter)
        atexit.register(repeat_filter.flush, logger)   # раньше logging.shutdown: atexit — с конца
    # Необработанные ошибки — в лог со стеком (у собранной программы на Windows
    # консоли нет, и раньше они пропадали бесследно).
    sys.excepthook = _log_uncaught
    threading.excepthook = _log_uncaught_thread
