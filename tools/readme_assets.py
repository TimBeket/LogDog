"""Картинки для README из настоящего интерфейса LogDog на демо-данных.

    python tools/readme_assets.py

Рисует без экрана (offscreen), ваши настройки не трогает. Результат —
assets/readme/: шапка, анимации (WebP), скриншоты и иконки, каждое в тёмной
и светлой теме — README показывает нужное по теме GitHub посетителя.
Интерфейс поменялся — запустите снова.
"""
import io
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "assets" / "readme"

from PIL import Image, ImageDraw, ImageFilter  # noqa: E402
from PySide6.QtCore import QBuffer, QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QRadialGradient  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)

from PySide6.QtCore import QSettings  # noqa: E402
from core.settings import settings  # noqa: E402
import gui.widgets.filter_history as filter_history  # noqa: E402

_tmp = Path(tempfile.mkdtemp(prefix="logdog-readme-"))
settings.store = QSettings(str(_tmp / "settings.ini"), QSettings.IniFormat)  # свои настройки не трогаем
filter_history.get_app_data_dir = lambda: _tmp
settings.help_shown = lambda: True

from gui import icons, main_window as mw, theme  # noqa: E402
from gui.theme import apply_theme  # noqa: E402
from gui.tour_steps import _cursor_to_line, _feed, _line, _CHECKER, load_demo  # noqa: E402

for name in ("IosDevicePoller", "UpdaterThread", "IosSyslogReader"):
    setattr(getattr(mw, name), "start", lambda self: None)

THEMES = ("Dark", "Light")


def to_pil(qimage: QImage) -> Image.Image:
    buf = QBuffer()
    buf.open(QBuffer.ReadWrite)
    qimage.save(buf, "PNG")
    return Image.open(io.BytesIO(bytes(buf.data()))).convert("RGBA")


def grab(widget) -> Image.Image:
    return to_pil(widget.grab().toImage())


def make_window(theme_name: str, size=(1280, 720), panel=False):
    # каждое окно — с чистыми настройками: иначе оно вспомнило бы фильтр прошлой анимации
    settings.store = QSettings(str(Path(tempfile.mkdtemp(dir=_tmp)) / "settings.ini"), QSettings.IniFormat)
    apply_theme(app, theme_name)
    w = mw.MainWindow()
    w.resize(*size)
    w.show()
    w.activateWindow()
    w._on_devices_updated([{"serial": "demo", "name": "iPhone QA", "model": "iPhone 16"}])
    w._ios_device_available = True
    load_demo(w)
    w._on_link_state("streaming")
    w.status_bar.showMessage("Сбор логов iOS (iPhone QA)")
    if panel:
        w.btn_panel.setChecked(True)
    QTest.qWait(50)
    return w


def close(w):
    w._demo_timer.stop() if hasattr(w, "_demo_timer") else None
    if w.tools_window is not None:
        w.tools_window.close()
    w.processor.stop()
    w.processor.wait(2000)
    w.close()
    w.deleteLater()
    QTest.qWait(20)


# ── Шапка ───────────────────────────────────────────────────────────────────

