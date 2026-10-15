import re
import time
from queue import Queue, Empty
from typing import List, Dict
from PySide6.QtCore import QThread, Signal, Slot
from core.filter import LogFilter
from utils.logger import logger

_COALESCE_SEC = 0.05
_MAX_LINES = 5000

_DATE_PATTERN = r'^[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}'
_ALT_DATE_PATTERN = r'^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}'


def is_new_log_line(line: str) -> bool:
    """Does `line` look like the start of a new log entry (iOS syslog timestamp
    or Unity's synthetic timestamp)? Shared by LogProcessor (grouping incoming
    lines) and gui.main_window's repaint (grouping already-inserted QTextBlocks),
    so both agree on where one logical entry ends and the next begins."""
    stripped = line.strip()
    return bool(re.match(_DATE_PATTERN, stripped) or re.match(_ALT_DATE_PATTERN, stripped))


def group_lines(lines: List[str]) -> List[List[str]]:
    """Groups a flat list of raw lines into logical multi-line entries: a line
    matching is_new_log_line starts a new group, everything else joins the
    current group. Blank lines are dropped."""
    groups: List[List[str]] = []
    for line in lines:
        if not line.strip():
            continue
        if not groups or is_new_log_line(line):
            groups.append([line])
        else:
            groups[-1].append(line)
    return groups


class LogProcessor(QThread):
    """Background thread to group multi-line entries and emit to UI."""

    processed_blocks = Signal(list)

    def __init__(self, filter_obj: LogFilter, parent=None):
        super().__init__(parent)
        self._queue: Queue = Queue()
        self._filter = filter_obj
        self._is_running = True

    @Slot(list)
    def enqueue_lines(self, lines: List[str]):
        if lines:
            self._queue.put(lines)

    def _is_new_log_line(self, line: str) -> bool:
        return is_new_log_line(line)

    def _process_batch(self, lines: List[str]):
        if not lines:
            return

        groups = group_lines(lines)
        if not groups:
            return

        blocks = [self._make_block("\n".join(g)) for g in groups]
        self.processed_blocks.emit(blocks)

    def _make_block(self, raw: str) -> Dict:
        return {'raw': raw, 'props': self._filter.extract_props(raw)}

    def run(self):
        while self._is_running:
            try:
                lines = list(self._queue.get(timeout=0.1))
            except Empty:
                continue
            # Всё, что пришло за _COALESCE_SEC, — одной пачкой: окно получает
            # не больше ~20 обновлений в секунду при любом потоке логов, а
            # многострочная запись, разорванная между пачками транспорта,
            # склеивается правильно.
            deadline = time.monotonic() + _COALESCE_SEC
            while self._is_running and len(lines) < _MAX_LINES:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    lines.extend(self._queue.get(timeout=remaining))
                except Empty:
                    break
            try:
                self._process_batch(lines)
            except Exception:
                logger.exception("Processor thread error")

    def stop(self):
        self._is_running = False


class LogFileLoader(QThread):
    """Открытие сохранённого лога: разбор в фоне, выдача пачками, как от транспорта."""

    blocks_ready = Signal(list)
    finished_loading = Signal(int)  # сколько записей
    failed = Signal(str)

    _CHUNK = 2000

    def __init__(self, path: str, filter_obj: LogFilter, parent=None):
        super().__init__(parent)
        self.path = path
        self._filter = filter_obj
        self._is_running = True

    def run(self):
        try:
            with open(self.path, encoding="utf-8", errors="replace") as f:
                groups = group_lines(f.read().splitlines())
        except OSError as exc:
            self.failed.emit(f"Не удалось открыть файл: {exc}")
            return
        for i in range(0, len(groups), self._CHUNK):
            if not self._is_running:
                return
            self.blocks_ready.emit([{"raw": "\n".join(g), "props": self._filter.extract_props("\n".join(g))}
                                    for g in groups[i:i + self._CHUNK]])
        self.finished_loading.emit(len(groups))

    def stop(self):
        self._is_running = False
