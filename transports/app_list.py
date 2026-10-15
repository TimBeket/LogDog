import asyncio

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


def _app_from_lookup(bundle_id: str, data: dict) -> dict:
    """Extract user-facing fields from a single InstallationProxy LookupResult entry."""
    inner = data.get("Application") or data
    name = inner.get("CFBundleDisplayName") or inner.get("CFBundleName") or bundle_id
    version = inner.get("CFBundleShortVersionString") or "-"
    build = inner.get("CFBundleVersion") or "-"
    return {
        "bundle_id": bundle_id,
        "name": name,
        "version": version,
        "build": build,
    }


class AppsListWorker(QThread):
    """Lists user-installed apps and their versions in a background thread."""
    apps_ready = Signal(list)
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
            async with InstallationProxyService(lockdown) as installer:
                apps = await installer.get_apps(application_type="User")
            await lockdown.close()

            items = [_app_from_lookup(bid, data) for bid, data in apps.items() if data]
            items.sort(key=lambda a: (a["name"] or "").lower())
            if self._is_running:
                self.apps_ready.emit(items)
        except Exception as e:
            logger.error("Failed to list apps: %r", e)
            if self._is_running:
                self.failed.emit(f"Ошибка получения списка приложений: {e}")

    def stop(self):
        self._is_running = False
