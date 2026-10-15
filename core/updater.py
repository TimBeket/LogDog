"""Проверка и скачивание обновлений с GitHub Releases (открытый репозиторий).

Версию, список изменений и файлы для каждой ОС приложение берёт из
`latest.json` — его кладёт в релиз .github/workflows/release.yml (собирается
из CHANGELOG.md и контрольных сумм сборок, см. .github/scripts/release.py).
Ссылка `releases/latest/download/<файл>` — обычное скачивание файла релиза,
а не GitHub API: у API без токена лимит 60 запросов в час на IP, и в офисе,
где все выходят в интернет с одного адреса, проверка начала бы молча
отказывать. Черновики и pre-release (тестовые ручные сборки) в `latest`
не попадают.

Установка скачанного файла — core/update_install.py (без Qt).
"""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import requests
from PySide6.QtCore import QThread, Signal

from core.update_install import DOWNLOAD_PREFIX, windows_installed
from utils.logger import logger

REPO = "TimBeket/LogDog"
LATEST_JSON_URL = f"https://github.com/{REPO}/releases/latest/download/latest.json"
RELEASES_PAGE_URL = f"https://github.com/{REPO}/releases/latest"
USER_AGENT = "LogDog-UpdateChecker"

_TIMEOUT_SEC = 10
_MAX_ATTEMPTS = 3
_RETRY_DELAY_SEC = 2


@dataclass
class Asset:
    """Файл обновления для текущей ОС: прямая ссылка, имя и SHA-256."""
    url: str
    file: str
    sha256: str


@dataclass
class UpdateInfo:
    version: str
    changelog: str  # Markdown — раздел CHANGELOG.md этой версии
    page_url: str   # страница релиза — для ручной установки
    asset: Asset | None = None  # None — для этой ОС файла нет, только страница


def platform_key() -> str:
    """Ключ платформы в installers из latest.json."""
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def asset_keys() -> list:
    """Какие файлы из latest.json подходят этой копии, по порядку. Установленная
    через Setup — новый Setup (обновляет запись в «Установленных приложениях»
    и ярлыки); если его в релизе нет — portable-zip (подмена папки)."""
    if sys.platform == "win32" and windows_installed():
        return ["windows_setup", "windows"]
    return [platform_key()]


def _parse_version(version: str) -> tuple[int, ...]:
    """'v1.2.3' -> (1, 2, 3); суффиксы вроде '-dev'/'-rc1' отбрасываются."""
    result = []
    for part in version.strip().lstrip("vV").split("-")[0].split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        result.append(int(digits) if digits else 0)
    return tuple(result)


def is_newer(remote: str, current: str) -> bool:
    remote_t = _parse_version(remote)
    current_t = _parse_version(current)
    length = max(len(remote_t), len(current_t))
    remote_t += (0,) * (length - len(remote_t))
    current_t += (0,) * (length - len(current_t))
    return remote_t > current_t


def is_dev_version(version: str) -> bool:
    return version.endswith("-dev")


def _parse_asset(data: dict) -> Asset | None:
    installers = data.get("installers")
    if not isinstance(installers, dict):
        return None
    raw = next((installers[k] for k in asset_keys() if isinstance(installers.get(k), dict)), None)
    if raw is None:
        return None
    url = str(raw.get("url") or "").strip()
    file = str(raw.get("file") or "").strip()
    sha = str(raw.get("sha256") or "").strip().lower()
    # file идёт в имя файла на диске — без разделителей пути
    if not (url and file and Path(file).name == file
            and len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)):
        return None
    return Asset(url=url, file=file, sha256=sha)


def parse_update(data: dict, current_version: str) -> UpdateInfo | None:
    """UpdateInfo, если в latest.json версия новее текущей, иначе None."""
    version = str(data.get("version") or "").strip()
    if not version or not is_newer(version, current_version):
        return None
    return UpdateInfo(
        version=version,
        changelog=str(data.get("changelog") or "").strip(),
        page_url=str(data.get("url") or "").strip() or RELEASES_PAGE_URL,
        asset=_parse_asset(data),
    )


