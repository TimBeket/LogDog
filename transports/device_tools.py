"""Действия с iOS-устройством для окна «Инструменты» и списка приложений.

Каждое действие — короткая async-функция над lockdown-соединением;
DeviceTask выполняет её в фоновом потоке (QThread) и отдаёт результат
сигналом. Так у каждого инструмента нет своего класса-потока, а очистка —
тот же stop() → quit() → wait() → terminate(), что и везде (см. CLAUDE.md).

Отдельно — потоки, которые живут дольше одного действия: IconLoader (иконки
приложений по одной, чтобы список открывался сразу) и CrashWatcher (новые
краш-отчёты, пока устройство подключено).
"""
import asyncio
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from utils.logger import logger

try:
    from pymobiledevice3.exceptions import PyMobileDevice3Exception
    from pymobiledevice3.lockdown import create_using_usbmux
    from pymobiledevice3.services.crash_reports import CrashReportsManager
    from pymobiledevice3.services.diagnostics import DiagnosticsService
    from pymobiledevice3.services.house_arrest import HouseArrestService
    from pymobiledevice3.services.installation_proxy import InstallationProxyService
    from pymobiledevice3.services.misagent import MisagentService
    from pymobiledevice3.services.mobile_config import MobileConfigService
    from pymobiledevice3.services.springboard import SpringBoardServicesService
    HAS_PYMOBILEDEVICE3 = True
except ImportError as e:
    logger.warning("pymobiledevice3 is not installed or failed to import: %s", e)
    HAS_PYMOBILEDEVICE3 = False
    PyMobileDevice3Exception = Exception
    create_using_usbmux = None
    CrashReportsManager = DiagnosticsService = HouseArrestService = None
    InstallationProxyService = MisagentService = MobileConfigService = None
    SpringBoardServicesService = None


class AppDataUnavailable(Exception):
    """iOS не даёт доступ к папке приложения (App Store-сборка, системное)."""


# ── Одно действие в фоне ─────────────────────────────────────────────────────

class DeviceTask(QThread):
    """job(lockdown) -> результат, в фоне. done(результат) / failed(текст)."""
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, serial: str, job, error_prefix: str = "Ошибка", connect: bool = True, parent=None):
        super().__init__(parent)
        self.serial = serial
        self.job = job
        self.error_prefix = error_prefix
        # connect=False — job(serial) подключается сам (сброс сопряжения: обычное
        # подключение с автосопряжением как раз то, что может не работать)
        self.connect = connect
        self._is_running = True

    def run(self):
        if not HAS_PYMOBILEDEVICE3:
            self.failed.emit("pymobiledevice3 не установлен")
            return
        try:
            result = asyncio.run(self._run())
        except AppDataUnavailable as e:
            if self._is_running:
                self.failed.emit(str(e))
            return
        except Exception as e:
            logger.error("%s: %s", self.error_prefix, e)
            if self._is_running:
                self.failed.emit(f"{self.error_prefix}: {e}")
            return
        if self._is_running:
            self.done.emit(result)

    async def _run(self):
        if not self.connect:
            return await self.job(self.serial)
        lockdown = await create_using_usbmux(self.serial)
        try:
            return await self.job(lockdown)
        finally:
            try:
                await lockdown.close()
            except Exception:
                pass

    def stop(self):
        self._is_running = False


# ── Действия ─────────────────────────────────────────────────────────────────

async def uninstall_app(lockdown, bundle_id: str):
    async with InstallationProxyService(lockdown) as installer:
        await installer.uninstall(bundle_id)
    return bundle_id


async def reboot(lockdown):
    async with DiagnosticsService(lockdown) as diag:
        await diag.restart()


async def shutdown(lockdown):
    async with DiagnosticsService(lockdown) as diag:
        await diag.shutdown()


async def product_version(lockdown) -> str:
    return await lockdown.get_value(None, "ProductVersion") or ""


async def read_international(lockdown) -> dict:
    """Текущие язык и регион + что поддерживает устройство (для списков)."""
    intl = await lockdown.get_value(domain="com.apple.international") or {}
    return {
        "language": intl.get("Language") or await lockdown.get_language(),
        "locale": intl.get("Locale") or await lockdown.get_locale(),
        "languages": list(intl.get("SupportedLanguages") or []),
        "locales": list(intl.get("SupportedLocales") or []),
    }


