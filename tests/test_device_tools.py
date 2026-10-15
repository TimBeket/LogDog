"""Действия с устройством — на подделках вместо iPhone (ничего не трогают на
реальном устройстве): очистка данных, ошибки доступа, язык, сопряжение,
профили, DeviceTask, CrashWatcher."""
import asyncio
from datetime import datetime

import pytest

from transports import device_tools as dt

pytestmark = pytest.mark.skipif(not dt.HAS_PYMOBILEDEVICE3, reason="нужен pymobiledevice3")


class FakeAfc:
    """Папка приложения: пути → None (файл) или set имён (папка)."""

    def __init__(self, tree: dict):
        self.tree = tree
        self.closed = False

    async def listdir(self, path):
        return sorted(self.tree[path])

    async def isdir(self, path):
        return isinstance(self.tree.get(path), set)

    async def exists(self, path):
        return path in self.tree

    async def rm(self, path, force=False):
        for p in [p for p in self.tree if p == path or p.startswith(path + "/")]:
            del self.tree[p]
        parent, _, name = path.rpartition("/")
        self.tree[parent or "/"].discard(name)
        return []

    async def close(self):
        self.closed = True


def container():
    paths = {
        "/": {"Documents", "Library", "SystemData", "tmp", ".com.apple.mobile_container_manager.metadata.plist"},
        "/.com.apple.mobile_container_manager.metadata.plist": None,
        "/SystemData": {"com.apple.x"}, "/SystemData/com.apple.x": None,
        "/Documents": {"Unity", "output.log"}, "/Documents/Unity": {"save.dat"},
        "/Documents/Unity/save.dat": None, "/Documents/output.log": None,
        "/Library": {"Preferences", "Caches", "gameAnalytics.sqlite", "WebKit"},
        "/Library/Preferences": {"com.example.mygame.plist"}, "/Library/Preferences/com.example.mygame.plist": None,
        "/Library/Caches": {"appsflyer-v1"}, "/Library/Caches/appsflyer-v1": None,
        "/Library/gameAnalytics.sqlite": None, "/Library/WebKit": {"x"}, "/Library/WebKit/x": None,
        "/tmp": {"t"}, "/tmp/t": None,
    }
    return FakeAfc(paths)


def test_clear_container_keeps_structure_and_system_data():
    afc = container()
    failed = asyncio.run(dt.clear_container(afc))
    assert failed == []
    tree = afc.tree
    # данные удалены…
    for gone in ("/Documents/output.log", "/Documents/Unity", "/Library/Preferences/com.example.mygame.plist",
                 "/Library/gameAnalytics.sqlite", "/Library/WebKit", "/Library/Caches/appsflyer-v1", "/tmp/t"):
        assert gone not in tree, gone
    # …а папки, без которых приложение может не запуститься, и служебное — на месте
    for kept in ("/Documents", "/Library", "/Library/Preferences", "/Library/Caches", "/tmp",
                 "/SystemData/com.apple.x", "/.com.apple.mobile_container_manager.metadata.plist"):
        assert kept in tree, kept


def test_app_store_app_gives_clear_message(monkeypatch):
    async def refuse(*a, **k):
        raise dt.PyMobileDevice3Exception("InstallationLookupFailed")
    monkeypatch.setattr(dt.HouseArrestService, "create", refuse)
    with pytest.raises(dt.AppDataUnavailable, match="App Store"):
        asyncio.run(dt.open_container(object(), "com.google.Gmail"))


def test_unity_log_missing(monkeypatch, tmp_path):
    afc = container()
    afc.tree["/Documents"].discard("output.log")
    del afc.tree["/Documents/output.log"]

    async def create(*a, **k):
        return afc
    monkeypatch.setattr(dt.HouseArrestService, "create", create)
    with pytest.raises(dt.AppDataUnavailable, match="output.log"):
        asyncio.run(dt.pull_unity_log(object(), "com.example.mygame", str(tmp_path / "o.log")))
    assert afc.closed


