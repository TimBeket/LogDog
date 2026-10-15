"""Диалог «Доступно обновление» — полуавтоматическая установка.

«Скачать обновление» качает файл для этой ОС с GitHub Releases
(core.updater.UpdateDownloadThread) и сверяет SHA-256; «Установить и
перезапустить» подменяет программу (core.update_install) — только по кнопке,
чтобы пользователь сам выбрал момент перезапуска. Если установка из программы
невозможна (запуск из исходников, нет файла для этой ОС) — остаётся кнопка
«Страница релиза» для ручной установки.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTextBrowser, QVBoxLayout,
)

from core import update_install
from core.updater import UpdateDownloadThread, UpdateInfo
from core.version import VERSION
from gui import icons, theme
from utils.helpers import resource_path
from utils.logger import logger

# вид строки состояния: иконка и ключ цвета темы
_STATUS_KINDS = {"ok": ("check", "accent"), "warn": ("alert", "warn"),
                 "error": ("alert", "danger"), "": ("info", "muted"), "busy": ("download", "accent")}


class _InstallThread(QThread):
    """Проверка суммы и распаковка (сотни МБ) — не в потоке окна, иначе оно
    замирает и Windows помечает его «Не отвечает»."""
    installed = Signal(str)
    failed = Signal(str)

    def __init__(self, archive: Path, target, sha256: str, parent=None):
        super().__init__(parent)
        self.archive, self.target, self.sha256 = archive, target, sha256

    def run(self):
        try:
            self.installed.emit(update_install.install(self.archive, self.target,
                                                       expected_sha256=self.sha256))
        except (update_install.UpdateError, OSError) as exc:
            logger.warning("Update install failed: %s", exc)
            self.failed.emit(str(exc))


class UpdateDialog(QDialog):
    def __init__(self, info: UpdateInfo, parent=None):
        super().__init__(parent)
        self.info = info
        #: True — программа должна закрыться (фоновый процесс подмены или новый
        #: AppImage уже запущены), MainWindow закрывается после exec()
        self.quit_requested = False
        self._target: update_install.InstallTarget | None = None
        self._downloader: UpdateDownloadThread | None = None
        self._installer: _InstallThread | None = None
        self._downloaded: Path | None = None

        self.setWindowTitle("Обновление LogDog")
        self.resize(560, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        # Шапка: иконка, «Доступна версия», переход версий
        head = QHBoxLayout()
        head.setSpacing(14)
        logo = QLabel()
        logo.setPixmap(QIcon(resource_path("assets/icon.png")).pixmap(QSize(56, 56)))
        head.addWidget(logo, 0, Qt.AlignTop)
        titles = QVBoxLayout()
        titles.setSpacing(4)
        header = QLabel(f"Доступна версия {info.version}")
        header.setProperty("role", "title")
        titles.addWidget(header)
        versions = QHBoxLayout()
        versions.setSpacing(8)
        sub = QLabel(f"У вас {VERSION}")
        sub.setProperty("role", "muted")
        versions.addWidget(sub)
        chip = QLabel(f"→ {info.version}")
        chip.setProperty("role", "chip")
        versions.addWidget(chip)
        versions.addStretch()
        titles.addLayout(versions)
        head.addLayout(titles, 1)
        layout.addLayout(head)

        changes = QLabel("Что нового")
        changes.setProperty("role", "muted")
        layout.addWidget(changes)
        self.changelog = QTextBrowser()
        self.changelog.setObjectName("Changelog")
        self.changelog.setOpenExternalLinks(True)
        self._fill_changelog()
        layout.addWidget(self.changelog, 1)

        # Состояние: иконка + текст, под ними прогресс
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self.status_icon = QLabel()
        self.status_icon.setFixedSize(18, 18)
        status_row.addWidget(self.status_icon, 0, Qt.AlignTop)
        self.status = QLabel()
        self.status.setWordWrap(True)
        status_row.addWidget(self.status, 1)
        self.progress_text = QLabel()
        self.progress_text.setProperty("role", "muted")
        status_row.addWidget(self.progress_text, 0, Qt.AlignTop)
        layout.addLayout(status_row)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.page_button = QPushButton("Страница релиза")
        self.page_button.setProperty("variant", "ghost")
        self.page_button.clicked.connect(self._open_page)
        buttons.addWidget(self.page_button)
        buttons.addStretch()
        self.later_button = QPushButton("Позже")
        self.later_button.clicked.connect(self.reject)
        buttons.addWidget(self.later_button)
        self.action_button = QPushButton("Скачать обновление")
        self.action_button.setProperty("variant", "primary")
        self.action_button.setDefault(True)
        self.action_button.setCursor(Qt.PointingHandCursor)
        self.action_button.clicked.connect(self._on_action)
        buttons.addWidget(self.action_button)
        layout.addLayout(buttons)

        if info.asset is None:
            self._set_status("Для вашей системы нет файла обновления в релизе — "
                             "скачайте новую версию со страницы релиза.", "warn")
        else:
            try:
                self._target = update_install.install_target()
            except update_install.UpdateError as exc:
                self._set_status(f"Установка из программы недоступна: {exc} "
                                 "Новую версию можно скачать со страницы релиза.", "warn")
        if self._target is None:
            self.action_button.setVisible(False)
            self.page_button.setProperty("variant", "primary")
            self.page_button.setDefault(True)
        else:
            self._set_status("LogDog скачает обновление, проверит его и предложит установить. "
                             "Без вашего нажатия ничего не установится.", "")
        self._refresh_icons()
        theme.theme_signals.theme_changed.connect(self._refresh_icons)

    def _fill_changelog(self):
        t = theme.tokens()
        self.changelog.document().setDefaultStyleSheet(
            f"h1, h2, h3 {{ color: {t['accent']}; font-size: 14px; margin-top: 10px; margin-bottom: 4px; }}"
            f"li {{ margin-bottom: 3px; }} code {{ background-color: {t['window']}; }}"
            f"a {{ color: {t['accent']}; }}")
        self.changelog.setMarkdown(self.info.changelog or "_Список изменений не указан._")

    def _refresh_icons(self, *_):
        self.page_button.setIcon(icons.icon("external"))
        self._fill_changelog()
        self._set_status(self.status.text(), self._status_kind if hasattr(self, "_status_kind") else "")

    def _set_status(self, text: str, kind: str) -> None:
        self._status_kind = kind
        icon_name, color_key = _STATUS_KINDS.get(kind, _STATUS_KINDS[""])
        t = theme.tokens()
        self.status_icon.setPixmap(icons.pixmap(icon_name, t[color_key], 18))
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {t[color_key]};" if kind in ("ok", "warn", "error") else "")

    def _open_page(self) -> None:
        QDesktopServices.openUrl(QUrl(self.info.page_url))

    def _on_action(self) -> None:
        if self._downloaded is None:
            self._start_download()
        else:
            self._install()

    # ── Скачивание ───────────────────────────────────────────────────────

    def _start_download(self) -> None:
        self.action_button.setEnabled(False)
        self.action_button.setText("Скачивание…")
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        self.progress_text.clear()
        self._set_status(f"Скачиваю {self.info.asset.file}", "busy")
        self._downloader = UpdateDownloadThread(self.info.asset)
        self._downloader.progress.connect(self._on_progress)
        self._downloader.downloaded.connect(self._on_downloaded)
        self._downloader.failed.connect(self._on_failed)
        self._downloader.start()

    def _on_progress(self, done: int, total: int) -> None:
        if total > 0:
            self.progress.setRange(0, 1000)
            self.progress.setValue(int(done * 1000 / total))
            self.progress_text.setText(f"{done / 1048576:.0f} из {total / 1048576:.0f} МБ")

    def _on_downloaded(self, path: str) -> None:
        self._downloaded = Path(path)
        self.progress.setVisible(False)
        self.progress_text.clear()
        self._set_status("Файл скачан и проверен. При установке LogDog закроется "
                         "и откроется уже новой версией.", "ok")
        self.action_button.setText("Установить и перезапустить")
        self.action_button.setEnabled(True)

    def _on_failed(self, message: str) -> None:
        self.progress.setVisible(False)
        self.progress_text.clear()
        self._set_status(message, "error")
        self.action_button.setText("Скачать ещё раз")
        self.action_button.setEnabled(True)

    # ── Установка ────────────────────────────────────────────────────────

    def _install(self) -> None:
        if self._downloaded is None or self._target is None:
            return
        for button in (self.action_button, self.later_button, self.page_button):
            button.setEnabled(False)
        self.action_button.setText("Установка…")
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        self._set_status("Проверяю и распаковываю обновление…", "busy")
        self._installer = _InstallThread(self._downloaded, self._target, self.info.asset.sha256)
        self._installer.installed.connect(self._on_installed)
        self._installer.failed.connect(self._on_install_failed)
        self._installer.start()

    def _on_installed(self, mode: str) -> None:
        self._installer.wait()
        self._installer = None
        if mode == "restart":
            try:
                update_install.relaunch(self._target)
            except OSError as exc:
                self._on_install_failed(str(exc))
                return
        self.quit_requested = True
        self.accept()

    def _on_install_failed(self, message: str) -> None:
        if self._installer is not None:
            self._installer.wait()
            self._installer = None
        self.progress.setVisible(False)
        self._set_status(f"Не удалось установить: {message}", "error")
        self.action_button.setText("Установить и перезапустить")
        for button in (self.action_button, self.later_button, self.page_button):
            button.setEnabled(True)

    def reject(self) -> None:
        if self._installer is not None:
            return  # распаковку не прерываем: закрыть окно можно после неё
        super().reject()

    def done(self, result: int) -> None:
        if self._downloader is not None and self._downloader.isRunning():
            self._downloader.stop()
            self._downloader.quit()
            self._downloader.wait(3000)
            if self._downloader.isRunning():
                self._downloader.terminate()
                self._downloader.wait()
        super().done(result)
