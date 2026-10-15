from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QColorDialog, QFormLayout, QGroupBox, QCheckBox, QApplication, QSpinBox
)
from PySide6.QtGui import QColor
from PySide6.QtCore import Qt
from core.settings import settings
from gui import theme
from gui.theme import apply_theme
from core.version import VERSION

_LEVELS = [("error", "Ошибки (Error)"),
           ("warn", "Предупреждения (Warning)"),
           ("info", "Информация (Info)"),
           ("debug", "Отладка (Debug)"),
           ("system", "Сообщения LogDog")]


class SettingsDialog(QDialog):
    """Dialog for configuring LogDog settings."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.setMinimumWidth(380)
        self._init_ui()
        self.layout().setSizeConstraint(QVBoxLayout.SetFixedSize)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 16)
        layout.setSpacing(6)

        # UI Theme
        theme_group = QGroupBox("Внешний вид")
        theme_layout = QFormLayout(theme_group)
        theme_layout.setHorizontalSpacing(16)
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Тёмная", "Dark")
        self.theme_combo.addItem("Светлая", "Light")
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(settings.theme())))
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        theme_layout.addRow("Тема:", self.theme_combo)

        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 24)
        self.font_size_spin.setValue(settings.font_size())
        self.font_size_spin.setSuffix(" pt")
        self.font_size_spin.valueChanged.connect(self._on_font_size_changed)
        theme_layout.addRow("Шрифт логов:", self.font_size_spin)
        layout.addWidget(theme_group)

        # Custom Colors
        color_group = QGroupBox("Цвета логов")
        color_layout = QFormLayout(color_group)
        color_layout.setHorizontalSpacing(16)

        self.color_btns = {}
        for level, label in _LEVELS:
            btn = QPushButton()
            btn.setFixedSize(44, 22)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip("Выбрать цвет")
            btn.clicked.connect(lambda checked=False, l=level: self._pick_color(l))
            color_layout.addRow(label, btn)
            self.color_btns[level] = btn

        reset_btn = QPushButton("Сбросить к цветам темы")
        reset_btn.setProperty("variant", "ghost")
        reset_btn.clicked.connect(self._reset_colors)
        color_layout.addRow(reset_btn)
        layout.addWidget(color_group)
        self._refresh_swatches()

        # Уведомления о новых крашах (gui/crash_alerts.py)
        crash_group = QGroupBox("Уведомления о крашах")
        crash_layout = QVBoxLayout(crash_group)
        self.chk_crash_alerts = QCheckBox("Сообщать о новых краш-отчётах, пока подключён iPhone")
        self.chk_crash_alerts.setChecked(settings.crash_alerts_enabled())
        self.chk_crash_alerts.toggled.connect(self._on_crash_alerts_toggled)
        crash_layout.addWidget(self.chk_crash_alerts)
        self.lbl_muted = QLabel()
        self.lbl_muted.setProperty("role", "muted")
        self.lbl_muted.setWordWrap(True)
        self.lbl_muted.setMaximumWidth(420)
        crash_layout.addWidget(self.lbl_muted)
        self.btn_unmute = QPushButton("Снова показывать для всех")
        self.btn_unmute.setProperty("variant", "ghost")
        self.btn_unmute.clicked.connect(self._unmute_all)
        crash_layout.addWidget(self.btn_unmute, 0, Qt.AlignLeft)
        layout.addWidget(crash_group)
        self._refresh_muted()

        layout.addSpacing(6)
        self.chk_restore_filter = QCheckBox("Восстанавливать последний фильтр при запуске")
        self.chk_restore_filter.setChecked(settings.restore_last_filter())
        self.chk_restore_filter.toggled.connect(settings.set_restore_last_filter)
        layout.addWidget(self.chk_restore_filter)
        layout.addSpacing(8)

        # Footer with GitHub link and license + OK
        bottom = QHBoxLayout()
        footer = QLabel(f'LogDog {VERSION} · GNU GPL v3.0 · '
                        f'<a href="https://github.com/TimBeket/LogDog">GitHub</a>')
        footer.setProperty("role", "muted")
        footer.setOpenExternalLinks(True)
        footer.setTextFormat(Qt.RichText)
        bottom.addWidget(footer)
        bottom.addStretch()
        ok_btn = QPushButton("Готово")
        ok_btn.setProperty("variant", "primary")
        ok_btn.clicked.connect(self.accept)
        bottom.addWidget(ok_btn)
        layout.addLayout(bottom)

    def _effective_color(self, level: str) -> str:
        return settings.custom_color(f"color_{level}") or theme.log_color(level)

    def _refresh_swatches(self):
        border = theme.tokens()["border_strong"]
        for level, btn in self.color_btns.items():
            btn.setStyleSheet(f"QPushButton {{ background-color: {self._effective_color(level)};"
                              f" border: 1px solid {border}; border-radius: 6px; padding: 0; }}")

    def _main_window(self):
        from gui.main_window import MainWindow
        parent = self.parent()
        while parent and not isinstance(parent, MainWindow):
            parent = parent.parent()
        return parent

    def _on_theme_changed(self, _index):
        name = self.theme_combo.currentData()
        settings.set_theme(name)
        app = QApplication.instance()
        if app:
            apply_theme(app, name)  # главное окно перекрасит логи по сигналу темы
        self._refresh_swatches()

    def _on_font_size_changed(self):
        settings.set_font_size(self.font_size_spin.value())
        parent = self._main_window()
        if parent and hasattr(parent, "apply_font_size"):
            parent.apply_font_size()

    def _repaint_logs(self):
        parent = self._main_window()
        if parent and hasattr(parent, "repaint_all_logs"):
            parent.repaint_all_logs()

    def _pick_color(self, level):
        color = QColorDialog.getColor(QColor(self._effective_color(level)), self, "Цвет логов")
        if color.isValid():
            settings.set_color(f"color_{level}", color.name())
            self._refresh_swatches()
            self._repaint_logs()

    def _reset_colors(self):
        settings.reset_colors()
        self._refresh_swatches()
        self._repaint_logs()

    def _refresh_muted(self):
        muted = settings.muted_crash_processes()
        self.lbl_muted.setText("Не показываются: " + ", ".join(muted) if muted
                               else "Показываются для всех процессов")
        self.btn_unmute.setVisible(bool(muted))

    def _unmute_all(self):
        settings.set_muted_crash_processes([])
        self._refresh_muted()

    def _on_crash_alerts_toggled(self, enabled: bool):
        settings.set_crash_alerts_enabled(enabled)
        parent = self._main_window()
        alerts = getattr(parent, "crash_alerts", None) if parent else None
        if alerts is not None:
            if enabled and getattr(parent, "_is_connected", False) and getattr(parent, "_connected_serial", None):
                alerts.start(parent._connected_serial)
            elif not enabled:
                alerts.stop()