class FakeLockdown:
    def __init__(self, unpair_error=None):
        self.calls = []
        self.unpair_error = unpair_error

    async def get_value(self, key=None, value=None, domain=None):
        return {"Language": "en-RU", "Locale": "en_RU", "SupportedLanguages": ["en", "ru"],
                "SupportedLocales": ["en_US", "ru_RU"]}

    async def set_language(self, lang):
        self.calls.append(("language", lang))

    async def set_locale(self, loc):
        self.calls.append(("locale", loc))

    async def unpair(self):
        self.calls.append("unpair")
        if self.unpair_error:
            raise self.unpair_error

    async def pair(self, timeout=None):
        self.calls.append(("pair", timeout))

    async def close(self):
        self.calls.append("close")


def test_international_read_and_apply():
    ld = FakeLockdown()
    intl = asyncio.run(dt.read_international(ld))
    assert intl == {"language": "en-RU", "locale": "en_RU", "languages": ["en", "ru"], "locales": ["en_US", "ru_RU"]}
    asyncio.run(dt.apply_international(ld, "ru", "ru_RU"))
    assert ld.calls == [("language", "ru"), ("locale", "ru_RU")]  # без перезагрузки


@pytest.mark.parametrize("unpair_error", [None, RuntimeError("pair record invalid")])
def test_reset_pairing_pairs_even_if_unpair_fails(monkeypatch, unpair_error):
    created = []

    async def create(serial, autopair=True):
        assert autopair is False  # без автосопряжения: оно и не работает
        ld = FakeLockdown(unpair_error if not created else None)
        created.append(ld)
        return ld
    monkeypatch.setattr(dt, "create_using_usbmux", create)
    asyncio.run(dt.reset_pairing("SERIAL", timeout=5))
    old, fresh = created
    assert "unpair" in old.calls and ("pair", 5) in fresh.calls


def test_provisioning_profiles_mapping(monkeypatch):
    class Profile:
        plist = {"Name": "Dev", "TeamName": "Example Team", "Entitlements": {"application-identifier": "T.app"},
                 "ExpirationDate": datetime(2026, 11, 1), "ProvisionedDevices": ["a", "b"]}

    class FakeMisagent:
        def __init__(self, ld):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def copy_all(self):
            return [Profile()]
    monkeypatch.setattr(dt, "MisagentService", FakeMisagent)
    (p,) = asyncio.run(dt.provisioning_profiles(object()))
    assert p == {"name": "Dev", "team": "Example Team", "app_id": "T.app", "expires": datetime(2026, 11, 1),
                 "devices": 2, "all_devices": False}


def test_device_task_reports_result_and_errors(qtbot, monkeypatch):
    async def create(serial, **k):
        return FakeLockdown()
    monkeypatch.setattr(dt, "create_using_usbmux", create)

    async def ok(ld):
        return "fine"

    async def boom(ld):
        raise RuntimeError("no device")

    async def unavailable(ld):
        raise dt.AppDataUnavailable("нет доступа")

    for job, expected in ((ok, ("done", "fine")), (boom, ("failed", "Удалить: no device")),
                          (unavailable, ("failed", "нет доступа"))):
        task = dt.DeviceTask("SERIAL", job, error_prefix="Удалить")
        got = []
        task.done.connect(lambda r: got.append(("done", r)))
        task.failed.connect(lambda m: got.append(("failed", m)))
        task.start()
        qtbot.waitUntil(lambda: bool(got), timeout=3000)
        task.wait(2000)
        assert got == [expected]


def test_crash_watcher_baseline_then_new(qtbot, monkeypatch):
    listings = [["/Old-2026-10-14-100000.ips"],
                ["/Old-2026-10-14-100000.ips", "/MyGame-2026-10-15-160659.ips"]]

    async def fake_list(self):
        return listings[min(self._calls_made(), len(listings) - 1)]

    calls = {"n": 0}

    def calls_made(self):
        calls["n"] += 1
        return calls["n"] - 1
    monkeypatch.setattr(dt.CrashWatcher, "_list", fake_list)
    monkeypatch.setattr(dt.CrashWatcher, "_calls_made", calls_made, raising=False)
    watcher = dt.CrashWatcher("SERIAL", interval=0.05)
    got = []
    watcher.new_reports.connect(got.append)
    watcher.start()
    try:
        qtbot.waitUntil(lambda: bool(got), timeout=3000)
    finally:
        watcher.stop()
        watcher.wait(2000)
    assert got[0] == ["/MyGame-2026-10-15-160659.ips"]  # то, что было при подключении, — не новое