def hero(theme_name: str):
    w = make_window(theme_name, (1360, 780), panel=True)
    w.btn_delta.setChecked(True)
    w._highlights[:] = [["af_ad_revenue", "#F2C94C"]]
    w._on_highlights_changed()
    _cursor_to_line(w, "af_ad_revenue")
    QTest.qWait(50)
    shot = grab(w)
    close(w)

    t = theme.TOKENS[theme_name]
    width, height = 2100, 1000
    canvas = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    p = QPainter(canvas)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    bg = QLinearGradient(0, 0, width, height)
    if theme_name == "Dark":
        bg.setColorAt(0, QColor("#111214"))
        bg.setColorAt(1, QColor("#16221C"))
    else:
        bg.setColorAt(0, QColor("#FBFCFB"))
        bg.setColorAt(1, QColor("#E2F4EA"))
    p.fillRect(canvas.rect(), bg)
    glow = QRadialGradient(QPointF(width * 0.5, height * 0.62), height * 0.7)
    accent_glow = QColor(t["accent"])
    accent_glow.setAlpha(70 if theme_name == "Dark" else 60)
    glow.setColorAt(0, accent_glow)
    glow.setColorAt(1, QColor(0, 0, 0, 0))
    p.fillRect(canvas.rect(), glow)

    # Сверху по центру: название, подзаголовок, плашки
    title = QFont(app.font())
    title.setPixelSize(104)
    title.setWeight(QFont.Black)
    p.setFont(title)
    p.setPen(QColor(t["text"]))
    p.drawText(QRectF(0, 40, width, 130), Qt.AlignCenter, "LogDog")
    sub = QFont(app.font())
    sub.setPixelSize(34)
    p.setFont(sub)
    p.setPen(QColor(t["muted"]))
    p.drawText(QRectF(0, 168, width, 50), Qt.AlignCenter, "Логи игр на iPhone для QA в реальном времени")
    chip = QFont(app.font())
    chip.setPixelSize(22)
    chip.setWeight(QFont.DemiBold)
    p.setFont(chip)
    chips = ("iPhone по USB", "Unity: USB и Wi-Fi", "Windows · macOS · Linux")
    widths = [p.fontMetrics().horizontalAdvance(text) + 30 for text in chips]
    x = (width - sum(widths) - 10 * (len(chips) - 1)) / 2
    for text, tw in zip(chips, widths):
        rect = QRectF(x, 236, tw, 46)
        fill = QColor(t["accent"])
        fill.setAlpha(36)
        p.setBrush(fill)
        p.setPen(QColor(t["accent"]))
        p.drawRoundedRect(rect, 23, 23)
        p.setPen(QColor(t["accent"] if theme_name == "Dark" else t["accent_hover"]))
        p.drawText(rect, Qt.AlignCenter, text)
        x += tw + 10
    p.end()
    base = to_pil(canvas)

    # По центру — окно в лёгкой перспективе, со скруглением и тенью
    shot_w = 1020
    shot = shot.resize((shot_w, int(shot.height * shot_w / shot.width)), Image.LANCZOS)
    mask = Image.new("L", shot.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, *shot.size], radius=18, fill=255)
    shot.putalpha(mask)
    # тонкая рамка: в тёмной теме край окна иначе сливается с фоном
    edge = (255, 255, 255, 46) if theme_name == "Dark" else (0, 0, 0, 34)
    ImageDraw.Draw(shot).rounded_rectangle([0, 0, shot.width - 1, shot.height - 1], radius=18, outline=edge, width=2)
    sw, sh = shot.size
    lift = 46  # левый край «дальше» — правый «ближе»
    src = [(0, 0), (sw, 0), (sw, sh), (0, sh)]
    dst = [(0, lift), (sw, 0), (sw, sh), (0, sh - lift)]
    shot = shot.transform(shot.size, Image.PERSPECTIVE, _perspective(dst, src), Image.BICUBIC)
    px, py = (width - sw) // 2, 330
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    shadow_mask = Image.new("L", base.size, 0)
    ImageDraw.Draw(shadow_mask).polygon([(px + a + 18, py + b + 26) for a, b in dst],
                                        fill=150 if theme_name == "Dark" else 90)
    shadow.putalpha(shadow_mask.filter(ImageFilter.GaussianBlur(28)))
    base.alpha_composite(shadow)
    base.alpha_composite(shot, (px, py))

    # По бокам — маскоты: девушка слева, её собака (с прежней иконки) справа,
    # обе сидят перед окном. В тёмной теме — мятное свечение, иначе чёрное
    # худи и волосы сливаются с фоном.
    for name, h, left in (("girl", 700, True), ("dog", 540, False)):
        im = Image.open(OUT / f"mascot-{name}.png").convert("RGBA")
        im = im.resize((round(im.width * h / im.height), h), Image.LANCZOS)
        pad = 60
        layer = Image.new("RGBA", (im.width + 2 * pad, im.height + 2 * pad), (0, 0, 0, 0))
        layer.alpha_composite(im, (pad, pad))
        if theme_name == "Dark":
            halo = layer.split()[3].point(lambda v: 255 if v > 60 else 0)
            halo = halo.filter(ImageFilter.MaxFilter(17)).filter(ImageFilter.GaussianBlur(20)).point(lambda v: int(v * 0.45))
            tint = Image.new("RGBA", layer.size, t["accent"])
            tint.putalpha(halo)
            tint.alpha_composite(layer)
            layer = tint
        x = 40 - pad if left else width - im.width - 40 - pad
        base.alpha_composite(layer, (x, height - im.height - 18 - pad))
    base.convert("RGB").save(OUT / f"hero-{theme_name.lower()}.png", optimize=True)


def _perspective(pa, pb):
    """Коэффициенты Image.PERSPECTIVE: точки pb исходника → pa результата
    (система 8×8, метод Гаусса — numpy ради одной картинки не тянем)."""
    rows = []
    for (x, y), (u, v) in zip(pa, pb):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y, u])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y, v])
    n = 8
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(rows[r][col]))
        rows[col], rows[pivot] = rows[pivot], rows[col]
        for r in range(n):
            if r != col:
                k = rows[r][col] / rows[col][col]
                rows[r] = [a - k * b for a, b in zip(rows[r], rows[col])]
    return [rows[i][n] / rows[i][i] for i in range(n)]


# ── Анимации ────────────────────────────────────────────────────────────────

