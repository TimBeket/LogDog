from PySide6.QtCore import QStandardPaths
from pathlib import Path
import sys
import os

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
