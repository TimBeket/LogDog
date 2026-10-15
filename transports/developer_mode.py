import asyncio
from PySide6.QtCore import Signal, QThread
from utils.logger import logger

try:
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.amfi import AmfiService
    from pymobiledevice3.exceptions import DeviceHasPasscodeSetError
    HAS_PYMOBILEDEVICE3 = True
except ImportError as e:
    logger.warning("pymobiledevice3 is not installed or failed to import: %s", e)
    HAS_PYMOBILEDEVICE3 = False
    create_using_usbmux = None
    AmfiService = None
    DeviceHasPasscodeSetError = None


class DeveloperModeWorker(QThread):
    """Enables Developer Mode on an iOS device in a background thread."""
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, device_serial: str, parent=None):
        super().__init__(parent)
        self.device_serial = device_serial
        self._is_running = True

    def run(self):
        if not HAS_PYMOBILEDEVICE3:
            self.failed.emit("pymobiledevice3 не установлен")
            return
        if not self._is_running:
            return
        asyncio.run(self._async_run())

    async def _async_run(self):
        try:
            lockdown = await create_using_usbmux(self.device_serial)
            if await lockdown.get_developer_mode_status():
                if self._is_running:
                    self.completed.emit("Developer Mode уже включён.")
                return

            await AmfiService(lockdown).reveal_developer_mode_option_in_ui()
            await AmfiService(lockdown).enable_developer_mode()

            if self._is_running:
                self.completed.emit(
                    "Готово, Developer Mode включён.\n"
                    "Раздел «Developer» появился в Настройках устройства."
                )
        except Exception as e:
            if not self._is_running:
                return
            if DeviceHasPasscodeSetError is not None and isinstance(e, DeviceHasPasscodeSetError):
                self.failed.emit(
                    "На устройстве задан код-пароль.\n"
                    "Включение Developer Mode невозможно, пока задан код-пароль."
                )
            else:
                logger.error("Failed to enable developer mode: %r", e)
                self.failed.emit(f"Ошибка включения Developer Mode: {e}")

    def stop(self):
        self._is_running = False