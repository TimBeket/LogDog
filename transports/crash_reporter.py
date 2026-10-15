import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Signal, QThread

from utils.logger import logger

try:
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.crash_reports import CrashReportsManager
    HAS_PYMOBILEDEVICE3 = True
except ImportError as e:
    logger.warning("pymobiledevice3 is not installed or failed to import: %s", e)
    HAS_PYMOBILEDEVICE3 = False
    create_using_usbmux = None
    CrashReportsManager = None


MAX_LISTED_CRASHES = 500


@dataclass
class CrashReportItem:
    """Metadata about a single crash report stored on an iOS device."""
    path: str
    name: str = ""
    timestamp: str = ""
    bug_type: str = ""
    incident_id: str = ""
    size: int = 0


def _device_time_to_str(ts) -> str:
    try:
        if hasattr(ts, "strftime"):
            return ts.strftime("%Y-%m-%d %H:%M:%S")
        from datetime import timezone
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass
    return ""


def write_readable_log(raw_ips_text: str, item: CrashReportItem) -> str:
    """Build a human-readable text representation of a crash report.

    :param raw_ips_text: the raw content of the pulled .ips file
    :param item: metadata about the report (name, incident, timestamp, ...)
    :return: formatted text suitable to be saved as a .log file
    """
    lines = []
    lines.append("=" * 60)
    lines.append("              iOS Crash Report (LogDog)")
    lines.append("=" * 60)
    if item.name:
        lines.append(f"Application:     {item.name}")
    if item.incident_id:
        lines.append(f"Incident ID:     {item.incident_id}")
    if item.bug_type:
        lines.append(f"Bug type:        {item.bug_type}")
    if item.timestamp:
        lines.append(f"Timestamp:       {item.timestamp}")
    if item.path:
        lines.append(f"Source:          {Path(item.path).name}")
    lines.append("-" * 60)

    body = raw_ips_text
    try:
        data = json.loads(raw_ips_text)
        body = json.dumps(data, indent=2, ensure_ascii=False)
    except (ValueError, TypeError):
        pass

    lines.append(body)
    lines.append("=" * 60)
    return "\n".join(lines)


class CrashListWorker(QThread):
    """Lists crash reports available on an iOS device in a background thread."""
    listing_ready = Signal(list)
    listing_failed = Signal(str)

    def __init__(self, device_serial: str, parent=None):
        super().__init__(parent)
        self.device_serial = device_serial
        self._is_running = True

    def run(self):
        if not HAS_PYMOBILEDEVICE3:
            self.listing_failed.emit("pymobiledevice3 не установлен")
            return
        if not self._is_running:
            return
        asyncio.run(self._list_async())

    async def _list_async(self):
        try:
            lockdown = await create_using_usbmux(self.device_serial)
            manager = CrashReportsManager(lockdown)
            items: list[CrashReportItem] = []

            entries = await manager.ls("/", depth=-1)
            files = []
            for entry in entries:
                if not self._is_running:
                    return
                try:
                    info = await manager.afc.stat(entry)
                    if info and info.get("st_ifmt") == "S_IFREG":
                        files.append((info.get("st_mtime"), entry, int(info.get("st_size", 0))))
                except Exception:
                    pass

            files.sort(key=lambda t: (t[0] is None, t[0] if t[0] is not None else 0), reverse=True)
            files = files[:MAX_LISTED_CRASHES]

            for _, path, size in files:
                if not self._is_running:
                    return
                item = CrashReportItem(path=path, size=size)
                try:
                    report = await manager.parse(path)
                    item.name = report.name or ""
                    item.timestamp = _device_time_to_str(report.timestamp)
                    item.bug_type = report.bug_type_str or ""
                    item.incident_id = str(report.incident_id) if report.incident_id else ""
                except Exception as e:
                    logger.debug("Could not parse crash report %s: %s", path, e)
                items.append(item)

            if self._is_running:
                self.listing_ready.emit(items)
        except Exception as e:
            if self._is_running:
                logger.error("Failed to list crash reports: %r", e)
                self.listing_failed.emit(f"Ошибка получения краш-отчётов: {e}")

    def stop(self):
        self._is_running = False


class CrashPuller(QThread):
    """Downloads selected crash reports (.ips) from an iOS device and writes .log duplicates."""
    pulled = Signal(str)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, device_serial: str, items: list, out_dir: str, parent=None):
        super().__init__(parent)
        self.device_serial = device_serial
        self.items = items
        self.out_dir = out_dir
        self._is_running = True

    def run(self):
        if not HAS_PYMOBILEDEVICE3:
            self.failed.emit("pymobiledevice3 не установлен")
            return
        if not self._is_running or not self.items:
            return
        asyncio.run(self._pull_async())

    async def _pull_async(self):
        try:
            lockdown = await create_using_usbmux(self.device_serial)
            manager = CrashReportsManager(lockdown)
            out_dir = Path(self.out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)

            saved = 0
            for item in self.items:
                if not self._is_running:
                    return
                name = Path(item.path).name
                dest = out_dir / name
                await manager.pull(str(out_dir), entry=item.path, erase=False, progress_bar=False)

                if dest.exists():
                    raw = dest.read_text(encoding="utf-8", errors="replace")
                    readable = write_readable_log(raw, item)
                    dest.with_suffix(".log").write_text(readable, encoding="utf-8")
                    saved += 1
                    self.pulled.emit(str(dest))
                else:
                    logger.warning("Crash report was not saved: %s", item.path)

            if self._is_running:
                msg = f"Сохранено краш-отчётов: {saved}"
                if saved < len(self.items):
                    msg += f" из {len(self.items)} (остальные не удалось скачать)"
                self.done.emit(f"{msg}\nПапка: {out_dir}")
        except Exception as e:
            if self._is_running:
                logger.error("Failed to pull crash reports: %r", e)
                self.failed.emit(f"Ошибка выгрузки краш-отчётов: {e}")

    def stop(self):
        self._is_running = False