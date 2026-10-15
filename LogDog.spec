# -*- mode: python ; coding: utf-8 -*-
"""Сборка PyInstaller: одна папка (onedir), а не один файл.

  Windows/Linux: <dist>/LogDog/LogDog(.exe) + <dist>/LogDog/_internal/
  macOS:         <dist>/LogDog.app

Почему папка: --onefile при каждом запуске распаковывает себя во временную
папку (заметная задержка старта с Qt), а установка обновления из программы
(core/update_install.py) рассчитана именно на эту раскладку: Windows — zip
папки, macOS — zip .app, Linux — папка внутри AppImage (см. release.yml).

Запуск: pyinstaller --noconfirm --distpath dist LogDog.spec
Иконки .ico (Windows) и .icns (macOS) генерируются в release.yml из assets/icon.png;
локально .ico берётся из репозитория, а macOS без .icns собирается без иконки.
"""
import os
import sys

from PyInstaller.utils.hooks import collect_data_files

IS_WIN = sys.platform == 'win32'
IS_MAC = sys.platform == 'darwin'

icon = None
if IS_WIN and os.path.exists('assets/icon.ico'):
    icon = 'assets/icon.ico'
elif IS_MAC and os.path.exists('assets/icon.icns'):
    icon = 'assets/icon.icns'

# Ресурсы pymobiledevice3 (не .py) статический анализ импортов не видит.
datas = collect_data_files('pymobiledevice3') + [('assets/icon.png', 'assets')]

a = Analysis(
    ['main.py'],
    pathex=[],
    datas=datas,
    # Ничего не исключаем ради размера: pymobiledevice3 импортирует, например,
    # IPython на верхнем уровне — без него iOS-режим молча отключается
    # (HAS_PYMOBILEDEVICE3 = False), проверено на сборке.
    noarchive=False,
)

exe = EXE(
    PYZ(a.pure),
    a.scripts,
    [],
    exclude_binaries=True,
    name='LogDog',
    console=False,
    icon=icon,
)

coll = COLLECT(exe, a.binaries, a.datas, name='LogDog')

if IS_MAC:
    app = BUNDLE(
        coll,
        name='LogDog.app',
        icon=icon,
        bundle_identifier=None,
    )
