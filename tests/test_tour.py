"""Обучение: все шаги проходят, а после — логи и настройки пользователя на месте."""
import pytest
from PySide6.QtCore import Qt

from core.settings import settings
from gui import main_window as mw

REAL = "Oct 15 16:04:01 iPhone-QA MyGame(UnityFramework)[2438] <Notice>: real line {}"


@pytest.fixture
def window(qtbot, monkeypatch):
    for name in ("IosDevicePoller", "UpdaterThread", "IosSyslogReader"):
        monkeypatch.setattr(getattr(mw, name), "start", lambda self: None)
    monkeypatch.setattr(settings, "help_shown", lambda: True)
    w = mw.MainWindow()
    w.resize(1300, 800)
    qtbot.addWidget(w)
    w.show()
    yield w
    w.processor.stop()
    w.processor.wait(2000)


def blocks(w, raws):
    return [{"raw": r, "props": w.filter_obj.extract_props(r)} for r in raws]


def test_tour_walks_all_steps_and_restores_user_state(window, qtbot):
    w = window
    w._on_blocks_processed(blocks(w, [REAL.format(i) for i in range(3)]))
    w._watch.add("real")
    w._highlights.append(["line", "#F2C94C"])
    w.filter_input.setText("real")
    w._apply_filter()
    before = [e["raw"] for e in w._entries]

    w.start_tour()
    assert len(w._entries) > 10 and all("real line" not in e["raw"] for e in w._entries)  # демо вместо своих
    w._on_incoming_blocks(blocks(w, [REAL.format(99)]))  # пришло во время обучения — придержано
    tour = w._tour
    for i in range(len(tour.steps)):
        tour.go(i)
        qtbot.wait(20)
    qtbot.keyClick(w, Qt.Key_Escape)  # Esc — выйти

    assert w._tour is None and w._tour_state is None
    assert [e["raw"] for e in w._entries] == before + [REAL.format(99)]
    assert w.filter_input.text() == "real" and w.filter_obj.filter_text == "real"
    assert w._watch.to_settings() == [["real", True]] and settings.watch_rules() == [["real", True]]
    assert w._highlights == [["line", "#F2C94C"]]


def test_autoplay_runs_demo_actions(window, qtbot):
    w = window
    w.start_tour(autoplay=True)
    tour = w._tour
    step = next(i for i, s in enumerate(tour.steps) if s.title == "Фильтр")
    tour.go(step)
    qtbot.waitUntil(lambda: w.filter_obj.filter_text == "level:error", timeout=5000)
    tour.stop()
    assert w.filter_obj.filter_text == ""