def _fetch_latest() -> dict | None:
    """Один запрос latest.json. None при любой ошибке (в т.ч. 404 — у
    последнего релиза нет latest.json)."""
    try:
        response = requests.get(LATEST_JSON_URL, headers={"User-Agent": USER_AGENT},
                                timeout=_TIMEOUT_SEC)
        logger.info("Update check response: %d", response.status_code)
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Update check failed: %s", exc)
        return None


class UpdaterThread(QThread):
    """Фоновая проверка новой версии при старте."""

    # UpdateInfo
    update_available = Signal(object)

    def __init__(self, current_version: str, parent=None):
        super().__init__(parent)
        self.current_version = current_version
        self._is_running = True

    def run(self):
        # Запуск из исходников (версия 0.0.0-dev) — любой релиз был бы
        # "новее", диалог обновления появлялся бы при каждом старте.
        if is_dev_version(self.current_version):
            logger.info("Dev build (%s), skipping update check", self.current_version)
            return
        logger.info("Checking updates at: %s", LATEST_JSON_URL)
        data = None
        for attempt in range(_MAX_ATTEMPTS):
            if not self._is_running:
                return
            data = _fetch_latest()
            if data is not None:
                break
            if attempt < _MAX_ATTEMPTS - 1:
                time.sleep(_RETRY_DELAY_SEC)
        if not data or not self._is_running:
            return
        info = parse_update(data, self.current_version)
        if info is not None:
            logger.info("Update available: %s", info.version)
            self.update_available.emit(info)

    def stop(self):
        self._is_running = False


def download_dir() -> Path:
    """Новая личная папка в temp (права только у владельца). Не общая
    постоянная: в /tmp на Linux её мог бы заранее создать другой пользователь
    компьютера и подменить файл между проверкой суммы и установкой."""
    return Path(tempfile.mkdtemp(prefix=DOWNLOAD_PREFIX))


class UpdateDownloadThread(QThread):
    """Скачивает файл обновления и сверяет SHA-256 по ходу скачивания."""

    # (скачано байт, всего байт; 0 — размер неизвестен)
    progress = Signal(int, int)
    # путь к проверенному файлу
    downloaded = Signal(str)
    # понятная пользователю причина
    failed = Signal(str)

    def __init__(self, asset: Asset, dest_dir: Path | None = None, parent=None):
        super().__init__(parent)
        self.asset = asset
        self.dest_dir = dest_dir or download_dir()
        self._is_running = True

    def run(self):
        part = self.dest_dir / (self.asset.file + ".part")
        try:
            self.dest_dir.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            with requests.get(self.asset.url, headers={"User-Agent": USER_AGENT},
                              stream=True, timeout=(_TIMEOUT_SEC, 60)) as response:
                response.raise_for_status()
                total = int(response.headers.get("Content-Length") or 0)
                done = 0
                with open(part, "wb") as f:
                    for chunk in response.iter_content(chunk_size=1 << 16):
                        if not self._is_running:
                            raise _Cancelled()
                        f.write(chunk)
                        digest.update(chunk)
                        done += len(chunk)
                        self.progress.emit(done, total)
            if digest.hexdigest() != self.asset.sha256:
                part.unlink(missing_ok=True)
                self._remove_empty_dir()
                self.failed.emit("Контрольная сумма не совпала — файл повреждён или скачан не полностью. "
                                 "Попробуйте ещё раз.")
                return
            final = self.dest_dir / self.asset.file
            os.replace(part, final)
            self.downloaded.emit(str(final))
        except _Cancelled:
            part.unlink(missing_ok=True)
            self._remove_empty_dir()
        except (requests.RequestException, OSError) as exc:
            logger.warning("Update download failed: %s", exc)
            part.unlink(missing_ok=True)
            self._remove_empty_dir()
            self.failed.emit(f"Не удалось скачать обновление: {exc}")

    def _remove_empty_dir(self):
        if self.dest_dir.name.startswith(DOWNLOAD_PREFIX):
            try:
                self.dest_dir.rmdir()
            except OSError:
                pass

    def stop(self):
        self._is_running = False


class _Cancelled(Exception):
    pass
