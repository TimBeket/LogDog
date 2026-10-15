import asyncio
from pathlib import Path
from PySide6.QtCore import Signal, QThread
from utils.logger import logger

try:
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.installation_proxy import InstallationProxyService
    HAS_PYMOBILEDEVICE3 = True
except ImportError as e:
    logger.warning("pymobiledevice3 is not installed or failed to import: %s", e)
    HAS_PYMOBILEDEVICE3 = False
    create_using_usbmux = None
    InstallationProxyService = None


class IpaInstaller(QThread):
    progress = Signal(int)
    status_message = Signal(str)
    install_completed = Signal(str)
    install_failed = Signal(str)

    def __init__(self, device_serial: str, ipa_path: str, parent=None):
        super().__init__(parent)
        self.device_serial = device_serial
        self.ipa_path = ipa_path
        self._is_running = True

    def run(self):
        if not HAS_PYMOBILEDEVICE3:
            self.install_failed.emit("pymobiledevice3 не установлен")
            return
        if not self._is_running:
            return
        asyncio.run(self._install_async())

    def _progress_handler(self, percent, *args):
        if self._is_running:
            self.progress.emit(int(percent))

    async def _install_async(self):
        try:
            self.status_message.emit("Подключение к устройству...")
            lockdown = await create_using_usbmux(self.device_serial)

            self.status_message.emit("Установка .ipa...")
            async with InstallationProxyService(lockdown) as installer:
                await installer.install_from_local(
                    self.ipa_path,
                    cmd="Install",
                    handler=self._progress_handler,
                )

            if self._is_running:
                self.install_completed.emit(
                    f"Установка завершена: {Path(self.ipa_path).name}"
                )
        except Exception as e:
            if self._is_running:
                logger.error("IPA install failed: %r", e)
                self.install_failed.emit(f"Ошибка установки: {e}")

    def stop(self):
        self._is_running = False
