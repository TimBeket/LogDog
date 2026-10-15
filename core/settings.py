import json

from PySide6.QtCore import QSettings
from utils.helpers import get_app_data_dir

LOG_COLOR_KEYS = ("color_error", "color_warn", "color_info", "color_debug", "color_system")
_LEGACY_DEFAULT_COLORS = {"#ff5252", "#ffeb3b", "#2196f3", "#00ff26", "#9e9e9e"}


class Settings:
    """Manages application settings stored in AppData. PyInstaller safe."""
    def __init__(self):
        try:
            ini_path = str((get_app_data_dir() / "settings.ini").resolve())
            self.store = QSettings(ini_path, QSettings.IniFormat)
        except Exception:
            self.store = QSettings()

    def custom_color(self, key: str) -> str | None:
        """Цвет уровня логов, выбранный пользователем; None — цвет темы
        (gui.theme.LOG_COLORS). Прежние общие для обеих тем цвета по
        умолчанию (их сохранял выбор цвета) считаем невыбранными."""
        value = self.store.value(key, "", type=str)
        if not value or value.lower() in _LEGACY_DEFAULT_COLORS:
            return None
        return value

    def set_color(self, k: str, v: str):
        self.store.setValue(k, v)

    def reset_colors(self):
        for key in LOG_COLOR_KEYS:
            self.store.remove(key)

    def int_val(self, key: str, default: int = 0) -> int:
        # Испорченный settings.ini (правка руками, обрыв записи) не должен
        # ронять программу при старте — берём значение по умолчанию.
        try:
            return int(self.store.value(key, default))
        except (TypeError, ValueError):
            return default

    def set_int(self, k: str, v: int):
        self.store.setValue(k, v)

    def theme(self) -> str:
        return self.store.value("theme", "Dark")

    def set_theme(self, theme: str):
        if theme in ["Light", "Dark"]:
            self.store.setValue("theme", theme)

    def restore_last_filter(self) -> bool:
        return self.store.value("restore_last_filter", True, type=bool)

    def set_restore_last_filter(self, enabled: bool):
        self.store.setValue("restore_last_filter", enabled)

    def help_shown(self) -> bool:
        return self.store.value("help_shown", False, type=bool)

    def set_help_shown(self, shown: bool):
        self.store.setValue("help_shown", shown)

    def last_filter(self) -> str:
        return self.store.value("last_filter", "", type=str)

    def set_last_filter(self, filter_text: str):
        self.store.setValue("last_filter", filter_text)

    def font_size(self) -> int:
        return self.int_val("font_size", 10)

    def set_font_size(self, size: int):
        self.store.setValue("font_size", size)

    def last_mode(self) -> str:
        return self.store.value("last_mode", "ios", type=str)

    def set_last_mode(self, mode: str):
        if mode in ("ios", "unity"):
            self.store.setValue("last_mode", mode)

    def last_unity_ip(self) -> str:
        return self.store.value("last_unity_ip", "192.168.1.100", type=str)

    def set_last_unity_ip(self, ip: str):
        self.store.setValue("last_unity_ip", ip)

    def last_unity_target(self) -> str:
        """Что выбрано в списке Unity в прошлый раз: «usb:<серийный>» или IP."""
        return self.store.value("last_unity_target", "", type=str)

    def set_last_unity_target(self, target: str):
        self.store.setValue("last_unity_target", target)

    def last_unity_port(self, ip: str) -> int | None:
        """Порт, к которому в прошлый раз подключились по этому IP."""
        saved = self.store.value("last_unity_port", "", type=str)
        saved_ip, _, port = saved.rpartition(":")
        return int(port) if saved_ip == ip and port.isdigit() else None

    def set_last_unity_port(self, ip: str, port: int):
        self.store.setValue("last_unity_port", f"{ip}:{port}")

    # ── Окно логов: отслеживание, подсветка, переключатели ──────────────

    def _json_list(self, key: str) -> list:
        try:
            value = json.loads(self.store.value(key, "[]", type=str))
            return value if isinstance(value, list) else []
        except (TypeError, ValueError):
            return []

    def watch_rules(self) -> list:
        """[[выражение, включено], …]"""
        return [[str(r[0]), bool(r[1])] for r in self._json_list("watch_rules")
                if isinstance(r, list) and len(r) == 2]

    def set_watch_rules(self, rules: list):
        self.store.setValue("watch_rules", json.dumps(rules, ensure_ascii=False))

    def highlights(self) -> list:
        """[[текст, цвет], …]"""
        return [[str(r[0]), str(r[1])] for r in self._json_list("highlights")
                if isinstance(r, list) and len(r) == 2]

    def set_highlights(self, rules: list):
        self.store.setValue("highlights", json.dumps(rules, ensure_ascii=False))

    def flag(self, key: str, default: bool) -> bool:
        return self.store.value(key, default, type=bool)

    def set_flag(self, key: str, value: bool):
        self.store.setValue(key, value)

    # ── Уведомления о новых краш-отчётах ────────────────────────────────

    def crash_alerts_enabled(self) -> bool:
        return self.store.value("crash_alerts_enabled", True, type=bool)

    def set_crash_alerts_enabled(self, enabled: bool):
        self.store.setValue("crash_alerts_enabled", enabled)

    def muted_crash_processes(self) -> list:
        """Процессы, о крашах которых не уведомлять. Строкой через перевод
        строки: список из одного элемента QSettings в INI вернул бы строкой."""
        raw = self.store.value("muted_crash_processes", "", type=str)
        return [p for p in raw.split("\n") if p]

    def set_muted_crash_processes(self, processes):
        self.store.setValue("muted_crash_processes", "\n".join(sorted(set(processes))))

    def mute_crash_process(self, process: str):
        self.set_muted_crash_processes(self.muted_crash_processes() + [process])

    def last_save_dir(self) -> str:
        """Последняя папка, куда сохраняли файлы с устройства (краши, данные игры)."""
        return self.store.value("last_save_dir", "", type=str)

    def set_last_save_dir(self, path: str):
        self.store.setValue("last_save_dir", path)

# Singleton accessible throughout the app
settings = Settings()
