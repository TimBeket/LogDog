"""Уведомления о новых крашах: разбор имён отчётов, «база», заглушка, защита от потока."""
import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QWidget

from core.crash_alerts import AlertPolicy, describe, new_reports, process_name
from core.settings import settings


def test_process_name_and_describe():
    assert process_name("/MyGame-2026-10-15-160659.ips") == "MyGame"
    assert process_name("/com.apple.WebKit.WebContent-2026-10-15-160659.000.ips") == "com.apple.WebKit.WebContent"
    assert describe("/MyGame-2026-10-15-160659.ips").title == "Новый краш: MyGame"
    assert "памяти" in describe("/JetsamEvent-2026-10-14-162706.ips").title
    # отчёты о расходе ресурсов — не краши
    assert describe("/hybridsearchd.diskwrites_resource-2026-10-15-150542.ips") is None
    assert describe("/Retired") is None


def test_first_listing_is_baseline():
    known = set()
    assert new_reports(known, ["/MyGame-2026-10-15-160659.ips"]) != []  # вызывающий решает, что это база
    known = {"/Old-2026-10-14-100000.ips"}
    fresh = new_reports(known, ["/Old-2026-10-14-100000.ips", "/MyGame-2026-10-15-160659.ips"])
    assert [r.process for r in fresh] == ["MyGame"]
    assert new_reports(known, ["/MyGame-2026-10-15-160659.ips"]) == []


def test_policy_hides_only_what_user_muted():
    muted = {"backboardd"}
    policy = AlertPolicy(lambda p: p in muted)
    art = describe("/MyGame-2026-10-15-160659.ips")
    assert policy.decide(describe("/backboardd-2026-10-15-160659.ips")) == "ignore"
    assert [policy.decide(art) for _ in range(3)] == ["show"] * 3  # молча ничего не скрываем


@pytest.fixture
def temp_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "store", QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat))
    return settings


def test_muted_processes_persist(temp_settings):
    assert temp_settings.muted_crash_processes() == []
    temp_settings.mute_crash_process("MyGame")
    temp_settings.mute_crash_process("MyGame")
    temp_settings.mute_crash_process("backboardd")
    assert temp_settings.muted_crash_processes() == ["MyGame", "backboardd"]
    assert temp_settings.crash_alerts_enabled() is True


# ── Карточки уведомлений в окне ──────────────────────────────────────────────

@pytest.fixture
def alerts(qtbot, temp_settings):
    from gui.crash_alerts import CrashAlerts
    window = QWidget()
    window.resize(1000, 600)
    qtbot.addWidget(window)
    window.show()
    return CrashAlerts(window)


def visible_titles(alerts):
    return [t.title.text() for t in alerts.toasts if t.isVisible()]


def test_toasts_show_bump_and_limit(alerts):
    alerts.on_new_paths(["/MyGame-2026-10-15-160659.ips",
                         "/hybridsearchd.diskwrites_resource-2026-10-15-150542.ips"])
    assert visible_titles(alerts) == ["Новый краш: MyGame"]
    alerts.on_new_paths(["/MyGame-2026-10-15-160710.ips", "/MyGame-2026-10-15-160720.ips"])
    (toast,) = alerts.toasts
    assert "и ещё 2" in toast.subtitle.text()             # цикл падений — счётчик, не новые карточки
    for i in range(5):
        alerts.on_new_paths([f"/Proc{i}-2026-10-15-160659.ips"])
    assert len(alerts.toasts) == 3                         # не больше трёх
    right = alerts.window.width() - 12
    assert all(t.geometry().right() <= right + 1 for t in alerts.toasts)


def test_closed_toast_does_not_swallow_next_crash(alerts):
    alerts.on_new_paths(["/MyGame-2026-10-15-160659.ips"])
    alerts.toasts[0].dismiss()
    alerts.on_new_paths(["/MyGame-2026-10-15-160710.ips"])
    assert visible_titles(alerts) == ["Новый краш: MyGame"]  # раньше — тишина до конца сеанса


def test_frequent_crashes_suggest_muting(alerts):
    alerts.on_new_paths([f"/MyGame-2026-10-15-1607{i}0.ips" for i in range(3)])
    (toast,) = alerts.toasts
    assert "Часто падает" in toast.subtitle.text()
    assert toast.mute_btn.text() == "Не показывать от MyGame"


def test_mute_button_hides_and_remembers(alerts, temp_settings):
    alerts.on_new_paths(["/MyGame-2026-10-15-160659.ips"])
    alerts.toasts[0].mute_btn.click()
    assert alerts.toasts == [] and temp_settings.muted_crash_processes() == ["MyGame"]
    alerts.on_new_paths(["/MyGame-2026-10-15-170000.ips"])
    assert alerts.toasts == []


def test_toast_hides_itself(alerts, qtbot, monkeypatch):
    from gui.widgets import crash_toast
    monkeypatch.setattr(crash_toast, "HIDE_AFTER_MS", 100)
    alerts.on_new_paths(["/MyGame-2026-10-15-160659.ips"])
    qtbot.waitUntil(lambda: alerts.toasts == [], timeout=2000)


def test_disabled_alerts_do_not_start_watcher(alerts, temp_settings):
    temp_settings.set_crash_alerts_enabled(False)
    alerts.start("00008140-001A2B3C4D5E")
    assert alerts.watcher is None
