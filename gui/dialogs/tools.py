from pathlib import Path

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QSizePolicy,
    QPushButton, QLabel, QMessageBox, QFileDialog,
)

from core import ipa_info
from transports.ipa_installer import IpaInstaller, HAS_PYMOBILEDEVICE3
from transports.crash_reporter import CrashListWorker, CrashPuller
from transports.developer_mode import DeveloperModeWorker
from transports.device_info import DeviceInfoWorker
from transports.app_list import AppsListWorker
from transports import device_tools
from gui import icons, theme
from gui.theme import theme_signals
from gui.dialogs.crash_reports import CrashReportDialog
from gui.dialogs.device_info import DeviceInfoDialog
from gui.dialogs.app_list import AppListDialog
from gui.dialogs.device_tasks import TaskRunner
from gui.dialogs.ipa_check import IpaCheckDialog
from gui.dialogs.language import LanguageDialog
from gui.dialogs.profiles import configuration_dialog, provisioning_dialog
from utils.logger import logger


class ToolsWindow(QDialog):
    """Non-modal window with auxiliary device tools (IPA install, crash reports).

    More tools can be added later by appending an entry to ``_TOOLS``.
    """

    _TOOLS = [
        ("btn_device_info", "info", "Информация об устройстве", "Модель, iOS, UDID, батарея, память", "_show_device_info"),
        ("btn_app_list", "apps", "Список приложений", "Установленные приложения и их версии", "_show_app_list"),
        ("btn_install_ipa", "package", "Установить .ipa", "Поставить сборку на устройство", "_install_ipa"),
        ("btn_crash_reports", "bug", "Краш-отчёты", "Скачать .ips и читаемый .log", "_fetch_crash_reports"),
        ("btn_developer_mode", "code", "Включить Developer Mode", "Без Xcode и Finder", "_enable_developer_mode"),
        ("btn_language", "globe", "Язык и регион", "Сменить язык и регион iPhone", "_change_language"),
        ("btn_power", "power", "Перезагрузить / выключить", "Перезагрузка без кнопок iPhone", "_power"),
        ("btn_prov_profiles", "shield", "Профили подготовки", "Кто подписал сборки и до какого числа", "_show_provisioning"),
        ("btn_config_profiles", "profile", "Конфигурационные профили", "Сертификат прокси, VPN, MDM", "_show_configuration"),
        ("btn_pairing", "link", "Сбросить сопряжение", "Если iPhone виден, но не подключается", "_reset_pairing"),
    ]
    # Простые действия через TaskRunner: доступны, пока подключён iPhone и
    # не идёт другое такое действие.
    _TASK_TOOLS = ("btn_language", "btn_power", "btn_prov_profiles", "btn_config_profiles", "btn_pairing")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Инструменты")
        self.setWindowFlags(Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setAcceptDrops(True)  # .ipa можно перетащить на окно
        self._tasks = TaskRunner(self)

        self.ipa_installer = None
        self.crash_list_worker = None
        self.crash_puller = None
        self.developer_mode_worker = None
        self.device_info_worker = None
        self.apps_list_worker = None

        self._init_ui()
        self.layout().setSizeConstraint(QVBoxLayout.SetFixedSize)
        self.refresh_device_state()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)

        title = QLabel("Инструменты iOS")
        title.setProperty("role", "title")
        layout.addWidget(title)
        self.device_hint = QLabel()
        self.device_hint.setProperty("role", "muted")
        layout.addWidget(self.device_hint)
        layout.addSpacing(4)

        # Две колонки: десяти карточкам одной колонкой не хватило бы высоты экрана.
        self._card_icons = {}
        grid = QGridLayout()
        grid.setSpacing(8)
        for i, (attr, icon_name, title_text, description, handler) in enumerate(self._TOOLS):
            btn = self._make_tool_btn(attr, icon_name, title_text, description)
            btn.clicked.connect(getattr(self, handler))
            setattr(self, attr, btn)
            grid.addWidget(btn, i // 2, i % 2)
        layout.addLayout(grid)

        layout.addStretch()

        btn_row = QHBoxLayout()
        self.status = QLabel("Файл .ipa можно перетащить на это окно")
        self.status.setProperty("role", "muted")
        btn_row.addWidget(self.status, 1)
        close_btn = QPushButton("Закрыть")
        close_btn.setMinimumWidth(90)
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._apply_icons()
        theme_signals.theme_changed.connect(self._apply_icons)

    def event(self, event):
        if event.type() == QEvent.WindowBlocked:
            theme.clear_stale_hover(self)  # карточки открывают окна — не оставлять их подсвеченными
        return super().event(event)

    def _make_tool_btn(self, attr: str, icon_name: str, title: str, description: str) -> QPushButton:
        btn = QPushButton()
        btn.setProperty("variant", "card")
        btn.setToolTip(description)
        btn.setFixedHeight(60)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        btn.setCursor(Qt.PointingHandCursor)

        row = QHBoxLayout(btn)
        row.setContentsMargins(12, 8, 14, 8)
        row.setSpacing(12)

        icon_lbl = QLabel()
        icon_lbl.setProperty("role", "cardIcon")
        icon_lbl.setFixedSize(40, 40)
        icon_lbl.setAlignment(Qt.AlignCenter)
        icon_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._card_icons[attr] = (icon_lbl, icon_name)

        text = QVBoxLayout()
        text.setSpacing(1)
        title_lbl = QLabel(title)
        title_lbl.setStyleSheet("font-weight: 600;")
        desc_lbl = QLabel(description)
        desc_lbl.setProperty("role", "muted")
        for lbl in (title_lbl, desc_lbl):
            lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
            text.addWidget(lbl)

        row.addWidget(icon_lbl)
        row.addLayout(text, 1)

        # QPushButton.sizeHint() doesn't account for a manually-installed child
        # layout, so the fixed-size window would otherwise size itself too
        # narrow and clip long titles - size explicitly from the text width.
        text_width = max(title_lbl.fontMetrics().horizontalAdvance(t) for t in (title, description))
        btn.setMinimumWidth(max(320, 12 + 40 + 12 + text_width + 14 + 24))
        return btn

    def _apply_icons(self, *_):
        for attr, (label, icon_name) in self._card_icons.items():
            btn = getattr(self, attr, None)
            enabled = btn is None or btn.isEnabled()
            color = theme.tokens()["accent" if enabled else "faint"]
            label.setPixmap(icons.pixmap(icon_name, color, 22))

    def _device_serial(self) -> str:
        mw = self.parentWidget()
        if mw and hasattr(mw, "current_device_serial"):
            return mw.current_device_serial() or ""
        return ""

    def _ios_device_available(self) -> bool:
        mw = self.parentWidget()
        return bool(mw and getattr(mw, "_ios_device_available", False))

    def refresh_device_state(self):
        """Enable/disable tool tiles based on current device availability."""
        has_device = self._ios_device_available() and bool(self._device_serial())
        self.btn_install_ipa.setEnabled(has_device and HAS_PYMOBILEDEVICE3 and not self.ipa_installer)
        self.btn_device_info.setEnabled(has_device and HAS_PYMOBILEDEVICE3 and not self.device_info_worker)
        self.btn_app_list.setEnabled(has_device and HAS_PYMOBILEDEVICE3 and not self.apps_list_worker)
        self.btn_developer_mode.setEnabled(has_device and HAS_PYMOBILEDEVICE3 and not self.developer_mode_worker)
        busy = bool(self.crash_list_worker or self.crash_puller)
        self.btn_crash_reports.setEnabled(has_device and HAS_PYMOBILEDEVICE3 and not busy)
        task_busy = self._tasks.busy()
        for attr in self._TASK_TOOLS:
            getattr(self, attr).setEnabled(has_device and HAS_PYMOBILEDEVICE3 and not task_busy)
        if not HAS_PYMOBILEDEVICE3:
            self.device_hint.setText("Недоступно: не установлен pymobiledevice3")
        elif has_device:
            mw = self.parentWidget()
            name = mw.device_combo.currentText() if mw and hasattr(mw, "device_combo") else ""
            self.device_hint.setText(f"Устройство: {name}" if name else "Устройство подключено")
        else:
            self.device_hint.setText("Подключите iPhone по USB и выберите его в режиме iOS Syslog")
        self._apply_icons()

    # ----------------------------------------------------- Device tools ----

    def _show_device_info(self):
        if self.device_info_worker:
            return
        if not HAS_PYMOBILEDEVICE3:
            QMessageBox.warning(self, "Ошибка", "pymobiledevice3 не установлен")
            return
        serial = self._device_serial()
        if not serial:
            return

        self.device_info_worker = DeviceInfoWorker(serial, parent=self)
        self.device_info_worker.result_ready.connect(self._on_device_info_ready)
        self.device_info_worker.failed.connect(self._on_device_info_failed)
        self.device_info_worker.start()
        self.btn_device_info.setEnabled(False)

    def _on_device_info_ready(self, info: dict):
        self._cleanup_device_info_worker()
        DeviceInfoDialog(info, self).exec()

    def _on_device_info_failed(self, err: str):
        self._cleanup_device_info_worker()
        QMessageBox.critical(self, "Ошибка", err)

    def _cleanup_device_info_worker(self):
        if self.device_info_worker:
            try:
                self.device_info_worker.result_ready.disconnect()
                self.device_info_worker.failed.disconnect()
            except RuntimeError:
                pass
            self.device_info_worker.stop()
            self.device_info_worker.quit()
            self.device_info_worker.wait(2000)
            if self.device_info_worker.isRunning():
                self.device_info_worker.terminate()
                self.device_info_worker.wait()
            self.device_info_worker = None
        self.refresh_device_state()

    def _show_app_list(self):
        if self.apps_list_worker:
            return
        if not HAS_PYMOBILEDEVICE3:
            QMessageBox.warning(self, "Ошибка", "pymobiledevice3 не установлен")
            return
        serial = self._device_serial()
        if not serial:
            return

        self.apps_list_worker = AppsListWorker(serial, parent=self)
        self.apps_list_worker.apps_ready.connect(self._on_apps_list_ready)
        self.apps_list_worker.failed.connect(self._on_apps_list_failed)
        self.apps_list_worker.start()
        self.btn_app_list.setEnabled(False)

    def _on_apps_list_ready(self, items: list):
        serial = self._device_serial()
        self._cleanup_apps_list_worker()
        AppListDialog(items, self, serial=serial).exec()

    def _on_apps_list_failed(self, err: str):
        self._cleanup_apps_list_worker()
        QMessageBox.critical(self, "Ошибка", err)

    def _cleanup_apps_list_worker(self):
        if self.apps_list_worker:
            try:
                self.apps_list_worker.apps_ready.disconnect()
                self.apps_list_worker.failed.disconnect()
            except RuntimeError:
                pass
            self.apps_list_worker.stop()
            self.apps_list_worker.quit()
            self.apps_list_worker.wait(2000)
            if self.apps_list_worker.isRunning():
                self.apps_list_worker.terminate()
                self.apps_list_worker.wait()
            self.apps_list_worker = None
        self.refresh_device_state()

    # ------------------------------------------------------------------ IPA ---

    def _install_ipa(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите .ipa файл", "", "IPA файлы (*.ipa);;Все файлы (*)"
        )
        if path:
            self._check_ipa(path)

    def dragEnterEvent(self, event):
        if self._dropped_ipa(event) and self.btn_install_ipa.isEnabled():
            event.acceptProposedAction()

    def dropEvent(self, event):
        path = self._dropped_ipa(event)
        if path and self.btn_install_ipa.isEnabled():
            event.acceptProposedAction()
            self._check_ipa(path)

    @staticmethod
    def _dropped_ipa(event) -> str:
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        files = [u.toLocalFile() for u in urls if u.isLocalFile()]
        return files[0] if len(files) == 1 and files[0].lower().endswith(".ipa") else ""

    def _check_ipa(self, path: str):
        """Сначала — что за сборка и встанет ли она (версию iOS спросим у
        устройства), потом по кнопке — установка."""
        if not Path(path).is_file():
            QMessageBox.warning(self, "Ошибка", "Файл не найден")
            return
        serial = self._device_serial()
        if not serial or self.ipa_installer:
            return
        try:
            info = ipa_info.read_ipa(path)
        except ipa_info.IpaError as exc:
            QMessageBox.critical(self, "Не .ipa", str(exc))
            return
        self.status.setText(f"Проверяю {Path(path).name}…")
        self._tasks.run(serial, device_tools.product_version,
                        lambda version: self._confirm_ipa(info, serial, version or ""),
                        on_failed=lambda _msg: self._confirm_ipa(info, serial, ""),
                        busy=(self.btn_install_ipa,))

    def _confirm_ipa(self, info, serial: str, ios_version: str):
        self.status.setText("")
        warnings = ipa_info.check(info, udid=serial, ios_version=ios_version)
        if IpaCheckDialog(info, warnings, ios_version, self).exec() != QDialog.Accepted:
            self.refresh_device_state()
            return
        self._start_ipa_install(serial, str(info.path))

    def _start_ipa_install(self, serial: str, path: str):
        self.ipa_installer = IpaInstaller(serial, path, parent=self)
        self.ipa_installer.install_completed.connect(self._on_install_completed)
        self.ipa_installer.install_failed.connect(self._on_install_failed)
        self.ipa_installer.start()

        self.btn_install_ipa.setEnabled(False)

    def _on_install_completed(self, msg: str):
        QMessageBox.information(self, "Установка завершена", msg)
        self._cleanup_ipa_installer()

    def _on_install_failed(self, err: str):
        QMessageBox.critical(self, "Ошибка установки", err)
        self._cleanup_ipa_installer()

    def _cleanup_ipa_installer(self):
        if self.ipa_installer:
            try:
                self.ipa_installer.install_completed.disconnect()
                self.ipa_installer.install_failed.disconnect()
            except RuntimeError:
                pass
            self.ipa_installer.stop()
            self.ipa_installer.quit()
            self.ipa_installer.wait(2000)
            if self.ipa_installer.isRunning():
                self.ipa_installer.terminate()
                self.ipa_installer.wait()
            self.ipa_installer = None
        self.refresh_device_state()

    # ----------------------------------------------------------- Crashes ----

    def _fetch_crash_reports(self):
        if self.crash_list_worker or self.crash_puller:
            return
        serial = self._device_serial()
        if not serial:
            return
        if not HAS_PYMOBILEDEVICE3:
            QMessageBox.warning(self, "Ошибка", "pymobiledevice3 не установлен")
            return

        self.btn_crash_reports.setEnabled(False)

        self.crash_list_worker = CrashListWorker(serial, parent=self)
        self.crash_list_worker.listing_ready.connect(self._on_crashes_listed)
        self.crash_list_worker.listing_failed.connect(self._on_crashes_list_failed)
        self.crash_list_worker.start()

    def _on_crashes_listed(self, items: list):
        self._cleanup_crash_list_worker()

        if not items:
            QMessageBox.information(self, "Краш-отчёты", "Краш-отчётов на устройстве не найдено")
            return

        dlg = CrashReportDialog(items, self)
        if dlg.exec() != QDialog.Accepted:
            self.refresh_device_state()
            return

        selected = dlg.selected_items()
        if not selected:
            self.refresh_device_state()
            return

        out_dir = QFileDialog.getExistingDirectory(self, "Куда сохранить краш-отчёты", "")
        if not out_dir:
            self.refresh_device_state()
            return

        serial = self._device_serial()
        if not serial:
            self.refresh_device_state()
            return

        self.crash_puller = CrashPuller(serial, selected, out_dir, parent=self)
        self.crash_puller.done.connect(self._on_crash_pull_done)
        self.crash_puller.failed.connect(self._on_crash_pull_failed)
        self.crash_puller.start()

        self.btn_crash_reports.setEnabled(False)

    def _on_crashes_list_failed(self, err: str):
        self._cleanup_crash_list_worker()
        QMessageBox.critical(self, "Ошибка", err)
        self.refresh_device_state()

    def _cleanup_crash_list_worker(self):
        if self.crash_list_worker:
            try:
                self.crash_list_worker.listing_ready.disconnect()
                self.crash_list_worker.listing_failed.disconnect()
            except RuntimeError:
                pass
            self.crash_list_worker.stop()
            self.crash_list_worker.quit()
            self.crash_list_worker.wait(2000)
            if self.crash_list_worker.isRunning():
                self.crash_list_worker.terminate()
                self.crash_list_worker.wait()
            self.crash_list_worker = None
        self.refresh_device_state()

    def _on_crash_pull_done(self, msg: str):
        self._cleanup_crash_puller()
        QMessageBox.information(self, "Выгрузка завершена", msg)

    def _on_crash_pull_failed(self, err: str):
        self._cleanup_crash_puller()
        QMessageBox.critical(self, "Ошибка выгрузки", err)

    def _cleanup_crash_puller(self):
        if self.crash_puller:
            try:
                self.crash_puller.done.disconnect()
                self.crash_puller.failed.disconnect()
            except RuntimeError:
                pass
            self.crash_puller.stop()
            self.crash_puller.quit()
            self.crash_puller.wait(2000)
            if self.crash_puller.isRunning():
                self.crash_puller.terminate()
                self.crash_puller.wait()
            self.crash_puller = None
        self.refresh_device_state()

    # ------------------------------------------------- Developer Mode ----

    def _enable_developer_mode(self):
        if self.developer_mode_worker:
            return
        if not HAS_PYMOBILEDEVICE3:
            QMessageBox.warning(self, "Ошибка", "pymobiledevice3 не установлен")
            return
        serial = self._device_serial()
        if not serial:
            return

        self.developer_mode_worker = DeveloperModeWorker(serial, parent=self)
        self.developer_mode_worker.completed.connect(self._on_devmode_done)
        self.developer_mode_worker.failed.connect(self._on_devmode_failed)
        self.developer_mode_worker.start()

        self.btn_developer_mode.setEnabled(False)

    def _on_devmode_done(self, msg: str):
        self._cleanup_developer_mode_worker()
        QMessageBox.information(self, "Developer Mode", msg)

    def _on_devmode_failed(self, err: str):
        self._cleanup_developer_mode_worker()
        QMessageBox.critical(self, "Ошибка Developer Mode", err)

    def _cleanup_developer_mode_worker(self):
        if self.developer_mode_worker:
            try:
                self.developer_mode_worker.completed.disconnect()
                self.developer_mode_worker.failed.disconnect()
            except RuntimeError:
                pass
            self.developer_mode_worker.stop()
            self.developer_mode_worker.quit()
            self.developer_mode_worker.wait(2000)
            if self.developer_mode_worker.isRunning():
                self.developer_mode_worker.terminate()
                self.developer_mode_worker.wait()
            self.developer_mode_worker = None
        self.refresh_device_state()

    # ------------------------------------------- Простые действия (TaskRunner) ----

    def _run_task(self, job, on_done, status: str, error_prefix: str, connect: bool = True):
        serial = self._device_serial()
        if not serial or self._tasks.busy():
            return
        self.status.setText(status)

        def done(result):
            self.status.setText("")
            on_done(result)
            self.refresh_device_state()

        def failed(message):
            self.status.setText("")
            QMessageBox.critical(self, "Не получилось", message)
            self.refresh_device_state()

        self._tasks.run(serial, job, done, on_failed=failed, error_prefix=error_prefix, connect=connect)
        self.refresh_device_state()

    def _change_language(self):
        self._run_task(device_tools.read_international, self._on_intl_read,
                       "Читаю язык и регион…", "Не удалось прочитать язык")

    def _on_intl_read(self, intl: dict):
        dlg = LanguageDialog(intl, self)
        if dlg.exec() != QDialog.Accepted:
            return
        language, locale = dlg.selection()
        if (language, locale) == (intl.get("language"), intl.get("locale")):
            return
        self._run_task(lambda ld: device_tools.apply_international(ld, language, locale),
                       lambda _r: QMessageBox.information(
                           self, "Язык и регион",
                           f"Установлено: {language}, {locale}.\n\nЕсли интерфейс iPhone не сменился — "
                           "перезагрузите его карточкой «Перезагрузить / выключить»."),
                       "Меняю язык и регион…", "Не удалось сменить язык")

    def _power(self):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("Перезагрузить / выключить")
        box.setText("Что сделать с iPhone?")
        box.setInformativeText("Сбор логов прервётся и продолжится сам, когда iPhone загрузится.")
        reboot = box.addButton("Перезагрузить", QMessageBox.AcceptRole)
        off = box.addButton("Выключить", QMessageBox.DestructiveRole)
        box.addButton("Отмена", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is reboot:
            self._run_task(device_tools.reboot, lambda _r: self.status.setText("iPhone перезагружается…"),
                           "Перезагружаю…", "Не удалось перезагрузить")
        elif box.clickedButton() is off:
            self._run_task(device_tools.shutdown, lambda _r: self.status.setText("iPhone выключается…"),
                           "Выключаю…", "Не удалось выключить")

    def _show_provisioning(self):
        self._run_task(device_tools.provisioning_profiles,
                       lambda profiles: provisioning_dialog(profiles, self).exec(),
                       "Читаю профили подготовки…", "Не удалось прочитать профили")

    def _show_configuration(self):
        self._run_task(device_tools.configuration_profiles,
                       lambda profiles: configuration_dialog(profiles, self).exec(),
                       "Читаю конфигурационные профили…", "Не удалось прочитать профили")

    def _reset_pairing(self):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Сбросить сопряжение")
        box.setText("Сбросить сопряжение с этим iPhone и сопрячь заново?")
        box.setInformativeText(
            "Помогает, когда iPhone виден в списке, но логи и инструменты не подключаются.\n\n"
            "Разблокируйте iPhone: на нём появится «Доверять этому компьютеру?» — нажмите "
            "«Доверять» и введите код-пароль. На это будет 2 минуты.")
        ok = box.addButton("Сбросить", QMessageBox.DestructiveRole)
        box.addButton("Отмена", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not ok:
            return
        self._run_task(device_tools.reset_pairing,
                       lambda _r: QMessageBox.information(self, "Сопряжение", "Готово: iPhone снова доверяет "
                                                                              "этому компьютеру."),
                       "Жду «Доверять» на iPhone…", "Не удалось сопрячь", connect=False)

    # ---------------------------------------------------------- Lifetime ----

    def closeEvent(self, event):
        logger.info("Tools window closing. Halting auxiliary threads...")
        self._tasks.stop_all()
        self._cleanup_ipa_installer()
        self._cleanup_crash_list_worker()
        self._cleanup_crash_puller()
        self._cleanup_device_info_worker()
        self._cleanup_apps_list_worker()
        self._cleanup_developer_mode_worker()
        event.accept()