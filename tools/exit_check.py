"""Закрывается ли программа: запуск как main.py, немного работы, закрытие окна — N раз.

    python tools/exit_check.py --runs 15                 # текущий код
    python tools/exit_check.py --runs 15 --code ../v1.0  # другая версия

Каждый запуск — отдельный процесс: окно, демо-логи, поиск, фильтр, потом
window.close() как крестиком. Меряется, через сколько после закрытия процесс
завершился; дольше --limit секунд — «завис» (процесс убивается). Нужен
потому, что тесты на Windows в CI иногда не завершались после прогона —
проверить, не бывает ли такого у самой программы.
"""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--code", default=str(Path(__file__).resolve().parent.parent))
parser.add_argument("--runs", type=int, default=15)
parser.add_argument("--limit", type=float, default=30.0)
parser.add_argument("--label", default="")
parser.add_argument("--child", action="store_true")
args = parser.parse_args()

if args.child:
    sys.path.insert(0, str(Path(args.code).resolve()))
    import tempfile
    from datetime import datetime, timedelta

    from PySide6.QtCore import QSettings, QTimer
    from PySide6.QtWidgets import QApplication

    from utils.logger import setup_logger
    setup_logger(debug_mode=True)
    app = QApplication(sys.argv)
    from core.settings import settings
    import gui.widgets.filter_history as filter_history
    tmp = Path(tempfile.mkdtemp(prefix="logdog-exit-"))
    settings.store = QSettings(str(tmp / "settings.ini"), QSettings.IniFormat)
    filter_history.get_app_data_dir = lambda: tmp
    settings.help_shown = lambda: True
    from gui.theme import apply_theme
    from gui.main_window import MainWindow
    from gui.tour_steps import _DEMO, _line
    apply_theme(app, "Dark")
    window = MainWindow()   # как в main.py: настоящие потоки (поиск iPhone, обработка логов)
    window.show()

    def work():
        t0 = datetime(2026, 11, 11, 12, 0, 0)
        raws = [_line(t0 + timedelta(milliseconds=20 * i), *_DEMO[i % len(_DEMO)][:2], f"{_DEMO[i % len(_DEMO)][2]} {i}")
                for i in range(5000)]
        window._on_blocks_processed([{"raw": r, "props": window.filter_obj.extract_props(r)} for r in raws])
        window.find_bar.show()
        window.find_bar.input.setText("AppsFlyer")
        window.filter_input.setText("level:error OR appsflyer")
        window._apply_filter()

    def close():
        print("CLOSING", flush=True)
        window.close()   # как крестиком: closeEvent останавливает потоки

    QTimer.singleShot(1500, work)
    QTimer.singleShot(4000, close)
    sys.exit(app.exec())

results = []
for i in range(1, args.runs + 1):
    proc = subprocess.Popen([sys.executable, __file__, "--child", "--code", args.code],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                            errors="replace")
    closed_at = None
    start = time.monotonic()
    out = []
    while True:
        line = proc.stdout.readline()
        if line:
            out.append(line)
            if line.startswith("CLOSING"):
                closed_at = time.monotonic()
                break
        elif proc.poll() is not None or time.monotonic() - start > 60:
            break
    try:
        proc.communicate(timeout=args.limit)
        exit_sec = time.monotonic() - (closed_at or start)
        status = f"вышел за {exit_sec:.1f} с, код {proc.returncode}"
        hung = False
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        status = f"ЗАВИС: не вышел за {args.limit:.0f} с после закрытия"
        hung = True
    if closed_at is None:
        status = "не дошёл до закрытия: " + "".join(out[-5:]).strip()
        hung = True
    results.append((i, status, hung))
    print(f"{i:2d}. {status}", flush=True)

bad = sum(1 for r in results if r[2])
title = f"### Выход программы — {args.label or Path(args.code).name}, {sys.platform}: зависаний {bad} из {len(results)}"
text = "\n".join([title, ""] + [f"- {i}. {s}" for i, s, _ in results]) + "\n\n"
print("\n" + text, flush=True)
summary = os.environ.get("GITHUB_STEP_SUMMARY")
if summary:
    with open(summary, "a", encoding="utf-8") as f:
        f.write(text)
sys.exit(1 if bad else 0)
