"""Замер отзывчивости окна LogDog на большом логе: поиск, фильтр, поток логов.

    python tools/perf_bench.py                 # текущий код
    python tools/perf_bench.py --code ../old   # другая версия (например, git worktree с v1.0)

Меряется главное для пользователя — насколько окно «зависает»: самая долгая
пауза цикла событий Qt во время действия (таймер каждые 5 мс), и через
сколько готов результат. Демо-логи как в обучении, свои настройки не трогает.
Таблица — в stdout и, в GitHub Actions, в сводку запуска (.github/workflows/perf.yml).
Подходит и для старых версий: чего в них нет, то пропускается.
"""
import argparse
import os
import random
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--code", default=str(Path(__file__).resolve().parent.parent), help="папка с кодом LogDog")
parser.add_argument("--entries", type=int, default=100_000)
parser.add_argument("--label", default="")
parser.add_argument("--quick-find-only", action="store_true",
                    help="старые версии: без поиска одной буквы (там это минуты)")
args = parser.parse_args()
sys.path.insert(0, str(Path(args.code).resolve()))

from PySide6.QtCore import QSettings, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

from core.settings import settings  # noqa: E402
import gui.widgets.filter_history as filter_history  # noqa: E402

_tmp = Path(tempfile.mkdtemp(prefix="logdog-perf-"))
settings.store = QSettings(str(_tmp / "settings.ini"), QSettings.IniFormat)
filter_history.get_app_data_dir = lambda: _tmp
settings.help_shown = lambda: True

from gui import main_window as mw  # noqa: E402
from gui.tour_steps import _DEMO, _line  # noqa: E402

for name in ("IosDevicePoller", "UpdaterThread", "IosSyslogReader"):
    setattr(getattr(mw, name), "start", lambda self: None)

rows = []


def row(name, freeze=None, ready=None, note=""):
    cells = [name, f"{freeze:.0f}" if freeze is not None else "—", f"{ready:.0f}" if ready is not None else "—", note]
    rows.append(cells)
    print(" | ".join(cells), flush=True)


class Lag:
    """Самая долгая пауза цикла событий = насколько окно «висело»."""

    def __init__(self):
        self.timer = QTimer()
        self.timer.setInterval(5)
        self.timer.timeout.connect(self._tick)
        self.max = self.last = 0.0

    def _tick(self):
        now = time.perf_counter()
        self.max = max(self.max, now - self.last)
        self.last = now

    def run(self, fn, settle_ms=300):
        self.max, self.last = 0.0, time.perf_counter()
        self.timer.start()
        t = time.perf_counter()
        fn()
        ready = time.perf_counter() - t
        self._tick()
        QTest.qWait(settle_ms)
        self.timer.stop()
        return self.max * 1000, ready * 1000


lag = Lag()


def busy(w):
    """Идёт ли у окна фоновая работа по шагам (в старых версиях её нет)."""
    jobs = [getattr(w, "_rebuild", None), getattr(w, "_watch_job", None)]
    return any(getattr(j, "running", False) for j in jobs if j is not None)


def wait_idle(w, limit=600):
    end = time.perf_counter() + limit
    while busy(w) and time.perf_counter() < end:
        QTest.qWait(5)


random.seed(1)
N = args.entries
t0 = datetime(2026, 11, 5, 12, 0, 0)
raws = [_line(t0 + timedelta(milliseconds=20 * i), *_DEMO[j][:2], f"{_DEMO[j][2]} seq={i}")
        for i, j in enumerate(random.choices(range(len(_DEMO)), k=N + 10_000))]

w = mw.MainWindow()
w.resize(1280, 720)
w.show()
QTest.qWait(100)
blocks = [{"raw": r, "props": w.filter_obj.extract_props(r)} for r in raws]


def feed(bs):
    w._on_blocks_processed([dict(b) for b in bs])


def fill():
    for i in range(0, N, 1000):
        feed(blocks[i:i + 1000])
    wait_idle(w)


