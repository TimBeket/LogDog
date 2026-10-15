"""Информация об устройстве: шапка, секции-карточки, полоски батареи и накопителя."""
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QDialog, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QToolButton, QVBoxLayout,
)

from gui import icons, theme
from gui.widgets.dialog_parts import DialogHeader, Section


def _size(num) -> str:
    gb = num / 1e9  # как в Настройках iPhone: десятичные ГБ
    return f"{gb:.0f} ГБ" if gb >= 10 else f"{gb:.1f} ГБ"


def _text(value) -> str:
    return str(value) if value not in (None, "", "-") else "нет данных"


def battery_text(info: dict) -> str:
    level = info.get("battery_level")
    if level is None:
        return "нет данных"
    return f"{level} %" + (" · заряжается" if info.get("charging") else "")


def storage_text(info: dict) -> str:
    total, free = info.get("storage_total"), info.get("storage_free")
    if not total:
        return "нет данных"
    return f"свободно {_size(free)} из {_size(total)}"


class DeviceInfoDialog(QDialog):
    """Сведения об iPhone из DeviceInfoWorker (только чтение)."""

    def __init__(self, info: dict, parent=None):
        super().__init__(parent)
        self.info = info
        self.setWindowTitle("Информация об устройстве")
        self._copy_buttons = []
        self._init_ui()
        self.setFixedWidth(440)
        self.setFixedHeight(self.sizeHint().height())

    def _rows(self) -> list:
        i = self.info
        return [
            ("Система", [("iOS", i.get("ios")), ("Билд", i.get("build")),
                         ("Product Type", i.get("product_type")), ("Аппаратная модель", i.get("hardware"))]),
            ("Идентификаторы", [("UDID", i.get("udid")), ("Wi-Fi MAC", i.get("wifi_mac"))]),
        ]

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 16)
        layout.setSpacing(12)
        i = self.info
        subtitle = " · ".join(x for x in (i.get("model"), f"iOS {i['ios']}" if i.get("ios") else "") if x)
        layout.addLayout(DialogHeader("phone", _text(i.get("name")), subtitle))

        for title, rows in self._rows():
            section = Section(title)
            grid = QGridLayout()
            grid.setHorizontalSpacing(16)
            grid.setVerticalSpacing(6)
            for row, (key, value) in enumerate(rows):
                k = QLabel(key)
                k.setProperty("role", "key")
                k.setMinimumWidth(130)  # одна колонка подписей во всех секциях
                v = QLabel(_text(value))
                v.setProperty("role", "value")
                v.setTextInteractionFlags(Qt.TextSelectableByMouse)
                grid.addWidget(k, row, 0)
                grid.addWidget(v, row, 1)
                if title == "Идентификаторы" and value not in (None, "", "-"):
                    copy = QToolButton()
                    copy.setToolTip(f"Скопировать {key}")
                    copy.setFixedSize(26, 26)
                    copy.setIconSize(QSize(14, 14))
                    copy.clicked.connect(lambda _=False, text=str(value): self._copy(text))
                    self._copy_buttons.append(copy)
                    grid.addWidget(copy, row, 2)
            grid.setColumnStretch(1, 1)
            section.body.addLayout(grid)
            layout.addWidget(section)

        meters = QHBoxLayout()
        meters.setSpacing(12)
        level = i.get("battery_level")
        meters.addWidget(self._meter("Батарея", battery_text(i), level))
        total, free = i.get("storage_total"), i.get("storage_free")
        used = round((total - free) / total * 100) if total else None
        meters.addWidget(self._meter("Накопитель", storage_text(i), used))
        layout.addLayout(meters)

        buttons = QHBoxLayout()
        self.copy_all = QPushButton("Скопировать всё")
        self.copy_all.setProperty("variant", "ghost")
        self.copy_all.clicked.connect(self._copy_all)
        buttons.addWidget(self.copy_all)
        buttons.addStretch()
        close = QPushButton("Готово")
        close.setProperty("variant", "primary")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self._apply_icons()
        theme.theme_signals.theme_changed.connect(self._apply_icons)

    @staticmethod
    def _meter(title: str, text: str, percent):
        section = Section(title)
        label = QLabel(text)
        label.setProperty("role", "value")
        section.body.addWidget(label)
        bar = QProgressBar()
        bar.setTextVisible(False)
        bar.setRange(0, 100)
        bar.setValue(percent or 0)
        bar.setVisible(percent is not None)
        section.body.addWidget(bar)
        return section

    def _apply_icons(self, *_):
        for button in self._copy_buttons:
            button.setIcon(icons.icon("copy"))
        self.copy_all.setIcon(icons.icon("copy"))

    def _copy(self, text: str):
        QApplication.clipboard().setText(text)

    def _copy_all(self):
        i = self.info
        lines = [f"Устройство: {_text(i.get('name'))}", f"Модель: {_text(i.get('model'))}"]
        for _title, rows in self._rows():
            lines += [f"{key}: {_text(value)}" for key, value in rows]
        lines += [f"Батарея: {battery_text(i)}", f"Накопитель: {storage_text(i)}"]
        QApplication.clipboard().setText("\n".join(lines))
        self.copy_all.setText("Скопировано ✓")
        QTimer.singleShot(1500, lambda: self.copy_all.setText("Скопировать всё"))
