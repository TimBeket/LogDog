"""Установка скачанного обновления (core/update_install.py).

Подмену (apply_update) проверяем на любой ОС; полный путь с настоящим
LogDog.exe-заглушкой — только на Windows: вручную
`gh workflow run tests.yml -f os=windows-latest` и в релизной сборке.
"""
import os
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import pytest

from core import update_install as ui


# ── Где установлена программа ────────────────────────────────────────────────

def test_install_target_refuses_source_run(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    with pytest.raises(ui.UpdateError, match="исходников"):
        ui.install_target()


def test_install_target_linux_uses_appimage_env(monkeypatch, tmp_path):
    appimage = tmp_path / "LogDog.AppImage"
    appimage.write_bytes(b"old")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("APPIMAGE", str(appimage))
    assert ui.install_target() == ui.InstallTarget("linux", appimage.resolve())


def test_install_target_linux_without_appimage(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("APPIMAGE", raising=False)
    with pytest.raises(ui.UpdateError, match="AppImage"):
        ui.install_target()


# ── Подмена ──────────────────────────────────────────────────────────────────

def test_linux_install_replaces_appimage_in_place(tmp_path):
    appimage = tmp_path / "LogDog.AppImage"
    appimage.write_bytes(b"old")
    downloaded = tmp_path / "download.AppImage"
    downloaded.write_bytes(b"new")

    mode = ui.install(downloaded, ui.InstallTarget("linux", appimage))

    assert mode == "restart"
    assert appimage.read_bytes() == b"new"
    if sys.platform != "win32":  # бит исполнения есть только в POSIX
        assert appimage.stat().st_mode & stat.S_IXUSR
    assert sorted(p.name for p in tmp_path.iterdir()) == ["LogDog.AppImage"]


def _windows_zip(path: Path, exe: str = "LogDog/LogDog.exe") -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(exe, "exe")
        zf.writestr("LogDog/_internal/lib.dll", "lib")
    return path


def test_stage_windows_unpacks_next_to_program(tmp_path):
    program = tmp_path / "LogDog"
    program.mkdir()
    staged = ui.stage_windows(_windows_zip(tmp_path / "u.zip"), program)
    assert staged == tmp_path / "LogDog.update" / "LogDog"
    assert (staged / "_internal" / "lib.dll").is_file()


def test_stage_windows_rejects_wrong_archive_and_cleans_up(tmp_path):
    program = tmp_path / "LogDog"
    program.mkdir()
    archive = _windows_zip(tmp_path / "u.zip", exe="Something/else.exe")
    with pytest.raises(ui.UpdateError, match="не тот файл"):
        ui.stage_windows(archive, program)
    assert not (tmp_path / "LogDog.update").exists()


def _program(tmp_path: Path, version: str, name: str = "LogDog") -> Path:
    folder = tmp_path / name
    (folder / "_internal").mkdir(parents=True)
    (folder / "LogDog.exe").write_text(version)
    (folder / "_internal" / "lib.dll").write_text(version)
    return folder


def _gone_pid() -> int:
    """PID уже завершившегося (и прибранного) процесса — «программа закрылась»."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def test_install_rechecks_checksum_before_swap(tmp_path):
    appimage = tmp_path / "LogDog.AppImage"
    appimage.write_bytes(b"old")
    downloaded = tmp_path / "download.AppImage"
    downloaded.write_bytes(b"replaced after download")
    with pytest.raises(ui.UpdateError, match="изменился"):
        ui.install(downloaded, ui.InstallTarget("linux", appimage), expected_sha256="0" * 64)
    assert appimage.read_bytes() == b"old"


def test_install_launches_new_version_in_apply_mode(tmp_path, monkeypatch):
    program = tmp_path / "LogDog"
    program.mkdir()
    archive = _windows_zip(tmp_path / "u.zip")
    started = []
    monkeypatch.setattr(ui.subprocess, "Popen", lambda cmd, **kw: started.append((cmd, kw)))
    mode = ui.install(archive, ui.InstallTarget("windows", program), pid=4321,
                      expected_sha256=ui.sha256_file(archive))
    assert mode == "quit"
    (cmd, kwargs), = started
    staged = tmp_path / "LogDog.update" / "LogDog"
    assert cmd == [str(staged / "LogDog.exe"), ui.APPLY_ARG, "windows", str(program), str(staged),
                   "4321", str(archive)]
    assert kwargs["cwd"] == tempfile.gettempdir()  # не папка программы — её переносят
    assert "powershell" not in " ".join(cmd).lower()


def test_apply_update_swaps_launches_and_cleans_up(tmp_path):
    program = _program(tmp_path, "1.0")
    staged = _program(tmp_path / "LogDog.update", "1.1")
    download = tmp_path / "tmp" / (ui.DOWNLOAD_PREFIX + "abc")
    download.mkdir(parents=True)
    archive = download / "LogDog-1.1-windows.zip"
    archive.write_bytes(b"zip")
    launched = []

    ok = ui.apply_update("windows", program, staged, _gone_pid(), archive,
                         launch=lambda kind, target, args: launched.append((target, args)))

    assert ok
    assert (program / "LogDog.exe").read_text() == "1.1"
    assert (program / "_internal" / "lib.dll").read_text() == "1.1"
    assert launched == [(program, [ui.FINISH_ARG, str(tmp_path / "LogDog.update")])]
    assert not (tmp_path / "LogDog.old").exists()
    assert not download.exists()  # архив и его папка из temp


def test_apply_update_copies_busy_files(tmp_path, monkeypatch):
    """Windows: файлы работающего процесса (он запущен из staged) не
    переносятся — их копируем."""
    program = _program(tmp_path, "1.0")
    staged = _program(tmp_path / "LogDog.update", "1.1")
    real_replace = os.replace

    def replace(src, dst):
        if Path(src) == staged or Path(src).name == "LogDog.exe":
            raise PermissionError("busy")
        real_replace(src, dst)

    monkeypatch.setattr(ui.os, "replace", replace)
    assert ui.apply_update("windows", program, staged, _gone_pid(), None, launch=lambda *a: None)
    assert (program / "LogDog.exe").read_text() == "1.1"
    assert (program / "_internal" / "lib.dll").read_text() == "1.1"


def test_apply_update_restores_old_version_on_failure(tmp_path, monkeypatch):
    program = _program(tmp_path, "1.0")
    staged = _program(tmp_path / "LogDog.update", "1.1")
    monkeypatch.setattr(ui, "_move_tree", lambda src, dst: (_ for _ in ()).throw(OSError("disk full")))
    monkeypatch.setattr(ui.os, "replace", _replace_except(staged))
    errors, launched = [], []
    monkeypatch.setattr(ui, "_show_error", errors.append)

    ok = ui.apply_update("windows", program, staged, _gone_pid(), None,
                         launch=lambda kind, target, args: launched.append(target))

    assert not ok and "disk full" in errors[0]
    assert (program / "LogDog.exe").read_text() == "1.0"  # старая версия на месте
    assert launched == [program]                           # и запущена
    assert not (tmp_path / "LogDog.old").exists()


def _replace_except(staged: Path):
    real_replace = os.replace

    def replace(src, dst):
        if Path(src) == staged:
            raise PermissionError("busy")
        real_replace(src, dst)
    return replace


def test_apply_update_gives_up_if_program_keeps_running(tmp_path, monkeypatch):
    program = _program(tmp_path, "1.0")
    staged = _program(tmp_path / "LogDog.update", "1.1")
    monkeypatch.setattr(ui, "_show_error", lambda text: None)
    assert not ui.apply_update("windows", program, staged, os.getpid(), None,
                               launch=lambda *a: pytest.fail("запуск"), wait_timeout=0.5)
    assert (program / "LogDog.exe").read_text() == "1.0"
    assert not (tmp_path / "LogDog.update").exists()


def test_finish_update_removes_only_staging_sibling(tmp_path, monkeypatch):
    program = _program(tmp_path, "1.1")
    monkeypatch.setattr(ui, "install_target", lambda: ui.InstallTarget("windows", program))
    staging = tmp_path / "LogDog.update"
    (staging / "LogDog").mkdir(parents=True)
    ui.finish_update(str(staging)).join(5)
    assert not staging.exists()

    other = tmp_path / "Документы"
    other.mkdir()
    assert ui.finish_update(str(other)) is None
    assert ui.finish_update(str(program)) is None
    assert other.exists() and program.exists()


# ── Подмена на настоящем Windows ─────────────────────────────────────────────

@pytest.mark.skipif(sys.platform != "win32", reason="занятые файлы и ожидание процесса — Windows")
def test_windows_apply_update_end_to_end(tmp_path):
    """Как в жизни: старая «программа» работает из своей папки, процесс
    подмены — из папки распаковки (его файлы заняты), программа закрывается."""
    program = _program(tmp_path / "QA Tools", "1.0")
    staged = _program(tmp_path / "QA Tools" / "LogDog.update", "1.1")
    app = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(3)"], cwd=program)
    with open(staged / "_internal" / "lib.dll", "rb"):  # занят без FILE_SHARE_DELETE
        launched = []
        ok = ui.apply_update("windows", program, staged, app.pid, None,
                             launch=lambda kind, target, args: launched.append(target))
    app.wait()
    log = Path(tempfile.gettempdir()) / ui.UPDATE_LOG
    journal = log.read_text(encoding="utf-8", errors="replace") if log.exists() else "(журнала нет)"
    assert ok, journal
    assert (program / "_internal" / "lib.dll").read_text() == "1.1"
    assert launched == [program]
    assert sorted(p.name for p in program.parent.iterdir()) == ["LogDog", "LogDog.update"]


def test_installed_copy_updates_by_running_setup_over_it(tmp_path, monkeypatch):
    setup = tmp_path / "LogDog-1.1-windows-setup.exe"
    setup.write_bytes(b"setup")
    started = []
    monkeypatch.setattr(ui.subprocess, "Popen", lambda cmd, **kw: started.append(cmd))
    mode = ui.install(setup, ui.InstallTarget("windows", tmp_path / "LogDog"),
                      expected_sha256=ui.sha256_file(setup))
    assert mode == "quit"
    (cmd,) = started
    assert cmd[0] == str(setup) and "/SILENT" in cmd and "/RELAUNCH=1" in cmd  # окно прогресса, без вопросов


def test_windows_installed_detects_uninstaller(tmp_path, monkeypatch):
    exe = tmp_path / "LogDog.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "executable", str(exe))
    assert ui.windows_installed() is False      # portable: деинсталлятора рядом нет
    (tmp_path / "unins000.exe").write_bytes(b"")
    assert ui.windows_installed() is True


def test_cleanup_removes_only_old_update_folders(tmp_path, monkeypatch):
    monkeypatch.setattr(ui.tempfile, "gettempdir", lambda: str(tmp_path))
    old = tmp_path / (ui.DOWNLOAD_PREFIX + "old")
    fresh = tmp_path / (ui.DOWNLOAD_PREFIX + "fresh")
    other = tmp_path / "SomethingElse"
    for d in (old, fresh, other):
        d.mkdir()
    os.utime(old, (time.time() - 7200, time.time() - 7200))
    os.utime(other, (time.time() - 7200, time.time() - 7200))
    ui.cleanup_old_downloads()
    assert not old.exists() and fresh.exists() and other.exists()
