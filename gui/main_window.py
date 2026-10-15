import re
from collections import Counter, deque
import bisect
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QEvent, Qt, QTimer, QSize
from PySide6.QtGui import (
    QTextCharFormat, QColor, QFont, QFontDatabase, QCloseEvent, QShowEvent,
    QShortcut, QKeySequence, QTextCursor, QIcon
)
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QComboBox, QLineEdit, QToolButton,
    QLabel, QMessageBox, QCheckBox, QStatusBar, QFileDialog, QFrame, QInputDialog, QSplitter
)

from core.settings import settings
from core.filter import LogFilter, get_log_level
from core.log_entry import MAX_DELTA_SEC, entry_time, message_key
from core.processor import LogFileLoader, LogProcessor, is_new_log_line
from core.watch import WatchList
from core.updater import UpdaterThread
from core.version import VERSION
from gui import icons, theme
from gui.theme import theme_signals
from gui.dialogs.help import HelpDialog
from gui.dialogs.settings import SettingsDialog
from gui.dialogs.update import UpdateDialog
from gui.dialogs.tools import ToolsWindow
from gui.crash_alerts import CrashAlerts
from gui.widgets.filter_edit import FilterLineEdit
from gui.widgets.log_view import LogView
from gui.widgets.side_panel import SidePanel
from gui.widgets.filter_history import FilterHistoryWidget
from gui.widgets.find_bar import FindBar
from transports.syslog_device import IosDevicePoller, IosSyslogReader
from transports.unity_socket import USB_PREFIX, GameDiscovery, UnityTCPReader
from utils.helpers import resource_path
from utils.logger import logger


def repaint_document_by_level(doc, color_for_level):
    """Re-colors every logical log entry in `doc` using color_for_level(level).

    Groups consecutive QTextBlocks the same way LogProcessor groups raw lines
    at insert time (core.processor.is_new_log_line decides where a new
    logical entry starts), computes get_log_level ONCE on the whole group's
    joined text, and applies a single QTextCharFormat across the entire span
    of QTextBlocks in that group - so a multi-line entry (e.g. a Unity stack
    trace) keeps one consistent color even after a theme change or custom
    color pick triggers a repaint, instead of being recomputed line-by-line
    in isolation.
    """
    cursor = QTextCursor(doc)
    cursor.beginEditBlock()

    block = doc.firstBlock()
    while block.isValid():
        group = [block]
        nxt = block.next()
        while nxt.isValid() and not is_new_log_line(nxt.text()):
            group.append(nxt)
            nxt = nxt.next()

        raw = "\n".join(b.text() for b in group)
        color = color_for_level(get_log_level(raw))

        cursor.setPosition(group[0].position())
        cursor.setPosition(group[-1].position(), QTextCursor.KeepAnchor)
        cursor.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)

        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cursor.setCharFormat(fmt)

        block = nxt

    cursor.endEditBlock()


