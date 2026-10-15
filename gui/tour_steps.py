"""Шаги обучения и демо-логи для него (gui/tour.py)."""
from datetime import datetime, timedelta
from typing import List

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtTest import QTest

from core.crash_alerts import CrashReport
from gui.tour import Step

_DEV = "iPhone-QA"
_GAME = "MyGame(UnityFramework)[2438]"

_DEMO = [
    ("SpringBoard(FrontBoard)[58]", "Notice", "[app<com.example.mygame>] Bootstrap complete"),
    (_GAME, "Notice", "[LogType:Log] UCM: consent window shown (GDPR region)"),
    (_GAME, "Notice", "[LogType:Log] UCM: user consent = granted, ATT = authorized"),
    (_GAME, "Notice", '[AppsFlyer] sendEvent af_login {"af_customer_user_id":"7f3a-21","is_tester":true}'),
    (_GAME, "Notice", "[INTERNET_CHECKER] AVAILABLE:True; isTimeout:False; ping:True; head:False; mainCdn:True; reserveCdn:False"),
    (_GAME, "Notice", "[LogType:Log] Loading level 3 (bundle: levels_main)"),
    (_GAME, "Notice", "[LogType:Warning] Texture atlas 'ui_old' is deprecated"),
    ("kernel[0]", "Notice", "memorystatus: MyGame pid 2438 [jetsam] 812MB"),
    (_GAME, "Error", "Failed to fetch remote config: timeout after 10s"),
    (_GAME, "Notice", '[AppsFlyer] sendEvent af_ad_revenue {"af_revenue":0.0123,"af_currency":"USD",'
                      '"ad_network":"AppLovin","placement":{"type":"rewarded","id":"main_menu"}}'),
    (_GAME, "Notice", "[Firebase] Logging event: origin, name, params: app, ad_impression, {value: 0.0123}"),
    (_GAME, "Notice", "[LogType:Exception] NullReferenceException: Object reference not set\n"
                      "  at ShopWindow.OnBuyClicked () [0x00012] in ShopWindow.cs:88"),
    (_GAME, "Debug", "[AppLovin MAX] Interstitial loaded: ad unit 9f2c"),
    (_GAME, "Notice", '[AppsFlyer] sendEvent af_purchase {"af_revenue":2.99,"af_content_id":"no_ads","af_currency":"USD"}'),
    ("backboardd(CoreBrightness)[64]", "Notice", "Lux 120.5 nits 300 ramping"),
]
_CHECKER = _DEMO[4]


_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def _line(when: datetime, proc: str, level: str, text: str) -> str:
    # месяц — по-английски, как в настоящем syslog (strftime после запуска Qt дал бы «окт»)
    return f"{_MONTHS[when.month - 1]} {when.day:2d} {when:%H:%M:%S} {_DEV} {proc} <{level}>: {text}"


def _feed(mw, raws):
    mw._on_blocks_processed([{"raw": r, "props": mw.filter_obj.extract_props(r)} for r in raws])


def load_demo(mw):
    start = datetime.now() - timedelta(seconds=95)
    raws, t = [], start
    for i, (proc, level, text) in enumerate(_DEMO):
        t += timedelta(seconds=[2, 1, 3, 5, 4, 2, 1, 7, 3, 2][i % 10])
        raws.append(_line(t, proc, level, text))
        if i in (4, 7):  # проверка интернета повторяется — пример для «×N»
            for _ in range(3):
                t += timedelta(seconds=10)
                raws.append(_line(t, *_CHECKER))
    _feed(mw, raws)


def demo_feed_timer(mw) -> QTimer:
    """Демо-логи «идут» и во время обучения: повтор проверки интернета (×N)."""
    load_demo(mw)
    timer = QTimer(mw)
    timer.timeout.connect(lambda: _feed(mw, [_line(datetime.now(), *_CHECKER)]))
    timer.start(5000)
    return timer


# ── Помощники для «Авто» ────────────────────────────────────────────────────

