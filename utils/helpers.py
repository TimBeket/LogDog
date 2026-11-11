from PySide6.QtCore import QStandardPaths
from datetime import datetime
from pathlib import Path
import os
import re
import sys

def resource_path(relative_path: str) -> str:
    """Gets the path to a resource, works both in dev script and PyInstaller .exe/.bin"""
    try:
        # PyInstaller creates a temporary folder _MEIPASS
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = Path(__file__).parent.parent.absolute()
    return str(Path(base_path) / relative_path)

def get_app_data_dir() -> Path:
    """Returns the platform-specific AppData path: ~/.local/share/LogDog (Linux)"""
    locations = QStandardPaths.standardLocations(QStandardPaths.GenericDataLocation)
    if locations:
        app_data = Path(locations[0]) / "LogDog"
    else:
        # Fallback
        app_data = Path(os.path.expanduser("~")) / ".local" / "share" / "LogDog"

    # Create the directory if it doesn't exist
    app_data.mkdir(parents=True, exist_ok=True)
    return app_data


_BAD_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def log_file_name(source: str, when: datetime) -> str:
    """Имя файла для «Сохранить логи»: LogDog_<откуда>_<год-месяц-день>_<часы-минуты>.log.

    Дата — от года, чтобы файлы в папке шли по порядку; время — чтобы
    несколько сохранений за день не затирали друг друга; без «:» (Windows
    не разрешает). Откуда — имя iPhone или игры, без недопустимых символов.
    """
    source = _BAD_FILENAME_CHARS.sub("", source or "")
    source = re.sub(r"\s+", "-", source.strip()).strip(".-_")[:40].strip(".-_")
    parts = ["LogDog", source, when.strftime("%Y-%m-%d_%H-%M")]
    return "_".join(p for p in parts if p) + ".log"


def default_save_dir() -> str:
    """Куда сохранять, если ещё не сохраняли: «Загрузки», иначе домашняя папка."""
    return QStandardPaths.writableLocation(QStandardPaths.DownloadLocation) or str(Path.home())
