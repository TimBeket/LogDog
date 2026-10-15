"""Помощник release.yml (только стандартная библиотека).

  python .github/scripts/release.py notes <версия> <notes.md> [--allow-missing]
      Раздел «## [<версия>]» из CHANGELOG.md → тело релиза (с подсказками по
      установке неподписанных сборок). Без раздела — ошибка: тег без описания
      не выпускаем. --allow-missing (ручная тестовая сборка) — заглушка.

  python .github/scripts/release.py manifest <версия> <тег> <owner/repo> <папка с *.sha256> <latest.json>
      latest.json для проверки обновлений в программе (core/updater.py):
      версия, список изменений и файл для каждой ОС со ссылкой и SHA-256.
"""
import json
import re
import sys
from pathlib import Path

INSTALL_HINTS = """\
---
Сборки собраны автоматически и **не подписаны** — при первом запуске
Windows SmartScreen и macOS Gatekeeper покажут предупреждение.

- Windows: `LogDog-*-windows-setup.exe` — установщик (без прав администратора; ярлык в «Пуске», удаление через «Установленные приложения»); `LogDog-*-windows-portable.zip` — без установки: распаковать и запускать `LogDog.exe` из папки. При предупреждении SmartScreen — «Подробнее» → «Выполнить в любом случае»
- macOS: распаковать, правый клик по LogDog → «Открыть», либо `xattr -cr LogDog.app`
- Linux: `chmod +x LogDog-*.AppImage` и запускать напрямую

Дальше обновляться можно из самой программы: при запуске она сообщит о новой
версии и предложит скачать и установить её.
"""

# суффикс имени файла сборки → ключ в latest.json (core.updater.asset_keys)
PLATFORMS = {
    "-windows-setup.exe": "windows_setup",    # установщик (Inno Setup, packaging/windows/LogDog.iss)
    "-windows-portable.zip": "windows",       # portable: папка LogDog/ — ключ прежний, его ждут уже выпущенные копии
    "-macos.zip": "macos",
    "-linux.AppImage": "linux",
}


def changelog_section(version: str, changelog: str) -> str:
    m = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## |\Z)", changelog, re.M | re.S)
    return m.group(1).strip() if m else ""


def cmd_notes(version: str, out: str, allow_missing: bool) -> None:
    section = changelog_section(version, Path("CHANGELOG.md").read_text(encoding="utf-8"))
    if not section:
        if not allow_missing:
            sys.exit(f"В CHANGELOG.md нет раздела '## [{version}]' — добавь описание версии и перевыпусти тег")
        section = "Тестовая сборка."
    Path(out).write_text(section + "\n\n" + INSTALL_HINTS, encoding="utf-8")
    print(section)


def cmd_manifest(version: str, tag: str, repo: str, sums_dir: str, out: str) -> None:
    installers = {}
    for sum_file in sorted(Path(sums_dir).glob("*.sha256")):
        sha, name = sum_file.read_text(encoding="utf-8").split()[:2]
        for suffix, key in PLATFORMS.items():
            if name.endswith(suffix):
                installers[key] = {
                    "file": name,
                    "url": f"https://github.com/{repo}/releases/download/{tag}/{name}",
                    "sha256": sha.lower(),
                }
    missing = sorted(set(PLATFORMS.values()) - set(installers))
    if missing:
        sys.exit(f"Нет контрольных сумм для: {', '.join(missing)}")
    changelog = changelog_section(version, Path("CHANGELOG.md").read_text(encoding="utf-8"))
    manifest = {
        "version": version,
        "changelog": changelog,
        "url": f"https://github.com/{repo}/releases/tag/{tag}",
        "installers": installers,
    }
    Path(out).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def main(argv: list[str]) -> None:
    if len(argv) >= 3 and argv[0] == "notes":
        cmd_notes(argv[1], argv[2], "--allow-missing" in argv[3:])
    elif len(argv) == 6 and argv[0] == "manifest":
        cmd_manifest(*argv[1:])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
