"""Проверка .ipa перед установкой: чтение Info.plist и профиля, предупреждения."""
import plistlib
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

from core import ipa_info

UDID = "00008140-001A2B3C4D5E"
NOW = datetime(2026, 10, 15, tzinfo=timezone.utc)


def make_ipa(tmp_path, *, devices=(UDID,), all_devices=False, expires=NOW + timedelta(days=30),
             debuggable=False, min_ios="15.0", with_profile=True, name="MyGame.ipa"):
    info = {"CFBundleDisplayName": "My Game", "CFBundleIdentifier": "com.example.mygame",
            "CFBundleShortVersionString": "1.4.2", "CFBundleVersion": "142", "MinimumOSVersion": min_ios}
    profile = {"Name": "MyGame Dev", "TeamName": "Example Team Ltd",
               "ExpirationDate": expires.replace(tzinfo=None),
               "Entitlements": {"get-task-allow": debuggable}}
    if devices:
        profile["ProvisionedDevices"] = list(devices)
    if all_devices:
        profile["ProvisionsAllDevices"] = True
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("Payload/MyGame.app/Info.plist", plistlib.dumps(info, fmt=plistlib.FMT_BINARY))
        # плагин внутри .app со своим Info.plist — не должен перепутаться с приложением
        zf.writestr("Payload/MyGame.app/PlugIns/Ext.appex/Info.plist",
                    plistlib.dumps({"CFBundleIdentifier": "com.example.mygame.ext"}))
        if with_profile:
            # настоящий профиль — plist внутри подписи CMS; имитируем мусор вокруг
            zf.writestr("Payload/MyGame.app/embedded.mobileprovision",
                        b"\x30\x82\x1f\x00CMS-HEADER" + plistlib.dumps(profile) + b"\x00\xa0SIGNATURE")
    return path


def test_reads_app_and_profile(tmp_path):
    info = ipa_info.read_ipa(make_ipa(tmp_path, debuggable=True))
    assert (info.name, info.bundle_id, info.version, info.build, info.min_ios) == \
        ("My Game", "com.example.mygame", "1.4.2", "142", "15.0")
    assert info.team == "Example Team Ltd" and info.devices == [UDID]
    assert info.kind == "Development"
    assert ipa_info.check(info, udid=UDID, ios_version="27.0.1", now=NOW) == []


def test_device_not_in_profile(tmp_path):
    info = ipa_info.read_ipa(make_ipa(tmp_path, devices=("00008110-OTHER",)))
    assert info.kind == "Ad Hoc"
    (w,) = ipa_info.check(info, udid=UDID, now=NOW)
    assert "UDID этого iPhone нет в профиле" in w.text and w.blocking


def test_expired_profile_and_old_ios(tmp_path):
    info = ipa_info.read_ipa(make_ipa(tmp_path, expires=NOW - timedelta(days=1), min_ios="18.0"))
    texts = [w.text for w in ipa_info.check(info, udid=UDID, ios_version="17.5", now=NOW)]
    assert any("истёк" in t for t in texts) and any("Нужна iOS 18.0" in t for t in texts)


def test_app_store_build_is_explained(tmp_path):
    info = ipa_info.read_ipa(make_ipa(tmp_path, devices=()))
    assert info.kind == "App Store / TestFlight"
    (w,) = ipa_info.check(info, udid=UDID, now=NOW)
    assert "TestFlight" in w.text


def test_enterprise_build_fits_any_device(tmp_path):
    info = ipa_info.read_ipa(make_ipa(tmp_path, devices=(), all_devices=True))
    assert info.kind.startswith("Enterprise")
    assert ipa_info.check(info, udid=UDID, now=NOW) == []


def test_version_compare_is_numeric(tmp_path):
    info = ipa_info.read_ipa(make_ipa(tmp_path, min_ios="9.0"))
    assert ipa_info.check(info, udid=UDID, ios_version="27.0.1", now=NOW) == []  # «27» > «9», не строкой


def test_not_an_ipa(tmp_path):
    bad = tmp_path / "x.ipa"
    bad.write_bytes(b"not a zip")
    with pytest.raises(ipa_info.IpaError, match="не zip"):
        ipa_info.read_ipa(bad)
    empty = tmp_path / "empty.ipa"
    with zipfile.ZipFile(empty, "w") as zf:
        zf.writestr("readme.txt", "x")
    with pytest.raises(ipa_info.IpaError, match="Info.plist"):
        ipa_info.read_ipa(empty)