async def apply_international(lockdown, language: str, locale: str):
    """Без перезагрузки: iOS часто подхватывает сама; если интерфейс не
    сменился — пользователь перезагрузит кнопкой."""
    if language:
        await lockdown.set_language(language)
    if locale:
        await lockdown.set_locale(locale)
    return language, locale


async def provisioning_profiles(lockdown) -> list:
    async with MisagentService(lockdown) as misagent:
        profiles = await misagent.copy_all()
    result = []
    for p in profiles:
        pl = p.plist
        result.append({
            "name": str(pl.get("Name") or ""),
            "team": str(pl.get("TeamName") or ""),
            "app_id": str((pl.get("Entitlements") or {}).get("application-identifier") or ""),
            "expires": pl.get("ExpirationDate"),
            "devices": len(pl.get("ProvisionedDevices") or []),
            "all_devices": bool(pl.get("ProvisionsAllDevices")),
        })
    return result


async def configuration_profiles(lockdown) -> list:
    async with MobileConfigService(lockdown) as mc:
        data = await mc.get_profile_list()
    result = []
    for ident in data.get("OrderedIdentifiers") or list((data.get("ProfileMetadata") or {}).keys()):
        meta = (data.get("ProfileMetadata") or {}).get(ident) or {}
        result.append({
            "id": ident,
            "name": str(meta.get("PayloadDisplayName") or ident),
            "organization": str(meta.get("PayloadOrganization") or ""),
            "description": str(meta.get("PayloadDescription") or ""),
        })
    return result


async def reset_pairing(serial: str, timeout: float = 120):
    """Снять сопряжение и сопрячь заново: на iPhone появится «Доверять этому
    компьютеру?». Помогает, когда устройство видно, но не подключается.
    Запускается с DeviceTask(connect=False): подключаемся сами и без
    автосопряжения. Если старое сопряжение уже не работает, снять его не
    выйдет — тогда просто сопрягаем заново."""
    try:
        old = await create_using_usbmux(serial, autopair=False)
        try:
            await old.unpair()
        finally:
            await old.close()
    except Exception as e:
        logger.info("Unpair skipped: %s", e)
    fresh = await create_using_usbmux(serial, autopair=False)
    try:
        await fresh.pair(timeout=timeout)
    finally:
        try:
            await fresh.close()
        except Exception:
            pass


# ── Данные приложения (папка контейнера) ────────────────────────────────────

# Эти папки не удаляем, только очищаем: приложение рассчитывает, что они есть.
KEEP_DIRS = {"/Documents", "/Library", "/Library/Preferences", "/Library/Caches",
             "/Library/Application Support", "/tmp"}
CLEAR_ROOTS = ("/Documents", "/Library", "/tmp")
UNITY_LOG = "/Documents/output.log"


async def open_container(lockdown, bundle_id: str):
    """iOS отдаёт папку TestFlight- и Development-сборок; App Store-приложениям —
    отказ (InstallationLookupFailed)."""
    try:
        return await HouseArrestService.create(lockdown, bundle_id, documents_only=False)
    except PyMobileDevice3Exception as e:
        raise AppDataUnavailable(
            "iOS не даёт доступ к данным этого приложения. Так бывает с приложениями из App Store "
            f"и системными; сборки из TestFlight и для разработки открываются. ({e})") from e


async def _clear_dir(afc, path: str, failed: list):
    for name in await afc.listdir(path):
        full = f"{path.rstrip('/')}/{name}"
        if full in KEEP_DIRS and await afc.isdir(full):
            await _clear_dir(afc, full, failed)
        else:
            failed.extend(await afc.rm(full, force=True))


async def clear_container(afc) -> list:
    """Удалить всё в Documents, Library и tmp (сами папки остаются).
    SystemData и служебный plist контейнера не трогаем. Возвращает пути,
    которые удалить не удалось."""
    failed: list = []
    for root in CLEAR_ROOTS:
        if await afc.exists(root):
            await _clear_dir(afc, root, failed)
    return failed


