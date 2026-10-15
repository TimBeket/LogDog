"""Язык и регион iPhone — для проверки локализации и региональных окон
согласия. Списки — те, что поддерживает само устройство."""
from PySide6.QtCore import QLocale
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)


def _split(code: str):
    """'en-RU' / 'en_RU' -> ('en', 'RU'); 'zh-Hans' -> ('zh', 'Hans')."""
    parts = code.replace("_", "-").split("-", 1)
    return parts[0], parts[1] if len(parts) > 1 else ""


def _territory(part: str) -> str:
    """Страна по коду из двух букв. Язык и страну называем по отдельности:
    сочетаний вроде en_RU Qt не знает и подставил бы en_US — «American English»."""
    if len(part) == 2 and part.isalpha():
        territory = QLocale.codeToTerritory(part.upper())
        if territory != QLocale.AnyTerritory:
            return QLocale.territoryToString(territory)
    return ""


def _language(part: str, script_code: str = "") -> str:
    lang = QLocale.codeToLanguage(part)
    if lang in (QLocale.AnyLanguage, QLocale.C):
        return ""
    script = QLocale.codeToScript(script_code) if len(script_code) == 4 else QLocale.AnyScript
    # английский Qt по умолчанию называет «American English» (en_US); у китайского
    # без письменности — всегда упрощённый
    native = QLocale(lang, script, QLocale.AnyTerritory).nativeLanguageName()
    name = "English" if lang == QLocale.English else (native or QLocale.languageToString(lang))
    return f"{name[:1].upper()}{name[1:]}"


def _script(part: str) -> str:
    if len(part) == 4 and part.isalpha():
        script = QLocale.codeToScript(part)
        if script != QLocale.AnyScript:
            return QLocale.scriptToString(script)
    return ""


def language_title(code: str) -> str:
    """'ru' -> 'Русский — ru', 'en-RU' -> 'English (Russia) — en-RU'."""
    lang, rest = _split(code)
    name = _language(lang, rest)
    if not name:
        return code
    extra = _territory(rest) or _script(rest) or rest
    return f"{name} ({extra}) — {code}" if extra else f"{name} — {code}"


def region_title(code: str) -> str:
    """Регион — по стране: 'en_RU' -> 'Russia (English) — en_RU'."""
    lang, rest = _split(code)
    territory = _territory(rest)
    if not territory:
        return code
    language = QLocale.languageToString(QLocale.codeToLanguage(lang)) if lang else ""
    return f"{territory} ({language}) — {code}" if language else f"{territory} — {code}"


# Сверху — то, что QA выставляют чаще всего
_COMMON_LANGUAGES = ["en", "ru", "de", "fr", "es", "pt-BR", "it", "ja", "ko", "zh-Hans", "tr", "ar"]
_COMMON_REGIONS = ["en_US", "en_GB", "ru_RU", "de_DE", "fr_FR", "es_ES", "pt_BR", "it_IT", "ja_JP",
                   "ko_KR", "zh_CN", "tr_TR", "en_IN", "en_CA", "en_AU"]


def _ordered(codes: list, common: list, current: str) -> list:
    rest = sorted(c for c in codes if c not in common)
    head = [c for c in common if c in codes or not codes]
    result = head + rest
    if current and current not in result:
        result.insert(0, current)
    return result


class LanguageDialog(QDialog):
    def __init__(self, intl: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Язык и регион")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)
        title = QLabel("Язык и регион iPhone")
        title.setProperty("role", "title")
        layout.addWidget(title)
        current = QLabel(f"Сейчас: {language_title(intl.get('language', ''))}  ·  "
                         f"{region_title(intl.get('locale', ''))}")
        current.setProperty("role", "muted")
        current.setWordWrap(True)
        layout.addWidget(current)

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        self.language_combo = QComboBox()
        for code in _ordered(intl.get("languages") or [], _COMMON_LANGUAGES, intl.get("language", "")):
            self.language_combo.addItem(language_title(code), code)
        self.language_combo.setCurrentIndex(max(0, self.language_combo.findData(intl.get("language"))))
        form.addRow("Язык:", self.language_combo)
        self.region_combo = QComboBox()
        for code in _ordered(intl.get("locales") or [], _COMMON_REGIONS, intl.get("locale", "")):
            self.region_combo.addItem(region_title(code), code)
        self.region_combo.setCurrentIndex(max(0, self.region_combo.findData(intl.get("locale"))))
        form.addRow("Регион:", self.region_combo)
        for combo in (self.language_combo, self.region_combo):
            combo.setMaxVisibleItems(16)
        layout.addLayout(form)

        hint = QLabel("iOS обычно применяет сразу. Если интерфейс iPhone не сменился — "
                      "перезагрузите его (карточка «Перезагрузить» в инструментах).")
        hint.setProperty("role", "muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        apply = QPushButton("Применить")
        apply.setProperty("variant", "primary")
        apply.setDefault(True)
        apply.clicked.connect(self.accept)
        buttons.addWidget(apply)
        layout.addLayout(buttons)

    def selection(self) -> tuple:
        return self.language_combo.currentData(), self.region_combo.currentData()
