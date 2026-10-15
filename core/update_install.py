"""Установка скачанного обновления (полуавтомат).

Сознательно НЕ полный автомат: программа ничего не ставит без человека.
Файл обновления для своей ОС она скачивает сама (репозиторий открытый,
GitHub Releases отдаёт файлы без входа — core/updater.py), сверяет SHA-256
с суммой из latest.json релиза и только по кнопке «Установить и
перезапустить» подменяет свои файлы:

- Windows — папка программы (zip с LogDog/), macOS — .app (zip; распаковка
  через ditto: zipfile теряет симлинки и права внутри фреймворков Qt).
  Архив распаковывается рядом с программой, и подмену делает уже НОВАЯ
  версия, запущенная из распакованной папки в режиме `--apply-update`
  (apply_update ниже): ждёт выхода старой, откладывает её в резерв, ставит
  себя на её место (при ошибке возвращает старую) и запускает. Работающий
  .exe заменить нельзя, поэтому подмена — после закрытия. Отдельный скрипт
  (PowerShell с -ExecutionPolicy Bypass из temp) не используем: антивирусы
  и EDR в компаниях считают такой запуск признаком вредоносной программы.
- Linux — AppImage: новый файл кладётся поверх старого атомарным rename — на
  Linux это можно и при запущенной программе (старая дорабатывает со своим
  inode), затем перезапуск.

Перед подменой сумма архива проверяется ещё раз (между скачиванием и
установкой файл лежит на диске). Скачанный архив после подмены удаляется.

Сумма защищает от битого/недокачанного/не того файла. От подмены самого
релиза на GitHub не защищает (там и файл, и сумма) — граница доверия та же,
что у ручного скачивания со страницы релиза.

Здесь нет Qt — диалог (gui/dialogs/update.py) только вызывает эти функции.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

GUI_EXE = "LogDog"
WIN_DIR = "LogDog"
MAC_APP = "LogDog.app"
APPLY_ARG = "--apply-update"
FINISH_ARG = "--finish-update"
#: журнал подмены (в temp) — что пошло не так, если пользователь увидел
#: «Обновление не установлено»
UPDATE_LOG = "logdog-update.log"
#: префикс папки скачивания (core.updater.download_dir)
DOWNLOAD_PREFIX = "LogDog-update-"


class UpdateError(Exception):
    """Понятная пользователю причина, почему установить нельзя."""


@dataclass
class InstallTarget:
    kind: str    # "windows" | "macos" | "linux"
    path: Path   # папка программы / .app / файл .AppImage


def windows_installed() -> bool:
    """Копия поставлена установщиком (Inno Setup кладёт деинсталлятор рядом),
    а не распакована из portable-zip."""
    if not getattr(sys, "frozen", False) or sys.platform != "win32":
        return False
    return (Path(sys.executable).resolve().parent / "unins000.exe").is_file()


def cleanup_old_downloads(max_age_sec: float = 3600) -> None:
    """Папки скачанных обновлений в temp, которые не удалились сами (Setup
    работает из своей папки и удалить её за собой не может). Только наш
    префикс и только старше часа — чтобы не задеть идущее обновление."""
    root = Path(tempfile.gettempdir())
    now = time.time()
    for folder in root.glob(DOWNLOAD_PREFIX + "*"):
        try:
            if folder.is_dir() and now - folder.stat().st_mtime > max_age_sec:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass


def install_target() -> InstallTarget:
    """Что именно заменять. UpdateError — если программа запущена не из сборки
    (из исходников) или раскладка не та, что даёт наш release.yml."""
    if not getattr(sys, "frozen", False):
        raise UpdateError("Программа запущена из исходников — обновляйте через git.")
    exe = Path(sys.executable).resolve()
    if sys.platform == "win32":
        folder = exe.parent
        if not (folder / f"{GUI_EXE}.exe").is_file() or not (folder / "_internal").is_dir():
            raise UpdateError(f"Не найдена папка программы рядом с {exe.name}.")
        return InstallTarget("windows", folder)
    if sys.platform == "darwin":
        # …/LogDog.app/Contents/MacOS/LogDog
        bundle = exe.parents[2]
        if bundle.suffix != ".app":
            raise UpdateError("Программа запущена не из .app.")
        return InstallTarget("macos", bundle)
    appimage = os.environ.get("APPIMAGE")
    if not appimage or not Path(appimage).is_file():
        raise UpdateError("Программа запущена не из AppImage.")
    return InstallTarget("linux", Path(appimage).resolve())


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ── Подготовка и запуск подмены ──────────────────────────────────────────────

def _sibling(path: Path, tag: str) -> Path:
    """Временное соседнее имя на том же диске (move папок/rename — без копирования)."""
    candidate = path.with_name(f"{path.name}.{tag}")
    n = 1
    while candidate.exists():
        n += 1
        candidate = path.with_name(f"{path.name}.{tag}{n}")
    return candidate


def stage_windows(archive: Path, target: Path) -> Path:
    """Распаковывает zip рядом с папкой программы, возвращает новую папку."""
    staging = _sibling(target, "update")
    staging.mkdir()
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(staging)
    inner = staging / WIN_DIR
    if not (inner / f"{GUI_EXE}.exe").is_file():
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError(f"В архиве нет {WIN_DIR}/{GUI_EXE}.exe — не тот файл?")
    return inner


def stage_macos(archive: Path, target: Path) -> Path:
    staging = _sibling(target, "update")
    staging.mkdir()
    result = subprocess.run(["ditto", "-x", "-k", str(archive), str(staging)],
                            capture_output=True, text=True)
    bundle = staging / MAC_APP
    if result.returncode != 0 or not bundle.is_dir():
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError(f"Не удалось распаковать архив: {result.stderr.strip() or 'нет ' + MAC_APP}")
    return bundle


def _remove_download(archive: Path | None) -> None:
    """Скачанный архив и его личную папку из temp (core.updater.download_dir)."""
    if archive is None:
        return
    archive.unlink(missing_ok=True)
    if archive.parent.name.startswith(DOWNLOAD_PREFIX):
        try:
            archive.parent.rmdir()
        except OSError:
            pass


def install(archive: Path, target: InstallTarget, pid: int | None = None,
            expected_sha256: str | None = None) -> str:
    """Готовит подмену и запускает её. Возвращает "restart" (Linux: файл уже
    заменён, программу нужно перезапустить самой) или "quit" (Windows/macOS:
    новая версия ждёт выхода программы — нужно закрыться)."""
    if expected_sha256 is not None and sha256_file(archive) != expected_sha256.lower():
        raise UpdateError("Скачанный файл изменился после проверки — скачайте обновление ещё раз.")
    pid = os.getpid() if pid is None else pid
    if target.kind == "linux":
        tmp = _sibling(target.path, "new")
        shutil.copyfile(archive, tmp)
        os.chmod(tmp, 0o755)
        os.replace(tmp, target.path)
        if archive.resolve() != target.path.resolve():
            _remove_download(archive)
        return "restart"

    if target.kind == "windows" and archive.suffix.lower() == ".exe":
        # Установленная копия: новый Setup поверх — с окном прогресса, без
        # вопросов; та же папка и ярлыки, обновлённая запись в «Установленных
        # приложениях»; /RELAUNCH=1 — запустить LogDog после (LogDog.iss).
        cmd = [str(archive), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS",
               "/RELAUNCH=1"]
        try:
            subprocess.Popen(cmd, close_fds=True, cwd=tempfile.gettempdir(),
                             creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
                             | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        except OSError as exc:
            raise UpdateError(f"Не удалось запустить установщик: {exc}") from exc
        return "quit"

    if target.kind == "windows":
        staged = stage_windows(archive, target.path)
        new_exe = staged / f"{GUI_EXE}.exe"
    elif target.kind == "macos":
        staged = stage_macos(archive, target.path)
        new_exe = staged / "Contents" / "MacOS" / GUI_EXE
    else:
        raise UpdateError(f"Неизвестная платформа: {target.kind}")

    cmd = [str(new_exe), APPLY_ARG, target.kind, str(target.path), str(staged), str(pid), str(archive)]
    # Не из папки программы: на Windows папку, которая служит текущей для
    # живого процесса, не переместить.
    kwargs = {"close_fds": True, "cwd": tempfile.gettempdir()}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    try:
        subprocess.Popen(cmd, **kwargs)
    except OSError as exc:
        shutil.rmtree(staged.parent, ignore_errors=True)
        raise UpdateError(f"Не удалось запустить новую версию: {exc}") from exc
    return "quit"


def relaunch(target: InstallTarget) -> None:
    """Linux: запустить обновлённый AppImage отдельным процессом."""
    subprocess.Popen([str(target.path)], start_new_session=True, close_fds=True,
                     cwd=tempfile.gettempdir())


# ── Режим --apply-update: выполняется новой версией ─────────────────────────

def _log(text: str) -> None:
    try:
        with open(Path(tempfile.gettempdir()) / UPDATE_LOG, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%H:%M:%S')} {text}\n")
    except OSError:
        pass


def _wait_for_exit(pid: int, timeout: float) -> bool:
    if sys.platform == "win32":
        # os.kill(pid, 0) на Windows не проверяет процесс, а завершает его.
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return True
        try:
            return kernel32.WaitForSingleObject(handle, int(timeout * 1000)) == 0
        finally:
            kernel32.CloseHandle(handle)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass
        time.sleep(0.5)
    return False


def _retry(action, what: str, attempts: int = 20, delay: float = 0.5):
    """Только что распакованные файлы и закрывшуюся программу обычно ещё
    несколько секунд проверяет антивирус (Defender) — папка недолго занята."""
    for attempt in range(1, attempts + 1):
        try:
            return action()
        except OSError as exc:
            _log(f"{what} (try {attempt}): {exc}")
            if attempt == attempts:
                raise
            time.sleep(delay)


def _move_tree(src: Path, dst: Path) -> None:
    """Переносит содержимое src в dst по файлам. Целиком папку не перенести:
    в ней работает этот самый процесс (Windows). Файл, который не
    переносится (занят), копируется."""
    for root, _dirs, files in os.walk(src):
        rel = Path(root).relative_to(src)
        (dst / rel).mkdir(parents=True, exist_ok=True)
        for name in files:
            try:
                os.replace(Path(root) / name, dst / rel / name)
            except OSError:
                shutil.copy2(Path(root) / name, dst / rel / name)


def _show_error(text: str) -> None:
    try:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, text, "LogDog", 0x10)
        elif sys.platform == "darwin":
            subprocess.run(["osascript", "-e", "on run argv", "-e",
                            'display alert "LogDog" message (item 1 of argv)', "-e", "end run", text],
                           timeout=600)
    except Exception:
        pass


def _launch(kind: str, target: Path, args: list[str]) -> None:
    if kind == "macos":
        cmd = ["open", "-n", str(target), "--args", *args]
    else:
        cmd = [str(target / f"{GUI_EXE}.exe"), *args]
    subprocess.Popen(cmd, close_fds=True, cwd=tempfile.gettempdir(),
                     **({"start_new_session": True} if sys.platform != "win32" else {}))


def apply_update(kind: str, target: Path, staged: Path, pid: int, archive: Path | None,
                 launch=_launch, wait_timeout: float = 300) -> bool:
    """Ставит staged на место target. True — новая версия на месте и запущена;
    при ошибке старая версия возвращается на место и запускается."""
    _log(f"update {target} from {staged}")
    if not _wait_for_exit(pid, wait_timeout):
        _log(f"program {pid} did not exit")
        _show_error("Обновление не установлено: LogDog не закрылся.")
        shutil.rmtree(staged.parent, ignore_errors=True)
        return False
    backup = _sibling(target, "old")
    try:
        _retry(lambda: os.replace(target, backup), f"move {target} -> {backup}")
        try:
            try:
                os.replace(staged, target)  # macOS: работающую папку переименовать можно
            except OSError:
                _move_tree(staged, target)
        except OSError:
            shutil.rmtree(target, ignore_errors=True)
            _retry(lambda: os.replace(backup, target), f"restore {backup}")
            raise
    except OSError as exc:
        _log(f"FAILED: {exc}")
        _show_error(f"Обновление не установлено: {exc}\n"
                    "Закройте окна, которые используют папку программы, и попробуйте ещё раз.")
        if target.exists():
            launch(kind, target, [FINISH_ARG, str(staged.parent)])
        return False
    if kind == "macos":
        subprocess.run(["xattr", "-cr", str(target)], capture_output=True)
    try:
        _retry(lambda: shutil.rmtree(backup), f"remove {backup}", attempts=10)
    except OSError:
        pass  # новая версия уже на месте — лишняя папка .old не повод для ошибки
    _remove_download(archive)
    _log("done")
    # Папку распаковки удалит уже запущенная новая версия: из неё работает
    # этот процесс (Windows), пока не выйдет.
    try:
        launch(kind, target, [FINISH_ARG, str(staged.parent)])
    except OSError as exc:
        _log(f"launch failed: {exc}")
        _show_error(f"Обновление установлено, но LogDog не запустился: {exc}\nЗапустите его вручную.")
    return True


def apply_main(argv: list[str]) -> int:
    """`LogDog --apply-update <kind> <target> <staged> <pid> <archive>`."""
    try:
        kind, target, staged, pid, archive = argv
        ok = apply_update(kind, Path(target), Path(staged), int(pid), Path(archive))
    except Exception as exc:  # без окна и консоли — иначе ошибку никто не увидит
        _log(f"FAILED: {exc!r}")
        _show_error(f"Обновление не установлено: {exc}")
        return 1
    return 0 if ok else 1


def finish_update(staging_root: str) -> threading.Thread | None:
    """Новая версия после подмены: удалить папку распаковки (в фоне, с
    повторами — процесс --apply-update из неё ещё может выходить). Удаляем
    только соседнюю папку `<программа>.update*` — аргумент командной строки
    не должен позволять удалить что угодно."""
    try:
        target = install_target().path
    except UpdateError:
        return None
    root = Path(staging_root)
    if root.parent != target.parent or not root.name.startswith(f"{target.name}.update"):
        _log(f"refuse to remove {root}")
        return None

    def remove():
        for _ in range(60):
            shutil.rmtree(root, ignore_errors=True)
            if not root.exists():
                return
            time.sleep(1)

    thread = threading.Thread(target=remove, daemon=True)
    thread.start()
    return thread
