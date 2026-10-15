"""Окно «Доступно обновление»: какие кнопки видны и полный путь скачать → установить."""
import hashlib
import sys

import pytest

from core import update_install, updater
from core.updater import Asset, UpdateInfo
from gui.dialogs.update import UpdateDialog


def make_info(asset=True):
    return UpdateInfo(
        version="1.1",
        changelog="### Добавлено\n- что-то",
        page_url="https://github.com/x/LogDog/releases/tag/v1.1",
        asset=Asset(url="u", file="LogDog-1.1-linux.AppImage", sha256="a" * 64) if asset else None,
    )


def test_source_run_offers_only_release_page(qtbot, monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    dlg = UpdateDialog(make_info())
    qtbot.addWidget(dlg)
    assert dlg.action_button.isHidden()
    assert "исходников" in dlg.status.text()


def test_no_installer_for_os_offers_only_release_page(qtbot):
    dlg = UpdateDialog(make_info(asset=False))
    qtbot.addWidget(dlg)
    assert dlg.action_button.isHidden()
    assert "нет файла обновления" in dlg.status.text()


@pytest.fixture
def appimage_install(monkeypatch, tmp_path):
    """Программа «запущена из AppImage»; скачивание отдаёт new_data."""
    appimage = tmp_path / "LogDog.AppImage"
    appimage.write_bytes(b"old")
    monkeypatch.setattr(update_install, "install_target",
                        lambda: update_install.InstallTarget("linux", appimage))
    relaunched = []
    monkeypatch.setattr(update_install, "relaunch", relaunched.append)
    monkeypatch.setattr(updater, "download_dir", lambda: tmp_path / "dl")
    return appimage, relaunched


def _fake_download(monkeypatch, data: bytes):
    class Stream:
        status_code = 200
        headers = {"Content-Length": str(len(data))}

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size):
            yield data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return None

    monkeypatch.setattr(updater.requests, "get", lambda *a, **k: Stream())


def test_download_then_install_replaces_appimage(qtbot, monkeypatch, appimage_install):
    appimage, relaunched = appimage_install
    data = b"new version"
    info = make_info()
    info.asset.sha256 = hashlib.sha256(data).hexdigest()
    _fake_download(monkeypatch, data)

    dlg = UpdateDialog(info)
    qtbot.addWidget(dlg)
    assert dlg.action_button.isVisibleTo(dlg) and dlg.action_button.text() == "Скачать обновление"

    dlg.action_button.click()
    qtbot.waitUntil(lambda: dlg.action_button.text() == "Установить и перезапустить", timeout=3000)
    assert appimage.read_bytes() == b"old"  # без второго нажатия ничего не ставится

    dlg.action_button.click()  # установка идёт в фоне — окно не замирает
    qtbot.waitUntil(lambda: dlg.quit_requested, timeout=3000)
    assert appimage.read_bytes() == data
    assert relaunched


def test_checksum_mismatch_offers_retry(qtbot, monkeypatch, appimage_install):
    appimage, _ = appimage_install
    _fake_download(monkeypatch, b"tampered")

    dlg = UpdateDialog(make_info())
    qtbot.addWidget(dlg)
    dlg.action_button.click()
    qtbot.waitUntil(lambda: dlg.action_button.text() == "Скачать ещё раз", timeout=3000)
    assert "сумма не совпала" in dlg.status.text()
    assert appimage.read_bytes() == b"old" and not dlg.quit_requested