class Recorder:
    """Кадры окна через равные промежутки; одинаковые подряд — один кадр подольше."""

    def __init__(self, widget, step_ms=110, width=1100):
        self.widget, self.step, self.width = widget, step_ms, width
        self.frames, self.durations = [], []

    def tick(self, n=1):
        for _ in range(n):
            QTest.qWait(self.step)
            img = grab(self.widget).convert("RGB")
            img = img.resize((self.width, int(img.height * self.width / img.width)), Image.LANCZOS)
            if self.frames and img.tobytes() == self.frames[-1].tobytes():
                self.durations[-1] += self.step
            else:
                self.frames.append(img)
                self.durations.append(self.step)

    def type(self, edit, text, per_char=2):
        for ch in text:
            QTest.keyClicks(edit, ch)
            self.tick(per_char)

    def key(self, edit, key, after=4):
        QTest.keyClick(edit, key)
        self.tick(after)

    def save(self, path: Path):
        self.durations[-1] += 1500  # пауза перед повтором
        self.frames[0].save(path, save_all=True, append_images=self.frames[1:],
                            duration=self.durations, loop=0, quality=82, method=6)


def demo_filter(theme_name: str):
    """Подсказки при наборе и фильтр на лету: только ошибки → ошибки и предупреждения."""
    w = make_window(theme_name, (1280, 640))
    f = w.filter_input
    f.setFocus()
    r = Recorder(w)
    r.tick(10)
    r.type(f, "le")
    r.tick(6)
    r.key(f, Qt.Key_Tab, 8)            # level:  → список уровней
    r.key(f, Qt.Key_Tab, 16)           # level:error  → остались только ошибки
    r.type(f, "OR le")
    r.key(f, Qt.Key_Tab, 6)            # level:
    r.type(f, "w")
    r.tick(5)
    r.key(f, Qt.Key_Tab, 22)           # level:warn  → плюс предупреждения
    r.save(OUT / f"demo-filter-{theme_name.lower()}.webp")
    close(w)


def demo_panel(theme_name: str):
    w = make_window(theme_name, (1280, 640), panel=True)
    w.btn_delta.setChecked(True)
    r = Recorder(w)
    _cursor_to_line(w, "af_ad_revenue")
    r.tick(14)
    _cursor_to_line(w, "INTERNET_CHECKER")
    r.tick(14)
    w.side_panel.setCurrentWidget(w.side_panel.watch_page)
    r.tick(4)
    for expr in ("revenue OR adrevenue", "is_tester", "level:error"):
        w.side_panel.watch_page.add_expression(expr)
        r.tick(6)
    w.chk_auto_scroll.setChecked(True)
    for i in range(6):  # логи идут: «×N» растёт, счётчики отслеживания тоже
        from datetime import datetime
        _feed(w, [_line(datetime.now(), *_CHECKER)])
        if i % 2:
            _feed(w, [_line(datetime.now(), "MyGame(UnityFramework)[2438]", "Notice",
                            '[AppsFlyer] sendEvent af_ad_revenue {"af_revenue":0.0123,"af_currency":"USD"}')])
        w.side_panel.watch_page.refresh()
        r.tick(7)
    r.tick(10)
    r.save(OUT / f"demo-panel-{theme_name.lower()}.webp")
    close(w)


# ── Скриншоты ───────────────────────────────────────────────────────────────

def tools_shot(theme_name: str):
    w = make_window(theme_name)
    w._open_tools()
    QTest.qWait(80)
    grab(w.tools_window).convert("RGB").save(OUT / f"tools-{theme_name.lower()}.png", optimize=True)
    close(w)


def tour_shot(theme_name: str):
    w = make_window(theme_name, (1280, 720))
    w.start_tour()
    tour = w._tour
    tour.go([s.title for s in tour.steps].index("Подсказки"))
    w.filter_input.setFocus()
    QTest.keyClicks(w.filter_input, "proc:my")
    QTest.qWait(400)
    grab(w).convert("RGB").save(OUT / f"tour-{theme_name.lower()}.png", optimize=True)
    tour.stop()
    close(w)


ICONS = ["phone", "gamepad", "search", "history", "panel_right", "flag", "toolbox", "bug", "help"]


def feature_icons():
    """Иконки для сетки возможностей: мятные на прозрачном — читаются в обеих темах."""
    apply_theme(app, "Dark")
    for name in ICONS:
        pm = icons._pixmap(name, "#1DB97A", 96)
        to_pil(pm.toImage()).save(OUT / f"icon-{name}.png", optimize=True)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    feature_icons()
    for name in THEMES:
        print(f"[{name}] шапка…", flush=True)
        hero(name)
        print(f"[{name}] скриншоты…", flush=True)
        tools_shot(name)
        tour_shot(name)
        print(f"[{name}] анимации…", flush=True)
        demo_filter(name)
        demo_panel(name)
    for path in sorted(OUT.iterdir()):
        print(f"{path.name:28s} {path.stat().st_size // 1024:6d} КБ")


if __name__ == "__main__":
    main()
