"""Перед установкой .ipa: что это за сборка и встанет ли она на этот iPhone."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from core.ipa_info import IpaInfo, Warning_
from gui import icons, theme


class IpaCheckDialog(QDialog):
    def __init__(self, info: IpaInfo, warnings: list, ios_version: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Установить .ipa")
        self.setMinimumWidth(460)
        t = theme.tokens()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)

        title = QLabel(info.name or info.path.name)
        title.setProperty("role", "title")
        layout.addWidget(title)
        sub = QLabel(info.path.name)
        sub.setProperty("role", "muted")
        layout.addWidget(sub)

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        rows = [
            ("Bundle id", info.bundle_id),
            ("Версия", f"{info.version} ({info.build})" if info.build else info.version),
            ("Минимальная iOS", info.min_ios + (f"  ·  на устройстве {ios_version}" if ios_version else "")),
            ("Сборка", info.kind),
            ("Команда", info.team),
            ("Профиль до", f"{info.expires:%d.%m.%Y}" if info.expires else ""),
        ]
        for label, value in rows:
            if value:
                field = QLabel(value)
                field.setTextInteractionFlags(Qt.TextSelectableByMouse)
                form.addRow(label + ":", field)
        layout.addLayout(form)

        for w in warnings:
            layout.addLayout(self._warning_row(w, t))
        if not warnings:
            ok = QHBoxLayout()
            icon = QLabel()
            icon.setPixmap(icons.pixmap("check", t["accent"], 18))
            ok.addWidget(icon, 0, Qt.AlignTop)
            text = QLabel("Проблем не видно — сборка должна установиться.")
            text.setStyleSheet(f"color: {t['accent']};")
            ok.addWidget(text, 1)
            layout.addLayout(ok)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.install_button = QPushButton("Установить" if not any(w.blocking for w in warnings)
                                          else "Всё равно установить")
        self.install_button.setProperty("variant", "primary" if not warnings else "")
        self.install_button.setDefault(not warnings)
        self.install_button.clicked.connect(self.accept)
        buttons.addWidget(self.install_button)
        layout.addSpacing(4)
        layout.addLayout(buttons)

    @staticmethod
    def _warning_row(w: Warning_, t: dict):
        row = QHBoxLayout()
        color = t["danger"] if w.blocking else t["warn"]
        icon = QLabel()
        icon.setPixmap(icons.pixmap("alert", color, 18))
        row.addWidget(icon, 0, Qt.AlignTop)
        text = QLabel(w.text)
        text.setWordWrap(True)
        text.setStyleSheet(f"color: {color};")
        row.addWidget(text, 1)
        return row