def _typing(widget, text: str, start: int = 600, per_char: int = 140) -> list:
    actions = [(start - 100, lambda: (widget.setFocus(), widget.clear()))]
    for i, ch in enumerate(text):
        actions.append((start + i * per_char, lambda ch=ch: QTest.keyClicks(widget, ch)))
    return actions


def _key(widget, key, at: int, modifier=Qt.NoModifier) -> tuple:
    return at, lambda: QTest.keyClick(widget, key, modifier)


def _cursor_to_line(mw, needle: str):
    doc = mw.log_display.document()
    block = doc.begin()
    while block.isValid():
        if needle in block.text():
            mw.chk_auto_scroll.setChecked(False)
            mw.log_display.setTextCursor(QTextCursor(block))
            mw.log_display.centerCursor()
            return
        block = block.next()


def _tool(mw, attr: str):
    return getattr(mw.tools_window, attr, None) if mw.tools_window else None


_DEMO_CRASH = CrashReport("/MyGame-демо.ips", "MyGame (демо)", "Новый краш: MyGame (демо)")


def _demo_toast(mw):
    """Демо-карточка — каждый раз, как заходим на шаг, и не исчезает сама, пока
    шаг открыт (настоящие проходят через защиту от повторов и прячутся за 8 с)."""
    toast = next((t for t in mw.crash_alerts.toasts if t.report is _DEMO_CRASH and t.isVisible()), None)
    return toast or mw.crash_alerts.show_toast(_DEMO_CRASH, sticky=True)


def _hide_demo_toast(mw):
    for toast in list(mw.crash_alerts.toasts):
        if toast.report is _DEMO_CRASH:
            toast.dismiss()


