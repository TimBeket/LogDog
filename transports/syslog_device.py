import time
import asyncio
from PySide6.QtCore import Signal, QThread
from transports.base import BaseReader
from utils.logger import logger

try:
    from pymobiledevice3.usbmux import list_devices
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.irecv_devices import IRECV_DEVICES
    from pymobiledevice3.services.syslog import SyslogService
    HAS_PYMOBILEDEVICE3 = True
except ImportError as e:
    logger.warning("pymobiledevice3 is not installed or failed to import: %s", e)
    HAS_PYMOBILEDEVICE3 = False
    list_devices = None
    create_using_usbmux = None
    IRECV_DEVICES = []
    SyslogService = None

# Строки syslog — пачками: iPhone шлёт их сотнями и тысячами в секунду, а
# сигнал на каждую строку (и перерисовка окна на каждую) медленный компьютер
# не успевал обработать — очередь росла, и окно со временем «зависало».
_FLUSH_INTERVAL_SEC = 0.05
_FLUSH_MAX_LINES = 500


class IosDevicePoller(QThread):
    """Polls for connected iOS devices efficiently and emits signals to update GUI."""
    devices_updated = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_running = True
        # имя и модель по серийному номеру: не меняются, пока устройство
        # подключено, — не спрашиваем их заново каждые 2 секунды
        self._info: dict = {}

    async def _device_info(self, serial: str, native_map: dict) -> dict:
        if serial not in self._info:
            try:
                lock = await create_using_usbmux(serial)
                try:
                    name = await lock.get_value(None, "DeviceName") or "Unknown iOS Device"
                    ptype = await lock.get_value(None, "ProductType")
                finally:
                    await lock.close()
                self._info[serial] = {"serial": serial, "name": name, "model": native_map.get(ptype, ptype)}
            except Exception as e:
                # не кэшируем: устройство могло быть ещё не «доверено» — спросим в следующий раз
                logger.debug("Device info for %s failed: %s", serial, e)
                return {"serial": serial, "name": "Unknown Device", "model": "iOS"}
        return self._info[serial]

    async def _poll(self, native_map: dict) -> list:
        devices = await list_devices()
        serials = [d.serial for d in devices]
        for serial in list(self._info):
            if serial not in serials:
                del self._info[serial]
        return [await self._device_info(s, native_map) for s in serials]

    def run(self):
        if not HAS_PYMOBILEDEVICE3:
            self.devices_updated.emit(["pymobiledevice3 не установлен"])
            return

        native_map = {d.product_type: d.display_name for d in IRECV_DEVICES}
        last = None
        while self._is_running:
            try:
                result = asyncio.run(self._poll(native_map)) or ["Нет подключенных устройств"]
            except Exception as e:
                logger.warning("Failed to list ios devices: %s: %s", type(e).__name__, e)
                result = ["Нет подключенных устройств"]
            # Окну — только изменения: перестройка списка каждые 2 секунды
            # закрывала открытый выпадающий список устройств.
            if result != last:
                last = result
                self.devices_updated.emit(result)

            for _ in range(20):
                if not self._is_running:
                    return
                time.sleep(0.1)

    def stop(self):
        self._is_running = False


class IosSyslogReader(BaseReader):
    """Reads syslog from an iOS device with auto-reconnect on disconnect."""

    def __init__(self, device_serial: str, display_name: str, parent=None):
        super().__init__(parent)
        self.device_serial = device_serial
        self.display_name = display_name

    def run(self):
        if not HAS_PYMOBILEDEVICE3:
            self.status_changed.emit("Ошибка: pymobiledevice3 не установлен")
            return

        while self._is_running:
            asyncio.run(self._async_run())
            if not self._is_running:
                break
            # Reconnect: wait before retrying
            for _ in range(30):
                if not self._is_running:
                    return
                time.sleep(0.1)
            self.status_changed.emit(f"Нет связи с {self.display_name} — переподключаюсь…")

    async def _async_run(self):
        try:
            self.state_changed.emit("connecting")
            self.status_changed.emit(f"Подключение к {self.display_name}…")
            lockdown = await create_using_usbmux(self.device_serial)

            async with SyslogService(lockdown) as syslog:
                self.state_changed.emit("streaming")
                self.status_changed.emit(f"Сбор логов iOS ({self.display_name})")
                await self._pump(syslog)
        except Exception as e:
            if self._is_running:
                logger.warning("Syslog connection lost: %s: %s", type(e).__name__, e)
                self.state_changed.emit("waiting")
                self.emit_system_message("Соединение с iOS потеряно. Переподключение...")

    async def _pump(self, syslog):
        """Чтение — отдельной задачей в очередь, а здесь — выдача пачками.
        Ожидание очереди с таймаутом: так и хвост пачки уходит, когда строк
        нет, и stop() срабатывает за 0,1 с, а не с приходом следующей строки
        (раньше «Отключиться» ждало 2 с и обрывало поток принудительно)."""
        queue: asyncio.Queue = asyncio.Queue()

        async def read():
            async for line in syslog.watch():
                queue.put_nowait(line)

        reader = asyncio.create_task(read())
        batch, last_flush = [], time.monotonic()
        try:
            while self._is_running:
                try:
                    line = await asyncio.wait_for(queue.get(), timeout=0.1)
                    line = line.strip()
                    if line:
                        batch.append(line)
                except asyncio.TimeoutError:
                    if reader.done():
                        reader.result()  # пробросит ошибку чтения (устройство отключили)
                        return
                    quiet = True  # строк нет — отдать, что накопилось
                else:
                    quiet = False
                if batch and (quiet or len(batch) >= _FLUSH_MAX_LINES
                              or time.monotonic() - last_flush >= _FLUSH_INTERVAL_SEC):
                    self.lines_ready.emit(batch)
                    batch, last_flush = [], time.monotonic()
        finally:
            if batch and self._is_running:
                self.lines_ready.emit(batch)
            reader.cancel()

    def stop(self):
        super().stop()