async def clear_app_data(lockdown, bundle_id: str) -> list:
    afc = await open_container(lockdown, bundle_id)
    try:
        return await clear_container(afc)
    finally:
        await afc.close()


async def pull_app_data(lockdown, bundle_id: str, dest: str) -> str:
    afc = await open_container(lockdown, bundle_id)
    target = Path(dest) / bundle_id
    try:
        target.mkdir(parents=True, exist_ok=True)
        for name in await afc.listdir("/"):
            if name.startswith(".com.apple"):
                continue
            await afc.pull(f"/{name}", str(target), ignore_errors=True, progress_bar=False)
    finally:
        await afc.close()
    return str(target)


async def pull_unity_log(lockdown, bundle_id: str, dest_file: str) -> str:
    afc = await open_container(lockdown, bundle_id)
    try:
        if not await afc.exists(UNITY_LOG):
            raise AppDataUnavailable("В папке игры нет Documents/output.log — игра не пишет лог Unity в файл.")
        Path(dest_file).write_bytes(await afc.get_file_contents(UNITY_LOG))
    finally:
        await afc.close()
    return dest_file


# ── Иконки приложений ───────────────────────────────────────────────────────

# Иконки не меняются, пока приложение установлено: повторное открытие списка
# показывает их сразу.
_icon_cache: dict = {}


class IconLoader(QThread):
    """Иконки по одной: список приложений открывается сразу, иконки
    появляются по мере загрузки. icon_ready(bundle_id, png)."""
    icon_ready = Signal(str, bytes)

    def __init__(self, serial: str, bundle_ids: list, parent=None):
        super().__init__(parent)
        self.serial = serial
        self.bundle_ids = list(bundle_ids)
        self._is_running = True

    def run(self):
        if not HAS_PYMOBILEDEVICE3:
            return
        missing = []
        for bid in self.bundle_ids:
            png = _icon_cache.get((self.serial, bid))
            if png:
                self.icon_ready.emit(bid, png)
            else:
                missing.append(bid)
        if missing:
            try:
                asyncio.run(self._load(missing))
            except Exception as e:
                logger.debug("Icon loading stopped: %s", e)

    async def _load(self, bundle_ids):
        lockdown = await create_using_usbmux(self.serial)
        try:
            async with SpringBoardServicesService(lockdown) as springboard:
                for bid in bundle_ids:
                    if not self._is_running:
                        return
                    png = await springboard.get_icon_pngdata(bid)
                    if png:
                        _icon_cache[(self.serial, bid)] = png
                        self.icon_ready.emit(bid, png)
        finally:
            await lockdown.close()

    def stop(self):
        self._is_running = False


# ── Новые краш-отчёты ───────────────────────────────────────────────────────

class CrashWatcher(QThread):
    """Пока iPhone подключён, раз в interval секунд смотрит список
    краш-отчётов (только имена в корне — это ~0,1 с) и сообщает о новых.
    Первый просмотр — «база»: то, что уже лежало на устройстве, не новое.
    new_reports(list[str]) — пути новых отчётов; решать, что показывать,
    будет окно (core.crash_alerts)."""
    new_reports = Signal(list)

    def __init__(self, serial: str, interval: float = 15.0, parent=None):
        super().__init__(parent)
        self.serial = serial
        self.interval = interval
        self._is_running = True

    def run(self):
        if not HAS_PYMOBILEDEVICE3:
            return
        known = None
        while self._is_running:
            try:
                names = asyncio.run(self._list())
                if known is None:
                    known = set(names)
                else:
                    fresh = [n for n in names if n not in known]
                    known.update(fresh)
                    if fresh and self._is_running:
                        self.new_reports.emit(fresh)
            except Exception as e:
                logger.debug("Crash watcher: %s", e)  # устройство отключили — попробуем позже
            deadline = time.monotonic() + self.interval
            while self._is_running and time.monotonic() < deadline:
                time.sleep(0.2)

    async def _list(self) -> list:
        lockdown = await create_using_usbmux(self.serial)
        try:
            return list(await CrashReportsManager(lockdown).ls("/", depth=1))
        finally:
            await lockdown.close()

    def stop(self):
        self._is_running = False