freeze, ready = lag.run(fill)
row(f"Загрузить {N:,} записей пачками по 1000".replace(",", " "), None, ready, "не живой поток — просто наполнение")


def stream(start, batches=20):
    def go():
        for k in range(batches):
            feed(blocks[start + k * 100:start + (k + 1) * 100])
            QTest.qWait(50)
    return go


cursor = N
freeze, _ = lag.run(stream(cursor))
cursor += 2000
row("Поток логов 2000 строк/с, поиск закрыт", freeze)

fb = w.find_bar
fb.show()


def type_find(word):
    def go():
        fb.input.clear()
        for i in range(1, len(word) + 1):
            fb.input.setText(word[:i])
            QTest.qWait(120)
        QTest.qWait(400)   # пауза набора — поиск
    return go


for word in ("AppsFlyer", "Ap") + (() if args.quick_find_only else ("a",)):
    freeze, _ = lag.run(type_find(word))
    row(f"Поиск: набрать «{word}»", freeze, None, f"найдено {fb.lbl_count.text()}")
if args.quick_find_only:
    row("Поиск: набрать «a»", None, None, "пропущено: в этой версии — минуты")

fb.input.setText("AppsFlyer")
QTest.qWait(500)
w.chk_auto_scroll.setChecked(True)
freeze, _ = lag.run(stream(cursor))
cursor += 2000
row("Поток логов 2000 строк/с, открыт поиск «AppsFlyer»", freeze)
fb.hide()


def apply_filter(text):
    def go():
        w.filter_input.setText(text)
        w._apply_filter()
        wait_idle(w)
    return go


for text in ('text:"appsflyer"', 'proc:mygame OR text:"appsflyer" OR text:"revenue"', ""):
    freeze, ready = lag.run(apply_filter(text))
    row(f"Фильтр «{text}»" if text else "Фильтр сброшен", freeze, ready, w.lbl_line_count.text())


def type_filter():
    text = 'proc:mygame OR text:"appsflyer"'
    for i in range(1, len(text) + 1):
        w.filter_input.setText(text[:i])
        QTest.qWait(500 if text[i - 1] in ":r" else 120)   # задумался — фильтр успевает примениться
    QTest.qWait(500)
    wait_idle(w)


freeze, _ = lag.run(type_filter)
row("Набор фильтра с паузами", freeze)
apply_filter("")()

freeze, _ = lag.run(lambda: w._add_highlight("AppsFlyer", "#F2C94C"))
row("Подсветить слово", freeze)
freeze, ready = lag.run(apply_filter("level:error OR appsflyer"))
row("Фильтр при подсветке слова", freeze, ready)
apply_filter("")()
freeze, _ = lag.run(lambda: (w._highlights.clear(), w._on_highlights_changed()))
row("Убрать подсветку", freeze)

freeze, ready = lag.run(lambda: (w._add_watch("af_purchase"), wait_idle(w)))
row("Отслеживание: 1-е правило", freeze, ready)
freeze, ready = lag.run(lambda: (w._add_watch("revenue OR adrevenue"), wait_idle(w)))
row("Отслеживание: 2-е правило", freeze, ready)

w.btn_pause.setChecked(True)
feed(blocks[:20_000])
freeze, ready = lag.run(lambda: (w.btn_pause.setChecked(False), wait_idle(w)))
row("Снять паузу (накопилось 20 000)", freeze, ready)

w.processor.stop()
w.processor.wait(2000)

title = f"### {args.label or Path(args.code).name} — {sys.platform}, Qt «{app.platformName()}»"
table = [title, "", "| Действие | Зависание окна, мс | Готово через, мс | |", "|---|---:|---:|---|"]
table += ["| " + " | ".join(r) + " |" for r in rows]
text = "\n".join(table) + "\n\n"
print("\n" + text, flush=True)
summary = os.environ.get("GITHUB_STEP_SUMMARY")
if summary:
    with open(summary, "a", encoding="utf-8") as f:
        f.write(text)
os._exit(0)   # не ждать закрытия Qt и потоков
