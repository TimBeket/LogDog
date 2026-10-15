"""Что внутри .ipa и встанет ли она на этот iPhone — до установки.

Без Qt и без устройства: Info.plist приложения и embedded.mobileprovision
(профиль подготовки) читаются прямо из zip. Профиль — это plist, завёрнутый
в подпись CMS; сам plist лежит внутри открытым текстом между `<?xml` и
`</plist>`, так что криптография для чтения не нужна.

Проверка (check) возвращает понятные предупреждения вместо невнятной ошибки
установки: UDID нет в профиле, профиль истёк, нужна более новая iOS, сборка
для App Store/TestFlight.
"""
from __future__ import annotations

import plistlib
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional


class IpaError(Exception):
    """Файл — не .ipa или повреждён."""


@dataclass
class IpaInfo:
    path: Path
    name: str = ""
    bundle_id: str = ""
    version: str = ""
    build: str = ""
    min_ios: str = ""
    # профиль подготовки (None — профиля в сборке нет)
    has_profile: bool = False
    profile_name: str = ""
    team: str = ""
    expires: Optional[datetime] = None
    devices: List[str] = field(default_factory=list)
    all_devices: bool = False   # корпоративный (Enterprise) профиль — для любого устройства
    debuggable: bool = False    # get-task-allow: сборка для разработки

    @property
    def kind(self) -> str:
        if not self.has_profile:
            return "без профиля"
        if self.all_devices:
            return "Enterprise (для любых устройств)"
        if not self.devices:
            return "App Store / TestFlight"
        return "Development" if self.debuggable else "Ad Hoc"


@dataclass
class Warning_:
    text: str
    blocking: bool = True  # установка почти наверняка не пройдёт


def _profile_plist(data: bytes) -> dict:
    start = data.find(b"<?xml")
    end = data.find(b"</plist>")
    if start == -1 or end == -1:
        raise IpaError("Не удалось прочитать профиль подготовки (embedded.mobileprovision)")
    return plistlib.loads(data[start:end + len(b"</plist>")])


def read_ipa(path) -> IpaInfo:
    path = Path(path)
    try:
        zf = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise IpaError(f"Это не .ipa (не zip-архив): {exc}") from exc
    with zf:
        names = zf.namelist()
        # Payload/<Имя>.app/Info.plist — ровно на этом уровне (не плагины внутри .app)
        info_name = next((n for n in names if n.startswith("Payload/") and n.count("/") == 2
                          and n.split("/")[1].endswith(".app") and n.endswith("/Info.plist")), None)
        if info_name is None:
            raise IpaError("В архиве нет Payload/*.app/Info.plist — это не .ipa")
        try:
            plist = plistlib.loads(zf.read(info_name))
        except Exception as exc:
            raise IpaError(f"Info.plist не читается: {exc}") from exc
        app_dir = info_name[: -len("Info.plist")]
        info = IpaInfo(
            path=path,
            name=str(plist.get("CFBundleDisplayName") or plist.get("CFBundleName") or ""),
            bundle_id=str(plist.get("CFBundleIdentifier") or ""),
            version=str(plist.get("CFBundleShortVersionString") or ""),
            build=str(plist.get("CFBundleVersion") or ""),
            min_ios=str(plist.get("MinimumOSVersion") or ""),
        )
        prov_name = app_dir + "embedded.mobileprovision"
        if prov_name in names:
            prov = _profile_plist(zf.read(prov_name))
            info.has_profile = True
            info.profile_name = str(prov.get("Name") or "")
            info.team = str(prov.get("TeamName") or "")
            expires = prov.get("ExpirationDate")
            if isinstance(expires, datetime):
                info.expires = expires if expires.tzinfo else expires.replace(tzinfo=timezone.utc)
            info.devices = [str(d) for d in prov.get("ProvisionedDevices") or []]
            info.all_devices = bool(prov.get("ProvisionsAllDevices"))
            info.debuggable = bool((prov.get("Entitlements") or {}).get("get-task-allow"))
    return info


def _version_tuple(version: str):
    parts = []
    for part in version.split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def check(info: IpaInfo, udid: str = "", ios_version: str = "",
          now: Optional[datetime] = None) -> List[Warning_]:
    """Почему сборка может не встать на это устройство."""
    now = now or datetime.now(timezone.utc)
    warnings: List[Warning_] = []
    if not info.has_profile:
        warnings.append(Warning_("В сборке нет профиля подготовки — iOS её не установит, "
                                 "если это не сборка из Xcode для симулятора."))
    else:
        if info.expires and info.expires < now:
            warnings.append(Warning_(f"Профиль сборки истёк {info.expires:%d.%m.%Y} — iOS её не установит."))
        if not info.all_devices:
            if not info.devices:
                warnings.append(Warning_("Это сборка для App Store / TestFlight — с компьютера она не "
                                         "установится. Ставьте её через TestFlight."))
            elif udid and udid.lower() not in (d.lower() for d in info.devices):
                warnings.append(Warning_("UDID этого iPhone нет в профиле сборки — iOS её не установит. "
                                         "Попросите добавить устройство в профиль и пересобрать."))
    if info.min_ios and ios_version and _version_tuple(ios_version) < _version_tuple(info.min_ios):
        warnings.append(Warning_(f"Нужна iOS {info.min_ios} или новее, на устройстве {ios_version}."))
    return warnings
