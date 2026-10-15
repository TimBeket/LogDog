import os
import sys
import threading

# Собранная PyInstaller-версия на Linux: загрузчик кладёт в LD_LIBRARY_PATH
# свою папку с библиотеками, и дочерние процессы (xdg-open для ссылок,
# перезапуск AppImage после обновления) падают на несовместимых копиях
# системных библиотек. Самой программе это уже не нужно — динамический
# загрузчик прочитал переменную при старте, — возвращаем исходное значение.
if getattr(sys, "frozen", False) and sys.platform.startswith("linux"):
    _orig = os.environ.pop("LD_LIBRARY_PATH_ORIG", None)
    if _orig is None:
        os.environ.pop("LD_LIBRARY_PATH", None)
    else:
        os.environ["LD_LIBRARY_PATH"] = _orig

# Установка обновления: эту (новую) версию запустила старая из папки
# распаковки — подменить программу и выйти. До импорта Qt: окно не нужно,
# а чем меньше библиотек загружено, тем меньше файлов занято при переносе.
if getattr(sys, "frozen", False) and sys.argv[1:2] == ["--apply-update"]:
    from core.update_install import apply_main
    sys.exit(apply_main(sys.argv[2:]))

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from utils.helpers import resource_path
from utils.logger import setup_logger, logger
from core import update_install
from core.version import VERSION
from core.settings import settings
from gui.theme import apply_theme
from gui.main_window import MainWindow

# Запуск из исходников на Windows: без собственного AppUserModelID панель
# задач группирует окно под python.exe и показывает иконку Python. В сборке
# не задаём — там иконку даёт сам LogDog.exe, а свой ID отвязал бы окно от
# ярлыков, закреплённых на панели задач.
if sys.platform == "win32" and not getattr(sys, "frozen", False):
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("LogDog")

def main():
    setup_logger(debug_mode=True)
    logger.info("Starting LogDog %s...", VERSION)
    if sys.argv[1:2] == [update_install.FINISH_ARG] and len(sys.argv) > 2:
        update_install.finish_update(sys.argv[2])
    if getattr(sys, "frozen", False):
        threading.Thread(target=update_install.cleanup_old_downloads, daemon=True).start()

    app = QApplication(sys.argv)
    app.setApplicationName("LogDog")
    app.setOrganizationName("QA Tools")
    # Иконка окна и панели задач. Иконка .exe (LogDog.spec) — только для
    # проводника, у окна Qt по умолчанию стандартная.
    app.setWindowIcon(QIcon(resource_path("assets/icon.png")))
    # Wayland (KDE, GNOME): app_id окна = имя .desktop-файла (packaging/
    # logdog.desktop) — по нему панель находит иконку и группирует окна.
    app.setDesktopFileName("logdog")

    # Init theme
    apply_theme(app, settings.theme())

    window = MainWindow()
    window.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
