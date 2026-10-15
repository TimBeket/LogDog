"""Проверка обновлений (latest.json) и скачивание файла обновления."""
import hashlib
from unittest.mock import Mock

import pytest
import requests

from core import updater
from core.updater import Asset, UpdateDownloadThread, UpdaterThread, is_newer, parse_update

KEY = updater.platform_key()
SHA = "a" * 64


def manifest(version="1.1", **installers):
    return {
        "version": version,
        "changelog": "### Добавлено\n- что-то",
        "url": "https://github.com/x/LogDog/releases/tag/v" + version,
        "installers": installers or {KEY: {"file": f"LogDog-{version}-{KEY}.zip",
                                           "url": "https://example/file", "sha256": SHA.upper()}},
    }


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr(updater.time, "sleep", lambda _s: None)


def _response(status=200, payload=None):
    resp = Mock()
    resp.status_code = status
    resp.json.return_value = payload
    if status >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(str(status))
    return resp


def run_check(qtbot, monkeypatch, responses, current="1.0"):
    """Запускает UpdaterThread с подменёнными ответами, возвращает (UpdateInfo|None, число запросов)."""
    calls = []

    def fake_get(url, headers=None, timeout=None):
        calls.append(url)
        item = responses[min(len(calls), len(responses)) - 1]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(updater.requests, "get", fake_get)
    thread = UpdaterThread(current_version=current)
    results = []
    thread.update_available.connect(results.append)
    thread.start()
    thread.wait(3000)
    qtbot.wait(50)
    return (results[0] if results else None), len(calls)


def test_is_newer():
    assert is_newer("1.0.1", "1.0")
    assert is_newer("v1.10", "1.9")
    assert is_newer("1.0", "0.0.0-dev")
    assert not is_newer("1.0", "1.0.0")
    assert not is_newer("v1.0", "1.1")


def test_parse_update_reads_installer_for_current_os():
    info = parse_update(manifest(), "1.0")
    assert info.version == "1.1"
    assert info.changelog.startswith("### Добавлено")
    assert info.page_url.endswith("/v1.1")
    assert info.asset == Asset(url="https://example/file", file=f"LogDog-1.1-{KEY}.zip", sha256=SHA)


def test_parse_update_same_or_older_version_is_none():
    assert parse_update(manifest("1.0"), "1.0") is None
    assert parse_update(manifest("0.9"), "1.0") is None
    assert parse_update({}, "1.0") is None


@pytest.mark.parametrize("raw", [
    {"file": "a.zip", "url": "u", "sha256": "not-a-hash"},
    {"file": "a.zip", "url": "", "sha256": SHA},
    {"file": "../evil.zip", "url": "u", "sha256": SHA},
])
def test_bad_installer_leaves_only_release_page(raw):
    info = parse_update(manifest(**{KEY: raw}), "1.0")
    assert info.asset is None
    assert info.page_url


def test_missing_installer_for_this_os_leaves_only_release_page():
    other = "linux" if KEY != "linux" else "windows"
    info = parse_update(manifest(**{other: {"file": "a", "url": "u", "sha256": SHA}}), "1.0")
    assert info.asset is None


def test_thread_emits_update(qtbot, monkeypatch):
    info, calls = run_check(qtbot, monkeypatch, [_response(200, manifest())])
    assert info.version == "1.1" and calls == 1


def test_thread_no_update_when_same_version(qtbot, monkeypatch):
    info, _ = run_check(qtbot, monkeypatch, [_response(200, manifest("1.0"))])
    assert info is None


def test_thread_404_means_no_update_without_retries(qtbot, monkeypatch):
    """У последнего релиза нет latest.json (например, старый v1.0) — тихо, без ретраев."""
    info, calls = run_check(qtbot, monkeypatch, [_response(404)])
    assert info is None and calls == 1


def test_thread_retries_network_errors(qtbot, monkeypatch):
    info, calls = run_check(qtbot, monkeypatch, [requests.ConnectionError("offline"),
                                                 _response(500),
                                                 _response(200, manifest())])
    assert info.version == "1.1" and calls == 3


def test_thread_gives_up_after_max_attempts(qtbot, monkeypatch):
    info, calls = run_check(qtbot, monkeypatch, [requests.ConnectionError("offline")])
    assert info is None and calls == updater._MAX_ATTEMPTS


def test_dev_version_skips_request(qtbot, monkeypatch):
    info, calls = run_check(qtbot, monkeypatch, [_response(200, manifest())], current="0.0.0-dev")
    assert info is None and calls == 0


# ── Скачивание ───────────────────────────────────────────────────────────────

class _Stream:
    def __init__(self, data: bytes, status=200):
        self.data, self.status_code = data, status
        self.headers = {"Content-Length": str(len(data))}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def iter_content(self, chunk_size):
        for i in range(0, len(self.data), 4):
            yield self.data[i:i + 4]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


def run_download(qtbot, monkeypatch, tmp_path, data: bytes, sha: str, status=200):
    monkeypatch.setattr(updater.requests, "get", lambda *a, **k: _Stream(data, status))
    thread = UpdateDownloadThread(Asset(url="u", file="LogDog-1.1.zip", sha256=sha), dest_dir=tmp_path)
    got = {"ok": [], "failed": [], "progress": []}
    thread.downloaded.connect(got["ok"].append)
    thread.failed.connect(got["failed"].append)
    thread.progress.connect(lambda done, total: got["progress"].append((done, total)))
    thread.start()
    thread.wait(3000)
    qtbot.wait(50)
    return got


def test_download_verifies_sha_and_reports_progress(qtbot, monkeypatch, tmp_path):
    data = b"new version archive"
    got = run_download(qtbot, monkeypatch, tmp_path, data, hashlib.sha256(data).hexdigest())
    assert got["failed"] == []
    assert got["ok"] == [str(tmp_path / "LogDog-1.1.zip")]
    assert (tmp_path / "LogDog-1.1.zip").read_bytes() == data
    assert got["progress"][-1] == (len(data), len(data))


def test_download_with_wrong_sha_is_rejected_and_removed(qtbot, monkeypatch, tmp_path):
    got = run_download(qtbot, monkeypatch, tmp_path, b"tampered", SHA)
    assert got["ok"] == [] and "сумма не совпала" in got["failed"][0]
    assert list(tmp_path.iterdir()) == []


def test_download_http_error(qtbot, monkeypatch, tmp_path):
    got = run_download(qtbot, monkeypatch, tmp_path, b"", SHA, status=404)
    assert got["ok"] == [] and "Не удалось скачать" in got["failed"][0]
    assert list(tmp_path.iterdir()) == []


def _installers():
    return {k: {"file": f"LogDog-1.1-{k}.bin", "url": "https://example/f", "sha256": SHA}
            for k in ("windows_setup", "windows", "macos", "linux")}


def test_installed_windows_copy_prefers_setup(monkeypatch):
    monkeypatch.setattr(updater.sys, "platform", "win32")
    monkeypatch.setattr(updater, "windows_installed", lambda: True)
    assert parse_update(manifest(**_installers()), "1.0").asset.file == "LogDog-1.1-windows_setup.bin"
    only_zip = {k: v for k, v in _installers().items() if k != "windows_setup"}
    assert parse_update(manifest(**only_zip), "1.0").asset.file == "LogDog-1.1-windows.bin"  # старый релиз


def test_portable_windows_copy_takes_zip(monkeypatch):
    monkeypatch.setattr(updater.sys, "platform", "win32")
    monkeypatch.setattr(updater, "windows_installed", lambda: False)
    assert parse_update(manifest(**_installers()), "1.0").asset.file == "LogDog-1.1-windows.bin"
