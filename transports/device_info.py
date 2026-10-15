import asyncio

from PySide6.QtCore import Signal, QThread
from utils.logger import logger

try:
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.diagnostics import DiagnosticsService
    from pymobiledevice3.irecv_devices import IRECV_DEVICES
    HAS_PYMOBILEDEVICE3 = True
except ImportError as e:
    logger.warning("pymobiledevice3 is not installed or failed to import: %s", e)
    HAS_PYMOBILEDEVICE3 = False
    create_using_usbmux = None
    DiagnosticsService = None
    IRECV_DEVICES = []


def _model_name(product_type: str) -> str:
    for dev in IRECV_DEVICES:
        if dev.product_type == product_type:
            return dev.display_name
    return product_type or ""


class DeviceInfoWorker(QThread):
    """Gathers general device info (model, iOS version, battery, ...) over usbmux."""
    result_ready = Signal(dict)
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

            info: dict = {}
            info["name"] = await lockdown.get_value(None, "DeviceName") or "-"
            pt = await lockdown.get_value(None, "ProductType") or ""
            info["product_type"] = pt
            info["model"] = _model_name(pt)
            info["ios"] = await lockdown.get_value(None, "ProductVersion") or "-"
            info["build"] = await lockdown.get_value(None, "BuildVersion") or "-"
            info["hardware"] = await lockdown.get_value(None, "HardwareModel") or "-"
            info["udid"] = await lockdown.get_value(None, "UniqueDeviceID") or "-"
            info["wifi_mac"] = await lockdown.get_value(None, "WiFiAddress") or "-"

            # Батарея и накопитель — из разделов lockdown: работают без
            # отладочного образа (MobileGestalt через диагностику на iOS 17.4+
            # больше не отдаёт память — было «Нет данных»). Проверено на iOS 27.
            info["battery_level"] = info["charging"] = None
            try:
                battery = await lockdown.get_value(domain="com.apple.mobile.battery") or {}
                if "BatteryCurrentCapacity" in battery:
                    info["battery_level"] = int(battery["BatteryCurrentCapacity"])
                    info["charging"] = bool(battery.get("BatteryIsCharging"))
            except Exception:
                pass
            if info["battery_level"] is None:
                try:
                    async with DiagnosticsService(lockdown) as diag:
                        batt = await diag.get_battery() or {}
                    max_cap = int(batt.get("MaxCapacity", 0)) or 1
                    info["battery_level"] = round(int(batt.get("CurrentCapacity", 0)) / max_cap * 100)
                    info["charging"] = bool(batt.get("IsCharging"))
                except Exception:
                    pass

            info["storage_total"] = info["storage_free"] = None
            try:
                disk = await lockdown.get_value(domain="com.apple.disk_usage") or {}
                total = disk.get("TotalDiskCapacity") or disk.get("TotalDataCapacity")
                free = disk.get("AmountDataAvailable") or disk.get("TotalDataAvailable")
                if total:
                    info["storage_total"], info["storage_free"] = int(total), int(free or 0)
            except Exception:
                pass

            # Закрываем только здесь: DiagnosticsService запускается через это
            # же lockdown-соединение, после close() он молча не стартует.
            await lockdown.close()

            if self._is_running:
                self.result_ready.emit(info)
        except Exception as e:
            logger.error("Failed to fetch device info: %r", e)
            if self._is_running:
                self.failed.emit(f"Ошибка получения информации об устройстве: {e}")

    def stop(self):
        self._is_running = False