class MainWindow(QMainWindow):
    """Main Application Window for LogDog."""

    MAX_STORED_ENTRIES = 100_000

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"LogDog {VERSION}")
        self.resize(1200, 800)
        
        self.filter_obj = LogFilter()
        
        self.processor = LogProcessor(self.filter_obj)
        self.processor.processed_blocks.connect(self._on_incoming_blocks)
        self.processor.start()
        
        # Все полученные записи по порядку (raw + props) — фильтр выбирает из
        # них, что показать. Раньше при смене фильтра уровень каждой строки
        # определялся заново (секунды на десятках тысяч), а скрытые записи
        # оказывались после показанных — ломался порядок.
        self._entries: deque = deque(maxlen=self.MAX_STORED_ENTRIES)
        self._entry_sizes = deque()  # число строк (QTextBlock) у каждой показанной записи
        self._shown_ids = deque()    # id каждой показанной записи (параллельно _entry_sizes)
        self._next_id = 0
        self._pause_from_id = 0  # id первой записи, пришедшей во время паузы
        self._last_shown = None      # последняя показанная: для «×N» и колонки времени
        self._markers = 0
        self._watch = WatchList(settings.watch_rules())
        self._highlights = settings.highlights()
        self._watch_refresh = QTimer(self)
        self._watch_refresh.setSingleShot(True)
        self._watch_refresh.setInterval(300)
        self._watch_refresh.timeout.connect(lambda: self.side_panel.watch_page.refresh())
        self._file_loader = None
        self._tour_state = None  # обучение идёт: отложенные логи и настройки
        self._tour = None
        self._proc_counts = Counter()  # для подсказок proc: в поле фильтра
        
        self.transport_thread = None
        self.poller_thread = None
        self.updater_thread = None
        self.tools_window = None
        self._is_connected = False
        self._link_state = None        # состояние связи от транспорта (BaseReader.state_changed)
        self._connected_serial = None  # к какому iPhone подключены (iOS)
        self._ios_device_available = False
        # Уведомления о новых крашах, пока подключён iPhone (gui/crash_alerts.py):
        # start() в _connect, stop() в _disconnect, shutdown() в closeEvent.
        self.crash_alerts = CrashAlerts(self)

        self._init_ui()
        self._init_updater()
        self._restore_last_filter()
        
    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Шапка ───────────────────────────────────────────────────────
        header = QWidget()
        header.setObjectName("HeaderBar")
        toolbar = QHBoxLayout(header)
        toolbar.setContentsMargins(12, 8, 12, 8)
        toolbar.setSpacing(8)

        logo = QLabel()
        logo.setPixmap(QIcon(resource_path("assets/icon.png")).pixmap(QSize(26, 26)))
        toolbar.addWidget(logo)
        title = QLabel("LogDog")
        title.setObjectName("AppTitle")
        toolbar.addWidget(title)
        toolbar.addSpacing(10)

        # Mode Selection
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("iOS Syslog", "ios")
        self.mode_combo.addItem("Unity TCP", "unity")
        self.mode_combo.setToolTip("Источник логов")
        self.mode_combo.setMinimumWidth(130)
        last_mode_idx = self.mode_combo.findData(settings.last_mode())
        if last_mode_idx >= 0:
            self.mode_combo.blockSignals(True)
            self.mode_combo.setCurrentIndex(last_mode_idx)
            self.mode_combo.blockSignals(False)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        toolbar.addWidget(self.mode_combo)

        # Device / IP Input
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(260)
        self.device_combo.setToolTip("iOS-устройство")
        self.device_combo.currentIndexChanged.connect(self._on_device_selected)
        # Unity: откуда читать — iPhone по USB, игра в Wi-Fi, последний IP или IP
        # вручную. Выбрал — LogDog подключается и ждёт игру (логи с самого запуска).
        self.unity_combo = QComboBox()
        self.unity_combo.setMinimumWidth(330)
        self.unity_combo.setToolTip("Откуда читать логи Unity: iPhone по USB, игра в Wi-Fi или IP вручную")
        self.unity_combo.activated.connect(self._on_unity_target_chosen)
        self.ip_input = QLineEdit(settings.last_unity_ip())
        self.ip_input.setFixedWidth(190)
        self.ip_input.setPlaceholderText("IP или IP:порт, Enter")
        self.ip_input.setToolTip("IP iPhone с игрой (Настройки → Wi-Fi → сеть → IP-адрес). Порт LogDog "
                                 "найдёт сам; если нужен конкретный — через двоеточие: 192.168.1.5:55123")
        self.ip_input.returnPressed.connect(lambda: self._connect_unity(auto=False))
        self._discovery = None
        self._games: list = []
        self._unity_stopped_by_user = False  # «стоп» — не подключаться самим, пока не выберут снова
        toolbar.addWidget(self.device_combo)
        toolbar.addWidget(self.unity_combo)
        toolbar.addWidget(self.ip_input)

        # Unity: подключиться / отключиться — иконкой, в стиле остальных кнопок
        self.connect_btn = self._make_tool_button("Подключиться и ждать игру")
        self.connect_btn.clicked.connect(self._toggle_connection)
        toolbar.addWidget(self.connect_btn)
        toolbar.addSpacing(10)

        # Filter: поиск слева, история справа — внутри поля
        self.filter_input = FilterLineEdit()
        self.filter_input.set_proc_source(lambda: [p for p, _ in self._proc_counts.most_common(300)])
        self.filter_input.setPlaceholderText('Фильтр: level:error OR text:"crash"  —  Ctrl+Space подсказки')
        # Фильтр применяется сам, когда набор замер; Enter — сразу.
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(350)
        self._filter_timer.timeout.connect(lambda: self._apply_filter(remember=False))
        self.filter_input.textChanged.connect(lambda _t: self._filter_timer.start())
        self.filter_input.returnPressed.connect(self._apply_filter)
        self.filter_input.editingFinished.connect(self._remember_filter)
        self.filter_input.setClearButtonEnabled(True)
        self._filter_search_action = self.filter_input.addAction(QIcon(), QLineEdit.LeadingPosition)
        self._filter_history_action = self.filter_input.addAction(QIcon(), QLineEdit.TrailingPosition)
        self._filter_history_action.setToolTip("Последние фильтры")
        self._filter_history_action.triggered.connect(self._show_filter_history)
        self.filter_history_widget = FilterHistoryWidget(self)
        toolbar.addWidget(self.filter_input, 1)

        # Auto-scroll
        self.chk_auto_scroll = QCheckBox("Автопрокрутка")
        self.chk_auto_scroll.setToolTip("Показывать новые логи (выключается, если прокрутить вверх)")
        self.chk_auto_scroll.setChecked(True)
        self.chk_auto_scroll.stateChanged.connect(self._on_auto_scroll_toggled)
        toolbar.addWidget(self.chk_auto_scroll)

        # Help
        self.btn_help = self._make_tool_button("Справка")
        self.btn_help.clicked.connect(self._show_help)
        toolbar.addWidget(self.btn_help)

        layout.addWidget(header)

        # Middle Section: Buttons + Logs
        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Left Panel — icon toolbar
        sidebar = QWidget()
        sidebar.setObjectName("SideBar")
        left_panel = QVBoxLayout(sidebar)
        left_panel.setContentsMargins(6, 8, 6, 8)
        left_panel.setSpacing(4)

        self.btn_pause = self._make_tool_button("Пауза", checkable=True)
        self.btn_pause.toggled.connect(self._on_pause_toggled)
        left_panel.addWidget(self.btn_pause)

        self.btn_marker = self._make_tool_button("Маркер шага (Ctrl+M)")
        self.btn_marker.clicked.connect(self._add_marker)
        left_panel.addWidget(self.btn_marker)

        self.btn_clear = self._make_tool_button("Очистить логи")
        self.btn_clear.clicked.connect(self._clear_logs)
        left_panel.addWidget(self.btn_clear)

        self.btn_save = self._make_tool_button("Сохранить логи в файл")
        self.btn_save.clicked.connect(self._save_logs)
        left_panel.addWidget(self.btn_save)

        self.btn_open = self._make_tool_button("Открыть лог-файл")
        self.btn_open.clicked.connect(self._open_log_file)
        left_panel.addWidget(self.btn_open)

        sep_view = QFrame()
        sep_view.setObjectName("SideBarSeparator")
        left_panel.addWidget(sep_view)

        self.btn_collapse = self._make_tool_button("Схлопывать одинаковые строки подряд (×N)", checkable=True)
        self.btn_collapse.setChecked(settings.flag("collapse_repeats", True))
        self.btn_collapse.toggled.connect(self._on_collapse_toggled)
        left_panel.addWidget(self.btn_collapse)

        self.btn_delta = self._make_tool_button("Время от предыдущей строки (колонка слева)", checkable=True)
        self.btn_delta.setChecked(settings.flag("show_time_delta", False))
        self.btn_delta.toggled.connect(self._on_delta_toggled)
        left_panel.addWidget(self.btn_delta)

        self.btn_panel = self._make_tool_button("Панель: подробности строки, отслеживание, подсветка", checkable=True)
        self.btn_panel.toggled.connect(self._on_panel_toggled)
        left_panel.addWidget(self.btn_panel)

        left_panel.addStretch()

        self.btn_tools = self._make_tool_button("Инструменты iOS-устройства")
        self.btn_tools.clicked.connect(self._open_tools)
        left_panel.addWidget(self.btn_tools)

        sep_line = QFrame()
        sep_line.setObjectName("SideBarSeparator")
        left_panel.addWidget(sep_line)

        self.btn_settings = self._make_tool_button("Настройки")
        self.btn_settings.clicked.connect(self._show_settings)
        left_panel.addWidget(self.btn_settings)

        content_layout.addWidget(sidebar)

        # Log Display
        self.log_display = LogView()
        self.log_display.setFont(self._log_font())
        self.log_display.set_gutter_visible(self.btn_delta.isChecked())
        self.log_display.set_highlights(self._highlights)
        self.log_display.highlight_requested.connect(self._add_highlight)
        self.log_display.watch_requested.connect(self._add_watch)
        self.log_display.marker_requested.connect(self._add_marker)
        self.log_display.cursorPositionChanged.connect(self._on_log_cursor_moved)
        # Trim by entry count — one entry may span multiple QTextBlocks (stack traces)
        self.MAX_LOG_ENTRIES = 50000
        # Connect scrollbar для отслеживания ручного скролла пользователя
        self.log_display.verticalScrollBar().valueChanged.connect(self._on_scroll_user_moved)

        self.side_panel = SidePanel(self._watch, self._highlights)
        self.side_panel.closed.connect(lambda: self.btn_panel.setChecked(False))
        self.side_panel.watch_page.changed.connect(self._on_watch_changed)
        self.side_panel.watch_page.jump_requested.connect(self._jump_to_entry)
        self.side_panel.highlights_page.changed.connect(self._on_highlights_changed)
        self.side_panel.hide()
        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.addWidget(self.log_display)
        self._splitter.addWidget(self.side_panel)
        self._splitter.setStretchFactor(0, 1)
        content_layout.addWidget(self._splitter)
        QShortcut(QKeySequence("Ctrl+M"), self, self._add_marker)

        # Find Bar (Ctrl+F) — hidden by default, sits above log area
        self.find_bar = FindBar(self.log_display)
        layout.insertWidget(1, self.find_bar)

        # Ctrl+F shortcut to open find bar
        QShortcut(QKeySequence("Ctrl+F"), self, self.find_bar.show)

        layout.addLayout(content_layout)

        # Add Status Bar
        self.status_bar = QStatusBar()
        self.status_bar.setSizeGripEnabled(False)
        self.setStatusBar(self.status_bar)
        # Постоянные виджеты справа: обычные Qt перекрывает временными сообщениями.
        self.lbl_connection = QLabel()
        self.status_bar.addPermanentWidget(self.lbl_connection)
        self.lbl_line_count = QLabel("Логов: 0")
        self.status_bar.addPermanentWidget(self.lbl_line_count)
        self.status_bar.showMessage("Готово")
        
        self._on_mode_changed(self.mode_combo.currentIndex())
        self._apply_icons()
        theme_signals.theme_changed.connect(self._apply_icons)
        # Уже показанные логи раскрашены цветами прежней темы.
        theme_signals.theme_changed.connect(self.repaint_all_logs)

    def event(self, event):
        if event.type() == QEvent.WindowBlocked:
            theme.clear_stale_hover(self)  # кнопки слева открывают окна (настройки, справка…)
        return super().event(event)

    def _make_tool_button(self, tooltip: str, checkable: bool = False) -> QToolButton:
        btn = QToolButton()
        btn.setToolTip(tooltip)
        btn.setCheckable(checkable)
        btn.setFixedSize(34, 34)
        btn.setIconSize(QSize(20, 20))
        btn.setCursor(Qt.PointingHandCursor)
        return btn

    def _apply_icons(self, *_):
        """Иконки в цветах текущей темы (и заново — после её смены)."""
        self.mode_combo.setItemIcon(0, icons.icon("phone"))
        self.mode_combo.setItemIcon(1, icons.icon("gamepad"))
        self._filter_search_action.setIcon(icons.icon("search"))
        self._filter_history_action.setIcon(icons.icon("history"))
        self.btn_help.setIcon(icons.icon("help"))
        self.btn_pause.setIcon(icons.icon("pause", checked_name="play"))
        self.btn_save.setIcon(icons.icon("save"))
        self.btn_clear.setIcon(icons.icon("trash"))
        self.btn_marker.setIcon(icons.icon("flag"))
        self.btn_open.setIcon(icons.icon("folder"))
        self.btn_collapse.setIcon(icons.icon("layers"))
        self.btn_delta.setIcon(icons.icon("clock"))
        self.btn_panel.setIcon(icons.icon("panel_right"))
        self._update_connect_button()
        self.btn_tools.setIcon(icons.icon("toolbox"))
        self.btn_settings.setIcon(icons.icon("settings"))
        self._update_connection_indicator()

    _LINK_STATES = {
        "streaming": ("accent", "Логи идут"),
        "connecting": ("warn", "Подключение…"),
        "waiting": ("warn", "Нет связи — жду"),
    }

    def _update_connection_indicator(self):
        t = theme.tokens()
        state = self._link_state if self._is_connected else None
        color_key, text = self._LINK_STATES.get(state, ("faint", "Не подключено"))
        if self._is_connected and state is None:
            color_key, text = "warn", "Подключение…"
        self.lbl_connection.setText(f'<span style="color:{t[color_key]}">●</span>&nbsp;{text}')

    def _on_link_state(self, state: str):
        self._link_state = state
        self._update_connection_indicator()
        self._refresh_unity_label()

    def _refresh_unity_label(self):
        """Подпись выбранного в списке Unity — по состоянию: «логи идут» /
        «жду запуска игры» (список не обновляется, пока подключены)."""
        if self.mode_combo.currentData() != "unity" or not self._is_connected:
            return
        t = self._unity_target()
        if t.get("kind") not in ("usb", "wifi", "last", "manual"):
            return
        base = (f"{t.get('device') or 'iPhone'}  ·  по USB" if t["kind"] == "usb"
                else f"{self._unity_target_string()}  ·  по Wi-Fi")
        suffix = {"streaming": "логи идут", "waiting": "жду запуска игры"}.get(self._link_state)
        if t["kind"] != "manual":
            self.unity_combo.setItemText(self.unity_combo.currentIndex(), f"{base}  —  {suffix}" if suffix else base)

    @staticmethod
    def _log_font() -> QFont:
        """Моноширинный шрифт системы: Courier, как раньше, на Windows выглядит
        как пишущая машинка."""
        font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        font.setFamilies(["JetBrains Mono", "Cascadia Mono", "Consolas", "SF Mono", "Menlo",
                          "DejaVu Sans Mono", font.family()])
        font.setPointSize(settings.font_size())
        return font

    def _init_updater(self):
        self.updater_thread = UpdaterThread(current_version=VERSION)
        self.updater_thread.update_available.connect(self._on_update_available)
        self.updater_thread.start()

    def showEvent(self, event: QShowEvent):
        super().showEvent(event)
        QTimer.singleShot(0, self._maybe_show_help_on_first_run)

    def _maybe_show_help_on_first_run(self):
        """Первый запуск: предложить обучение (добровольно) — один раз."""
        if not settings.help_shown():
            settings.set_help_shown(True)
            box = QMessageBox(self)
            box.setWindowTitle("Добро пожаловать в LogDog")
            box.setText("<b>Пройти короткое обучение?</b>")
            box.setInformativeText("Около 3 минут: покажу на примере, где что и как искать нужное в логах. "
                                   "Пройти его можно и позже — из справки (кнопка «?» справа вверху).")
            start = box.addButton("Пройти", QMessageBox.AcceptRole)
            box.addButton("Позже", QMessageBox.RejectRole)
            start.setProperty("variant", "primary")
            box.exec()
            if box.clickedButton() is start:
                self.start_tour()

    def _on_update_available(self, info):
        dialog = UpdateDialog(info, self)
        dialog.exec()
        if dialog.quit_requested:
            # Обновление запущено: Windows/macOS ждут выхода программы,
            # на Linux новый AppImage уже стартовал.
            self.close()

    def _on_mode_changed(self, index: int):
        mode = self.mode_combo.itemData(index)
        settings.set_last_mode(mode)

        if self._is_connected:
            self._disconnect()

        if mode == "ios":
            self.device_combo.blockSignals(True)
            self.device_combo.clear()
            self.device_combo.blockSignals(False)
            
            self.ip_input.hide()
            self.unity_combo.hide()
            self.device_combo.show()
            self.connect_btn.hide()
            
            self._stop_discovery()
            if not self.poller_thread:
                self.poller_thread = IosDevicePoller()
                self.poller_thread.devices_updated.connect(self._on_devices_updated)
                self.poller_thread.start()
        else: # Unity TCP
            self._start_discovery()
            self._ios_device_available = False
            self._sync_tools_state()
            if self.poller_thread:
                self.poller_thread.stop()
                self.poller_thread.quit()
                self.poller_thread.wait()
                self.poller_thread = None
                
            self.device_combo.hide()
            self.unity_combo.show()
            self.ip_input.setVisible(self._unity_kind() == "manual")
            self.connect_btn.show()
            self.connect_btn.setEnabled(True)
            self._unity_stopped_by_user = False
            self._rebuild_unity_combo()

    def _on_devices_updated(self, devices: list):
        current_data = self._connected_serial or self.device_combo.currentData()
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        
        if not devices:
            self.device_combo.addItem("Нет подключенных устройств", "")
            self.connect_btn.setEnabled(False)
            self.status_bar.showMessage("Не найдено iOS устройств")
            self._ios_device_available = False
        else:
            # Check if the first item is a string, indicating an error message
            if isinstance(devices[0], str):
                self.device_combo.addItem(devices[0], "")
                self.connect_btn.setEnabled(False)
                self.status_bar.showMessage(devices[0])
                self._ios_device_available = False
            else:
                for dev in devices:
                    display_text = f"{dev['name']} ({dev['model']})" if dev.get("model") else dev["name"]
                    self.device_combo.addItem(display_text, dev["serial"])
                
                idx = 0
                if current_data:
                    idx = self.device_combo.findData(current_data)
                    if idx < 0:
                        idx = 0
                
                if self.device_combo.count() > 0:
                    self.device_combo.setCurrentIndex(idx)
                        
                self.connect_btn.setEnabled(self.device_combo.count() > 0)
                self._ios_device_available = True
            
        self.device_combo.blockSignals(False)
        self._sync_tools_state()

        # Подключённый iPhone пропал из списка — сразу показать, не дожидаясь
        # ошибки чтения. Вернулся — поток чтения переподключится сам (без
        # перезапуска и вопроса «очистить логи?»).
        if self._is_connected and self._connected_serial and self.mode_combo.currentData() == "ios":
            serials = [d["serial"] for d in devices if isinstance(d, dict)]
            if self._connected_serial not in serials:
                self._on_link_state("waiting")
                self.status_bar.showMessage("Устройство отключено — логи продолжатся, когда его подключат снова")
            elif self.device_combo.currentData() == self._connected_serial:
                if self._link_state == "waiting":
                    self.status_bar.showMessage("Устройство снова подключено — переподключаюсь…")
                return

        new_current = self.device_combo.currentData()
        if new_current and new_current != current_data:
            if self.mode_combo.currentData() == "ios":
                self._disconnect()
                self._connect()

    def _on_device_selected(self, index):
        if self.mode_combo.currentData() == "ios":
            if index >= 0 and self.device_combo.currentData():
                self._disconnect()
                self._connect()

    def _open_tools(self):
        """Show (or raise) the non-modal additional tools window."""
        if self.tools_window is None:
            self.tools_window = ToolsWindow(self)
        self.tools_window.refresh_device_state()
        self.tools_window.show()
        self.tools_window.raise_()
        self.tools_window.activateWindow()

    def _sync_tools_state(self):
        """Push current device availability to the open tools window."""
        if self.tools_window is not None:
            self.tools_window.refresh_device_state()

    def current_device_serial(self) -> str:
        """Serial of the selected iOS device, or '' in Unity mode."""
        if self.mode_combo.currentData() == "ios":
            return self.device_combo.currentData() or ""
        return ""

    def _toggle_connection(self):
        if self._is_connected:
            self._unity_stopped_by_user = True  # не подключаться снова самим
            self._disconnect()
        else:
            self._connect()

    def _connect(self, auto: bool = False):
        """auto — подключение без действия пользователя (LogDog сам нашёл
        iPhone или игру): без вопроса «очистить логи?», просто разделитель."""
        if self.mode_combo.currentData() == "unity" and self._unity_target_string() is None:
            self._unity_hint()
            return
        if auto and self.log_display.toPlainText().strip():
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            line = f"{stamp} [LogDog:System] ──────── Новое подключение ────────"
            self._on_blocks_processed([{"raw": line, "props": self.filter_obj.extract_props(line)}])
        elif self.log_display.toPlainText().strip():
            msg = QMessageBox(self)
            msg.setWindowTitle("Внимание: Очистка логов")
            msg.setText("Очистить старые логи перед сбором новых?")
            btn_yes = msg.addButton("Очистить", QMessageBox.YesRole)
            btn_no = msg.addButton("Оставить", QMessageBox.NoRole)
            btn_cancel = msg.addButton("Отмена", QMessageBox.RejectRole)
            
            msg.exec()
            if msg.clickedButton() == btn_cancel:
                return
            elif msg.clickedButton() == btn_yes:
                self._clear_logs()
            else:
                stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                line = f"{stamp} [LogDog:System] ──────── Новое подключение ────────"
                self._on_blocks_processed([{"raw": line, "props": self.filter_obj.extract_props(line)}])
                
        mode = self.mode_combo.currentData()

        if mode == "ios":
            serial = self.device_combo.currentData()
            display_name = self.device_combo.currentText()
            if not serial: return
            self.transport_thread = IosSyslogReader(serial, display_name)
            self._connected_serial = serial
        else:
            target = self._unity_target_string()
            if not target.startswith(USB_PREFIX):
                settings.set_last_unity_ip(target)
            settings.set_last_unity_target(target)
            self._unity_stopped_by_user = False
            self.transport_thread = UnityTCPReader(target, port_hint=settings.last_unity_port(target))
            self.transport_thread.port_found.connect(
                lambda port, key=target: settings.set_last_unity_port(key, port))
            
        self.transport_thread.lines_ready.connect(self.processor.enqueue_lines)
        self.transport_thread.error_occurred.connect(self._on_transport_error)
        self.transport_thread.status_changed.connect(self._update_status)
        self._link_state = None
        self.transport_thread.state_changed.connect(self._on_link_state)
        self.transport_thread.start()
        
        self._stop_discovery()  # подключились — искать игры незачем
        self._is_connected = True
        self._update_connect_button()
        self._update_connection_indicator()
        self.crash_alerts.start(self._connected_serial or "")

    def _disconnect(self):
        self.crash_alerts.stop()
        if self.transport_thread:
            # Disconnect all signals from the old thread to prevent stale delivery
            try:
                self.transport_thread.lines_ready.disconnect()
                self.transport_thread.error_occurred.disconnect()
                self.transport_thread.status_changed.disconnect()
                self.transport_thread.state_changed.disconnect()
            except RuntimeError:
                pass
            self.transport_thread.stop()
            self.transport_thread.quit()
            self.transport_thread.wait(2000) # Give 2 secs to close
            if self.transport_thread.isRunning():
                self.transport_thread.terminate()
                self.transport_thread.wait()
            self.transport_thread = None
            
        self._is_connected = False
        if self.mode_combo.currentData() == "unity":
            self._start_discovery()
        self._update_connect_button()
        self._connected_serial = None
        self._link_state = None
        self._update_connection_indicator()
        self.status_bar.showMessage("Сбор логов остановлен (Отключено)", 5000)

    def _on_pause_toggled(self, checked: bool):
        if checked:
            self._pause_from_id = self._next_id
            self.status_bar.showMessage("Пауза: экран заморожен, новые логи копятся и появятся после паузы")
            self._update_entry_count()
        else:
            self.status_bar.showMessage("Пауза снята", 5000)
            self._reapply_filter_to_history()

    def _on_transport_error(self, err_msg: str):
        self.status_bar.showMessage(f"Ошибка: {err_msg}", 10000)
        self._disconnect()

    def _restore_last_filter(self):
        """Restore the last filter from settings if enabled."""
        if settings.restore_last_filter():
            last = settings.last_filter()
            if last:
                self.filter_input.setText(last)
                self.filter_obj.set_filter(last)

    def _apply_filter(self, remember: bool = True):
        """remember=False — применение «на лету» при наборе: в историю такие
        промежуточные фильтры не попадают, только по Enter или уходу из поля."""
        self._filter_timer.stop()
        flt = self.filter_input.text().strip()
        if self.filter_input.has_errors():
            return  # недописанный фильтр — оставляем прежний, ошибку покажет поле
        if flt != self.filter_obj.filter_text:
            self.filter_obj.set_filter(flt)
            self._reapply_filter_to_history()
            settings.set_last_filter(flt)
        if remember:
            self._remember_filter()

    def _remember_filter(self):
        flt = self.filter_obj.filter_text
        if flt and flt == self.filter_input.text().strip():
            self.filter_history_widget.add_filter(flt)

    def apply_history_filter(self, filter_text: str):
        self.filter_input.setText(filter_text)
        self._apply_filter()

    def _show_filter_history(self):
        if self.filter_history_widget.isHidden():
            self.filter_history_widget.show_below_widget(self.filter_input)
        else:
            self.filter_history_widget.hide()

    def _update_status(self, msg: str):
        self.status_bar.showMessage(msg)

    def _save_logs(self):
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить логи", "", "Log Files (*.log);;All Files (*)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self.log_display.toPlainText())
                self.status_bar.showMessage(f"Логи успешно сохранены в {path}", 5000)
            except Exception as e:
                self.status_bar.showMessage(f"Ошибка сохранения файла: {e}", 5000)

    def _update_entry_count(self):
        shown, total = len(self._entry_sizes), len(self._entries)
        if self.btn_pause.isChecked():
            # На паузе растёт не «всего», а очередь: так понятно, что логи ждут, а не теряются
            waiting = self._next_id - self._pause_from_id
            text = f"Показано {shown:,}" + (f" · ещё {waiting:,} после паузы" if waiting else " · пауза")
            self.lbl_line_count.setText(text.replace(",", " "))
        elif self.filter_obj.filter_text or shown != total:
            self.lbl_line_count.setText(f"Показано {shown:,} из {total:,}".replace(",", " "))
        else:
            self.lbl_line_count.setText(f"Логов: {total:,}".replace(",", " "))

    _COLOR_TAG_PATTERN = re.compile(r'\[LogDog:(Red|Green|Magenta|Teal|Yellow)\]', re.IGNORECASE)
    _SYSTEM_TAG_PATTERN = re.compile(r'\[LogDog:System\]', re.IGNORECASE)

    _MARKER_TAG_PATTERN = re.compile(r'\[LogDog:Marker\]\s*')

    def _render(self, entry: dict) -> tuple:
        """(текст, цвет, жирный) записи на экране."""
        raw = entry["raw"]
        if entry["props"].get("level") == "marker":
            return self._MARKER_TAG_PATTERN.sub("══ ", raw) + " ══", theme.tokens()["accent"], True
        color = self._get_base_color(entry["props"]["level"])
        match = self._COLOR_TAG_PATTERN.search(raw)
        if match:
            color_map = {
                "red": "#ff5252", "green": "#00ff26", "magenta": "#ff00ff",
                "teal": "#008080", "yellow": "#ffeb3b"
            }
            color = color_map.get(match.group(1).lower(), color)
            raw = self._COLOR_TAG_PATTERN.sub('', raw).strip()
        return self._SYSTEM_TAG_PATTERN.sub('[System]', raw), color, False

    def _insert_entries(self, entries) -> None:
        """В конец документа. Подряд идущие записи одного цвета — одной
        вставкой (по одной на запись перестроение фильтра шло секундами).
        Одинаковые строки подряд (без учёта времени) — одной строкой «×N».
        Слева — разница во времени с предыдущей показанной записью."""
        doc = self.log_display.document()
        collapse = self.btn_collapse.isChecked()
        items = []  # [текст, цвет, жирный, id, ключ, разница, повторов]
        last = self._last_shown
        for entry in entries:
            text, color, bold = self._render(entry)
            key = message_key(text) if collapse and not bold else None
            if key is not None and last is not None and last["key"] == key and last["color"] == color:
                last["count"] += 1
                if items:
                    items[-1][6] = last["count"]
                else:
                    self._bump_last_count(last)
                continue
            when = entry_time(entry["raw"])
            delta = int(when - last["time"]) if when is not None and last and last["time"] is not None else 0
            if not 0 < delta <= MAX_DELTA_SEC:
                delta = 0
            items.append([text, color, bold, entry["id"], key, delta, 1])
            last = {"key": key, "color": color, "count": 1, "time": when if when is not None else (last or {}).get("time")}
        self._last_shown = last
        if not items:
            return

        cursor = QTextCursor(doc)
        cursor.movePosition(QTextCursor.End)
        first_block = doc.blockCount() - 1  # вставка начинается с последней (пустой) строки
        cursor.beginEditBlock()
        run, run_style = [], None

        def flush():
            if run:
                fmt = QTextCharFormat()
                fmt.setForeground(QColor(run_style[0]))
                if run_style[1]:
                    fmt.setFontWeight(QFont.Bold)
                cursor.insertText("\n".join(run) + "\n", fmt)

        for text, color, bold, entry_id, _key, _delta, count in items:
            if count > 1:
                text += f"  ×{count}"
            self._entry_sizes.append(text.count("\n") + 1)
            self._shown_ids.append(entry_id)
            if (color, bold) != run_style:
                flush()
                run, run_style = [], (color, bold)
            run.append(text)
        flush()
        cursor.endEditBlock()

        # разница во времени — в userState первой строки каждой записи (колонка слева)
        block_no = first_block
        for item, size in zip(items, list(self._entry_sizes)[-len(items):]):
            if item[5] > 0:
                doc.findBlockByNumber(block_no).setUserState(item[5])
            block_no += size

    def _bump_last_count(self, last: dict) -> None:
        """Ещё один повтор последней показанной строки: «×N» на её конце."""
        doc = self.log_display.document()
        block = doc.findBlockByNumber(doc.blockCount() - 2)
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.EndOfBlock)
        old = f"  ×{last['count'] - 1}"
        if last["count"] > 2 and block.text().endswith(old):
            cursor.movePosition(QTextCursor.Left, QTextCursor.KeepAnchor, len(old))
        else:
            cursor.movePosition(QTextCursor.Left)
            cursor.movePosition(QTextCursor.Right)
        fmt = cursor.charFormat()
        cursor.insertText(f"  ×{last['count']}", fmt)

    def _trim_display(self) -> None:
        excess = len(self._entry_sizes) - self.MAX_LOG_ENTRIES
        if excess <= 0:
            return
        blocks = 0
        for _ in range(excess):
            blocks += self._entry_sizes.popleft()
            self._shown_ids.popleft()
        doc = self.log_display.document()
        cursor = QTextCursor(doc)
        end_block = doc.findBlockByNumber(blocks)
        cursor.setPosition(end_block.position() if end_block.isValid() else doc.characterCount() - 1,
                           QTextCursor.KeepAnchor)
        cursor.removeSelectedText()

    def _matches(self, entry: dict) -> bool:
        if entry["props"].get("level") == "marker":
            return True  # маркеры шагов фильтр не скрывает
        return not self.filter_obj.filter_text or self.filter_obj.match(entry["props"])

    def _reapply_filter_to_history(self, *_):
        """Показать заново все сохранённые записи, подходящие под фильтр."""
        shown = [e for e in self._entries if self._matches(e)][-self.MAX_LOG_ENTRIES:]
        self.log_display.setUpdatesEnabled(False)
        try:
            self.log_display.clear()
            self._entry_sizes.clear()
            self._shown_ids.clear()
            self._last_shown = None
            self._insert_entries(shown)
        finally:
            self.log_display.setUpdatesEnabled(True)
        if self.chk_auto_scroll.isChecked():
            self._scroll_to_bottom()
        self._update_entry_count()

    def _scroll_to_bottom(self):
        sb = self.log_display.verticalScrollBar()
        self._is_programmatic_scroll = True
        sb.setValue(sb.maximum())
        self._is_programmatic_scroll = False

    def _clear_logs(self):
        self.log_display.clear()
        self._entry_sizes.clear()
        self._shown_ids.clear()
        self._entries.clear()
        self._last_shown = None
        self._markers = 0
        self._pause_from_id = self._next_id
        self._watch.recount([])
        self.side_panel.watch_page.refresh()
        self.side_panel.details.show_entry(None)
        self._update_entry_count()

    # ── Маркеры, панель, отслеживание, подсветка ────────────────────────

    def _add_marker(self):
        name, ok = QInputDialog.getText(self, "Маркер шага",
                                        "Название шага (можно оставить пустым):",
                                        text="")
        if ok:
            self.insert_marker(name)

    def insert_marker(self, name: str = ""):
        self._markers += 1
        name = name.strip() or f"Шаг {self._markers}"
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        raw = f"{stamp} [LogDog:Marker] {name}"
        props = self.filter_obj.extract_props(raw)
        props["level"] = "marker"
        self._on_blocks_processed([{"raw": raw, "props": props}])
        if self.chk_auto_scroll.isChecked():
            self._scroll_to_bottom()

    def _on_collapse_toggled(self, checked: bool):
        settings.set_flag("collapse_repeats", checked)
        self._reapply_filter_to_history()

    def _on_delta_toggled(self, checked: bool):
        settings.set_flag("show_time_delta", checked)
        self.log_display.set_gutter_visible(checked)

    def _on_panel_toggled(self, checked: bool):
        self.side_panel.setVisible(checked)
        if checked:
            width = self.width()
            self._splitter.setSizes([int(width * 0.68), int(width * 0.32)])
            self._on_log_cursor_moved()

    def _entry_by_id(self, entry_id: int):
        if not self._entries:
            return None
        index = entry_id - self._entries[0]["id"]
        return self._entries[index] if 0 <= index < len(self._entries) else None

    def _shown_index_at_block(self, block_no: int) -> int:
        total = 0
        for i, size in enumerate(self._entry_sizes):
            total += size
            if block_no < total:
                return i
        return -1

    def _on_log_cursor_moved(self):
        if not self.side_panel.isVisible():
            return
        index = self._shown_index_at_block(self.log_display.textCursor().blockNumber())
        entry = self._entry_by_id(self._shown_ids[index]) if index >= 0 else None
        level = entry["props"].get("level") if entry else ""
        self.side_panel.details.show_entry(entry, self._get_base_color(level) if entry else "")

    def _jump_to_entry(self, entry_id: int):
        entry = self._entry_by_id(entry_id)
        if entry is None:
            self.status_bar.showMessage("Эта запись уже вытеснена более новыми логами", 5000)
            return
        if not self._matches(entry):
            self.status_bar.showMessage("Запись скрыта текущим фильтром", 5000)
            return
        # повтор, схлопнутый в «×N», — показан строкой первого из них
        index = bisect.bisect_right(list(self._shown_ids), entry_id) - 1
        if index < 0:
            return
        block_no = sum(list(self._entry_sizes)[:index])
        block = self.log_display.document().findBlockByNumber(block_no)
        self.chk_auto_scroll.setChecked(False)
        cursor = QTextCursor(block)
        self.log_display.setTextCursor(cursor)
        self.log_display.centerCursor()
        self.log_display.setFocus()

    def _add_watch(self, text: str):
        self.btn_panel.setChecked(True)
        self.side_panel.setCurrentWidget(self.side_panel.watch_page)
        self.side_panel.watch_page.add_expression(f'"{text}"' if " " in text else text)

    def _on_watch_changed(self):
        settings.set_watch_rules(self._watch.to_settings())
        self._watch.recount(self._entries)
        self.side_panel.watch_page.refresh()

    def _add_highlight(self, text: str, color: str):
        self.side_panel.highlights_page.add_rule(text, color)

    def _on_highlights_changed(self):
        settings.set_highlights(self._highlights)
        self.log_display.set_highlights(self._highlights)

    # ── Открыть лог-файл ────────────────────────────────────────────────

    def _open_log_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Открыть лог", "",
                                              "Логи (*.log *.txt *.ips);;Все файлы (*)")
        if not path:
            return
        if self._is_connected:
            answer = QMessageBox.question(self, "Открыть лог-файл",
                                          "Сбор логов будет остановлен, а текущие логи заменятся логами из файла. Продолжить?")
            if answer != QMessageBox.Yes:
                return
            self._disconnect()
        self._clear_logs()
        self._file_loader = LogFileLoader(path, self.filter_obj)
        self._file_loader.blocks_ready.connect(self._on_incoming_blocks)
        self._file_loader.finished_loading.connect(
            lambda total: self.status_bar.showMessage(
                f"Открыт файл {Path(path).name}: записей {total:,}".replace(",", " ")
                + (" (показаны последние 100 000)" if total > self.MAX_STORED_ENTRIES else "")))
        self._file_loader.failed.connect(lambda msg: self.status_bar.showMessage(msg, 10000))
        self.status_bar.showMessage(f"Открываю {Path(path).name}…")
        self._file_loader.start()

    # ── Обучение ────────────────────────────────────────────────────────

    def start_tour(self, autoplay: bool = False):
        """Обучение на демо-логах. Настоящие логи, фильтр, отслеживание,
        подсветка и переключатели откладываются и возвращаются после."""
        if self._tour is not None:
            return
        from gui.tour import Tour
        from gui.tour_steps import build_steps, demo_feed_timer
        self._tour_state = {
            "entries": list(self._entries), "next_id": self._next_id, "markers": self._markers,
            "filter": self.filter_input.text(), "watch": self._watch.to_settings(),
            "highlights": [list(h) for h in self._highlights],
            "collapse": self.btn_collapse.isChecked(), "delta": self.btn_delta.isChecked(),
            "panel": self.btn_panel.isChecked(), "pause": self.btn_pause.isChecked(),
            "autoscroll": self.chk_auto_scroll.isChecked(), "proc_counts": Counter(self._proc_counts),
            "held": [],
        }
        self.btn_pause.setChecked(False)
        self.filter_input.clear()
        self._apply_filter(remember=False)
        self._watch.rules.clear()
        self._highlights.clear()
        self.log_display.set_highlights([])
        self._clear_logs()
        self._demo_timer = demo_feed_timer(self)
        self._tour = Tour(self, build_steps(self), autoplay=autoplay)
        self._tour.finished.connect(self._end_tour)
        self._tour.start()

    def _end_tour(self):
        state, self._tour_state = self._tour_state, None
        self._tour = None
        self._demo_timer.stop()
        self.find_bar.hide()
        self.filter_input.hide_popup()
        if self.tools_window is not None:
            self.tools_window.hide()
        for toast in list(self.crash_alerts.toasts):
            if toast.report.path.endswith("-демо.ips"):
                toast.dismiss()
        self.btn_collapse.setChecked(state["collapse"])
        self.btn_delta.setChecked(state["delta"])
        self.btn_panel.setChecked(state["panel"])
        self.chk_auto_scroll.setChecked(state["autoscroll"])
        self._watch.rules[:] = WatchList(state["watch"]).rules
        self._highlights[:] = state["highlights"]
        settings.set_watch_rules(state["watch"])
        settings.set_highlights(state["highlights"])
        self.log_display.set_highlights(self._highlights)
        self.side_panel.watch_page.refresh()
        self.side_panel.highlights_page.refresh()
        self._proc_counts = state["proc_counts"]
        self._entries.clear()
        self._entries.extend(state["entries"])
        self._next_id, self._markers = state["next_id"], state["markers"]
        self.filter_input.setText(state["filter"])
        self._apply_filter(remember=False)
        self._reapply_filter_to_history()
        self._watch.recount(self._entries)
        if state["held"]:
            self._on_blocks_processed(state["held"])
        self.btn_pause.setChecked(state["pause"])
        self.status_bar.showMessage("Обучение закончено — ваши логи и настройки на месте", 6000)

    # ── Unity: игры в сети ──────────────────────────────────────────────

    def _start_discovery(self):
        if self._discovery is None and not self._is_connected:
            self._discovery = GameDiscovery()
            self._discovery.games_changed.connect(self._on_games_changed)
            self._discovery.start()
        self._update_connect_button()

    def _stop_discovery(self):
        if self._discovery is not None:
            try:
                self._discovery.games_changed.disconnect()
            except RuntimeError:
                pass
            self._discovery.stop()
            self._discovery.quit()
            self._discovery.wait(2000)
            if self._discovery.isRunning():
                self._discovery.terminate()
                self._discovery.wait()
            self._discovery = None
        self._games = []
        self._update_connect_button()

    # ── Unity: откуда читать ────────────────────────────────────────────

    def _unity_target(self) -> dict:
        return self.unity_combo.currentData() or {}

    def _unity_kind(self) -> str:
        return self._unity_target().get("kind", "")

    def _unity_target_string(self):
        """«usb:<серийный>», «IP», «IP:порт» — или None, если ничего не выбрано."""
        t = self._unity_target()
        if t.get("kind") == "usb":
            return USB_PREFIX + t["serial"]
        if t.get("kind") in ("wifi", "last"):
            return t["ip"]
        if t.get("kind") == "manual":
            return self.ip_input.text().strip() or None
        return None

    @staticmethod
    def _target_key(t: dict) -> str:
        return USB_PREFIX + t["serial"] if t.get("kind") == "usb" else t.get("ip", t.get("kind", ""))

    @staticmethod
    def _game_title(game: dict) -> str:
        """Подпись в списке: «iPhone (Семен) · по USB — MyGame запущена»."""
        if game.get("via") == "usb":
            title = f"{game.get('device') or 'iPhone'}  ·  по USB"
            if game.get("port"):
                title += f"  —  {game['project'] or 'Unity-игра'} запущена"
            return title
        parts = [game["project"] or "Unity-игра"]
        if game["platform"]:
            parts.append(game["platform"])
        parts.append(game["ip"])
        return "  ·  ".join(parts)

    def _rebuild_unity_combo(self):
        """Список «откуда читать»: iPhone по USB (и запущенные на них игры),
        игры в Wi-Fi, последний IP, ввод IP вручную. Выбор сохраняется."""
        current = self._target_key(self._unity_target()) if self._unity_target() else settings.last_unity_target()
        items = []
        for game in self._games:
            kind = "usb" if game.get("via") == "usb" else "wifi"
            items.append(({**game, "kind": kind}, self._game_title(game), "phone" if kind == "usb" else "gamepad"))
        last_ip = settings.last_unity_ip()
        if last_ip and last_ip not in {g["ip"] for g in self._games if g.get("via") != "usb"}:
            items.append(({"kind": "last", "ip": last_ip}, f"{last_ip}  ·  по Wi-Fi (прошлый раз)", "gamepad"))
        self.unity_combo.blockSignals(True)
        self.unity_combo.clear()
        if not self._games:
            self.unity_combo.addItem(icons.icon("search"), "Ищу iPhone по USB и игры в Wi-Fi…", None)
        for data, title, icon_name in items:
            self.unity_combo.addItem(icons.icon(icon_name), title, data)
        self.unity_combo.insertSeparator(self.unity_combo.count())
        self.unity_combo.addItem(icons.icon("code"), "Ввести IP вручную…", {"kind": "manual"})
        index = next((i for i in range(self.unity_combo.count())
                      if self.unity_combo.itemData(i) and self._target_key(self.unity_combo.itemData(i)) == current), -1)
        if index < 0 and self._unity_kind() != "manual":
            index = 0
        if index >= 0:
            self.unity_combo.setCurrentIndex(index)
        self.unity_combo.blockSignals(False)
        self._maybe_auto_connect()

    def _maybe_auto_connect(self):
        """Как в режиме iOS: iPhone по USB (или прошлый выбор) — подключаемся
        сами и ждём игру, чтобы поймать логи с самого запуска."""
        if self._is_connected or self._unity_stopped_by_user or self.mode_combo.currentData() != "unity":
            return
        t = self._unity_target()
        remembered = t and self._target_key(t) == settings.last_unity_target()
        single_usb = [g for g in self._games if g.get("via") == "usb"]
        if t.get("kind") == "usb" and (remembered or len(single_usb) == 1):
            self._connect(auto=True)

    def _on_unity_target_chosen(self, _index: int):
        kind = self._unity_kind()
        self.ip_input.setVisible(kind == "manual")
        if kind == "manual":
            self.ip_input.setFocus()
            self.ip_input.selectAll()
            return
        if not kind:
            return
        self._connect_unity(auto=False)

    def _connect_unity(self, auto: bool):
        if self._is_connected:
            self._disconnect()
        self._connect(auto=auto)

    def _unity_hint(self):
        self.status_bar.showMessage("Выберите, откуда читать логи Unity: iPhone по USB, игру в Wi-Fi или IP вручную",
                                    8000)

    def _update_connect_button(self):
        if self._is_connected:
            self.connect_btn.setIcon(icons.icon("stop"))
            self.connect_btn.setToolTip("Отключиться")
        else:
            self.connect_btn.setIcon(icons.icon("play"))
            self.connect_btn.setToolTip("Подключиться и ждать игру")

    def _on_games_changed(self, games: list):
        known = {(g.get("via"), g.get("serial") or g["ip"], g.get("port")) for g in self._games}
        new = [g for g in games if (g.get("via"), g.get("serial") or g["ip"], g.get("port")) not in known]
        self._games = games
        self._rebuild_unity_combo()
        running = [g for g in new if g.get("port")]
        if running and not self._is_connected:
            self.status_bar.showMessage(f"Найдена игра: {self._game_title(running[0])}", 8000)

    def _choose_game(self, game: dict):
        """Выбрать цель в списке (по данным из поиска) и подключиться."""
        key = self._target_key({**game, "kind": "usb" if game.get("via") == "usb" else "wifi"})
        for i in range(self.unity_combo.count()):
            data = self.unity_combo.itemData(i)
            if data and self._target_key(data) == key:
                self.unity_combo.setCurrentIndex(i)
                break
        self._connect_unity(auto=False)

    def _show_settings(self):
        SettingsDialog(self).exec()

    def _show_help(self):
        HelpDialog(self).exec()

    def _on_incoming_blocks(self, blocks: list):
        """Логи от транспорта и из файла. Во время обучения — придержать:
        на экране демо-логи, а настоящие добавятся после него."""
        if self._tour_state is not None:
            self._tour_state["held"].extend(blocks)
            return
        self._on_blocks_processed(blocks)

    def _on_blocks_processed(self, blocks: list):
        for block in blocks:
            block["id"] = self._next_id
            self._next_id += 1
            proc = block["props"].get("proc")
            if proc:
                # в подсказках proc: — и «mygame», и «mygame(unityframework)»
                self._proc_counts[proc.split("(")[0]] += 1
                if "(" in proc:
                    self._proc_counts[proc] += 1
        self._entries.extend(blocks)
        if self._watch.rules and self._watch.feed(blocks) and self.side_panel.isVisible():
            self._watch_refresh.start()
        if self.btn_pause.isChecked():
            # Пауза замораживает экран, но логи не теряются: покажутся после неё.
            self._update_entry_count()
            return
        self._insert_entries([b for b in blocks if self._matches(b)])
        if self.chk_auto_scroll.isChecked():
            self._scroll_to_bottom()
        self._trim_display()
        self._update_entry_count()

    def apply_font_size(self):
        """Apply font size setting to log display."""
        self.log_display.setFont(self._log_font())

    def _get_base_color(self, level: str) -> str:
        if level not in ("error", "warn", "debug", "system"):
            level = "info"
        return settings.custom_color(f"color_{level}") or theme.log_color(level)

    def repaint_all_logs(self, *_):
        """Перекрасить показанные логи (смена темы или цветов) с сохранением прокрутки."""
        sb = self.log_display.verticalScrollBar()
        position = sb.value()
        self._reapply_filter_to_history()
        if not self.chk_auto_scroll.isChecked():
            sb.setValue(min(position, sb.maximum()))

    def _on_auto_scroll_toggled(self, state):
        """Scroll to bottom immediately when auto-scroll is enabled."""
        if state == Qt.Checked:
            sb = self.log_display.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _on_scroll_user_moved(self, value):
        """Disable auto-scroll if user scrolls up manually."""
        if getattr(self, "_is_programmatic_scroll", False):
            return
        sb = self.log_display.verticalScrollBar()
        if value < sb.maximum() - 2:
            self.chk_auto_scroll.setChecked(False)

    def closeEvent(self, event: QCloseEvent):
        """Clean up all active QThread loops robustly to prevent SIGABRT."""
        logger.info("Application closing. Halting all background threads...")
        self._disconnect()
        self.crash_alerts.shutdown()

        if self.tools_window is not None:
            self.tools_window.close()
            self.tools_window = None

        self._stop_discovery()
        threads_to_stop = [self.processor, self.poller_thread, self.updater_thread, self._file_loader]
        for t in threads_to_stop:
            if t and t.isRunning():
                t.stop()
                t.quit()
                t.wait(1000)
                if t.isRunning():
                    t.terminate()
                    t.wait()
                    
        event.accept()