def build_steps(mw) -> List[Step]:
    f = mw.filter_input

    def reset_filter():
        f.hide_popup()
        f.clear()
        mw._apply_filter(remember=False)

    steps = [
        Step("LogDog — короткое обучение",
             "Покажу, где что, на демо-логах игры. Ваши настоящие логи, фильтр и настройки "
             "отложены и вернутся, когда обучение закончится.<br><br>"
             "Листать — «Далее» или ← →, выйти — Esc. «▶ Авто» — шаги пойдут сами и покажут действия."),
        Step("Источник логов",
             "<b>iOS Syslog</b> — системные логи iPhone по USB. <b>Unity TCP</b> — полные логи Unity-игры "
             "на iPhone по USB или Wi-Fi: в системном логе строки игры часто скрыты как «&lt;private&gt;». "
             "В режиме Unity выберите в списке iPhone по USB — LogDog дождётся игры и поймает "
             "логи с самого её запуска.",
             target=lambda: mw.mode_combo),
        Step("Устройство",
             "Подключите iPhone по USB и выберите его здесь — логи пойдут сразу. Если кабель выдернут, "
             "внизу станет «Нет связи — жду», а после подключения логи продолжатся сами.",
             target=lambda: mw.device_combo if mw.device_combo.isVisible() else mw.unity_combo),
        Step("Логи",
             "Цвет — уровень: ошибки, предупреждения, информация, отладка. Уровень определяется и по "
             "тексту: <code>Exception</code>, <code>Failed</code>, <code>timeout</code> — ошибка, даже если "
             "Unity прислала строку как Info.",
             target=lambda: mw.log_display),
        Step("Фильтр",
             "Фильтр применяется сам, как только перестали печатать. Поля: <code>level:</code>, "
             "<code>proc:</code>, <code>pid:</code>, <code>text:</code>; связки <code>AND</code> / "
             "<code>OR</code> / <code>NOT</code>, скобки. Несколько слов подряд — строки со всеми словами.",
             target=lambda: f, try_hint="введите <code>level:error</code>",
             done=lambda: mw.filter_obj.filter_text.lower().startswith("level:e"),
             demo=_typing(f, "level:error"), leave=reset_filter, also=lambda: [f.popup], reserve_below=290),
        Step("Подсказки",
             "Пока печатаете — список, как в редакторе кода: поля, AND/OR, уровни, имена процессов из "
             "полученных логов. ↑ ↓ — выбрать, Enter или Tab — вставить, Ctrl+Space — все варианты.",
             target=lambda: f, try_hint="наберите <code>proc:a</code> и нажмите Tab",
             done=lambda: f.text().lower().startswith("proc:art"),
             demo=_typing(f, "proc:a") + [_key(f, Qt.Key_Tab, 2600)], leave=reset_filter,
             also=lambda: [f.popup], reserve_below=290),
        Step("Ошибки в фильтре",
             "Ошибка подчёркивается, а через секунду под полем появляется объяснение. Пока она есть, "
             "действует прежний фильтр — логи не пропадают из-за недописанной скобки.",
             target=lambda: f, demo=_typing(f, "(level:fatal"), leave=reset_filter,
             also=lambda: [f.popup], reserve_below=290),
        Step("История фильтров",
             "Значок часов в поле фильтра — последние 50 фильтров. Щелчок — применить, крестик слева "
             "от фильтра — удалить. В историю попадает фильтр после Enter или когда уходите из поля.",
             target=lambda: f),
        Step("Поиск по логам — Ctrl+F",
             "Поиск ничего не скрывает: подсвечивает совпадения и переходит между ними — ↓ ↑, Enter или F3.",
             target=lambda: mw.find_bar,
             enter=lambda: mw.find_bar.show(),
             demo=_typing(mw.find_bar.input, "revenue") + [_key(mw.find_bar.input, Qt.Key_Down, 2400),
                                                            _key(mw.find_bar.input, Qt.Key_Down, 3400)],
             try_hint="найдите <code>revenue</code> и нажмите ↓",
             leave=lambda: mw.find_bar.hide()),
        Step("Пауза",
             "Замораживает экран, чтобы спокойно читать. Логи при этом не теряются: всё пришедшее "
             "за паузу появится после неё.",
             target=lambda: mw.btn_pause),
        Step("Маркер шага — Ctrl+M",
             "Строка «══ Название ══» с вашим текстом: в длинном логе видно, где начался шаг теста. "
             "Фильтр маркеры не скрывает.",
             target=lambda: mw.btn_marker, try_hint="нажмите Ctrl+M и назовите шаг",
             done=lambda: mw._markers > 0,
             demo=[(1500, lambda: mw.insert_marker("Покупка No Ads")),
                   (1600, lambda: mw._scroll_to_bottom())]),
        Step("Повторы — одной строкой",
             "Одинаковые строки подряд (время не сравнивается) показываются одной с «×N» — "
             "как проверка интернета в демо-логах. Кнопка включает и выключает.",
             target=lambda: mw.btn_collapse,
             enter=lambda: (mw.chk_auto_scroll.setChecked(True), mw._scroll_to_bottom())),
        Step("Время между строками",
             "Колонка слева — сколько прошло с предыдущей строки: <code>+7с</code>, <code>+1м05с</code>. "
             "В текст и копирование не попадает.",
             target=lambda: mw.btn_delta,
             demo=[(1200, lambda: mw.btn_delta.setChecked(True))]),
        Step("Подробности строки",
             "Панель справа: строка под курсором разобрана — уровень, время, процесс; JSON — деревом, "
             "пары <code>ключ:значение</code> — таблицей.",
             target=lambda: mw.side_panel,
             enter=lambda: (mw.btn_panel.setChecked(True),
                            mw.side_panel.setCurrentWidget(mw.side_panel.details),
                            _cursor_to_line(mw, "af_ad_revenue"))),
        Step("Отслеживание",
             "Что ищете в логах — словами или выражением, например <code>revenue OR adrevenue</code>: "
             "сколько раз встретилось и когда последний раз, по всем логам независимо от фильтра. "
             "Двойной щелчок — к последнему совпадению.",
             target=lambda: mw.side_panel,
             enter=lambda: mw.side_panel.setCurrentWidget(mw.side_panel.watch_page),
             demo=[(1200, lambda: mw.side_panel.watch_page.add_expression("revenue OR adrevenue")),
                   (2400, lambda: mw.side_panel.watch_page.add_expression("is_tester"))],
             try_hint="добавьте <code>af_purchase</code>",
             done=lambda: any("purchase" in r.expression for r in mw._watch.rules)),
        Step("Подсветка слов",
             "Нужное слово заливается цветом во всех логах. Быстрее всего — выделить слово в логах и "
             "в меню по правой кнопке выбрать «Подсветить»; там же «Отслеживать».",
             target=lambda: mw.side_panel,
             enter=lambda: mw.side_panel.setCurrentWidget(mw.side_panel.highlights_page),
             demo=[(1200, lambda: mw.side_panel.highlights_page.add_rule("af_ad_revenue", "#F2C94C")),
                   (2200, lambda: mw.side_panel.highlights_page.add_rule("UCM", "#6FCF97"))],
             leave=lambda: mw.btn_panel.setChecked(False)),
        Step("Сохранить и открыть",
             "Сохранить логи в файл и открыть сохранённый — с тем же фильтром, поиском и подсветкой. "
             "Копировать строки — выделить и Ctrl+C.",
             target=lambda: mw.btn_open),
        Step("Строка состояния",
             "Внизу: идут ли логи («Логи идут» / «Нет связи — жду») и сколько показано из полученного.",
             target=lambda: mw.status_bar),
        Step("Инструменты iPhone",
             "Отдельное окно для подключённого iPhone. Карточки активны, когда iPhone подключён в режиме iOS.",
             target=lambda: mw.btn_tools),
        Step("Приложения и «Данные игры»",
             "Список приложений с иконками и версиями. Для игры из TestFlight — «Данные игры»: "
             "<b>очистить данные без переустановки</b> (игра стартует как в первый раз), скачать папку "
             "игры и лог Unity. Там же — удалить приложение.",
             target=lambda: _tool(mw, "btn_app_list"), enter=lambda: mw._open_tools()),
        Step("Установить .ipa",
             "Перед установкой LogDog покажет версию и профиль и сразу скажет, если сборка не встанет: "
             "UDID iPhone нет в профиле, профиль истёк, нужна новее iOS. .ipa можно перетащить на это окно.",
             target=lambda: _tool(mw, "btn_install_ipa"), enter=lambda: mw._open_tools()),
        Step("Краш-отчёты",
             "Выгрузка .ips с поиском по приложению: оригинал и читаемый .log.",
             target=lambda: _tool(mw, "btn_crash_reports"), enter=lambda: mw._open_tools()),
        Step("Язык, перезагрузка, профили",
             "Сменить язык и регион iPhone, перезагрузить или выключить, посмотреть профили подготовки "
             "(кто подписал сборки и до какого числа) и конфигурационные (прокси, VPN), сбросить "
             "сопряжение, если iPhone виден, но не подключается.",
             target=lambda: _tool(mw, "btn_language"), enter=lambda: mw._open_tools(),
             leave=lambda: mw.tools_window.hide() if mw.tools_window else None),
        Step("Уведомление о краше",
             "Пока iPhone подключён, о новом краше скажет карточка справа вверху: сама исчезает и не "
             "мешает. «Скачать» — сохранить отчёт. Если что-то падает раз за разом, на карточке растёт "
             "счётчик, а от надоедливого процесса можно отписаться кнопкой «Не показывать от …» "
             "(вернуть — в Настройках). Сам LogDog ничего не скрывает.",
             target=lambda: _demo_toast(mw),
             leave=lambda: _hide_demo_toast(mw)),
        Step("Настройки",
             "Тема (тёмная / светлая), размер шрифта логов, свои цвета уровней.",
             target=lambda: mw.btn_settings),
        Step("Справка",
             "Справка по всему, что здесь есть, и это обучение — всегда по этой кнопке.",
             target=lambda: mw.btn_help),
        Step("Готово",
             "Это всё. Ваши логи и настройки сейчас вернутся. Удачных проверок!"),
    ]
    return steps
