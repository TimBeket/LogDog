from PySide6.QtWidgets import QDialog, QVBoxLayout, QTextBrowser, QPushButton, QHBoxLayout
from PySide6.QtCore import QUrl
from PySide6.QtGui import QTextDocument
from core.version import VERSION
from gui import icons, theme

# иконки кнопок в тексте справки — те же, что в окне (gui/icons.py)
_ICONS = ["pause", "save", "trash", "toolbox", "settings", "help", "history", "close",
          "flag", "folder", "layers", "clock", "panel_right",
          "phone", "gamepad", "info", "apps", "package", "bug", "code", "search",
          "globe", "power", "shield", "profile", "link", "bell"]


def _img(name: str, size: int = 18) -> str:
    return f'<img src="icon://{name}" width="{size}" height="{size}" style="vertical-align: middle;">'

class HelpDialog(QDialog):
    """Полная справка по LogDog — режимы, фильтры, цвета, кнопки."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Справка по LogDog {VERSION}")
        self.setFixedSize(680, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)

        text_browser = QTextBrowser()
        doc = text_browser.document()
        for name in _ICONS:
            doc.addResource(QTextDocument.ImageResource, QUrl(f"icon://{name}"),
                            icons.pixmap(name, theme.tokens()["accent"], 18).toImage())
        text_browser.setHtml(self._build_html())
        text_browser.setOpenExternalLinks(True)  # Allow clicking links
        layout.addWidget(text_browser)

        btn_layout = QHBoxLayout()
        tour_btn = QPushButton("Пройти обучение")
        tour_btn.setToolTip("Пошаговый показ на демо-логах; ваши логи и настройки вернутся после")
        tour_btn.clicked.connect(self._start_tour)
        btn_layout.addWidget(tour_btn)
        close_btn = QPushButton("Понятно")
        close_btn.setProperty("variant", "primary")
        close_btn.clicked.connect(self.accept)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    def _start_tour(self):
        self.accept()
        if self.parent() is not None and hasattr(self.parent(), "start_tour"):
            self.parent().start_tour()

    def _build_html(self) -> str:
        t = theme.tokens()
        log = theme.LOG_COLORS[theme.current()]
        return f"""
<style>
    body {{ font-size: 13px; line-height: 1.5; color: {t['text']}; }}
    h2 {{ font-size: 17px; margin-top: 18px; color: {t['accent']}; }}
    h3 {{ margin-top: 12px; margin-bottom: 4px; font-size: 14px; }}
    ul {{ margin: 2px 0 6px 18px; padding: 0; }}
    li {{ margin-bottom: 2px; }}
    code {{ background-color: {t['window']}; padding: 1px 6px; border-radius: 3px; font-size: 12px; color: {t['text']}; }}
    table {{ border-collapse: collapse; width: 100%; margin: 6px 0; }}
    td, th {{ border: 1px solid {t['border']}; padding: 6px 8px; text-align: left; vertical-align: top; }}
    th {{ background-color: {t['window']}; font-size: 12px; }}
    .key {{ display: inline-block; background: {t['window']}; border: 1px solid {t['border']}; border-radius: 3px; padding: 1px 6px; font-size: 12px; color: {t['text']}; }}
    .tag {{ display: inline-block; padding: 1px 6px; border-radius: 3px; font-weight: bold; font-size: 11px; }}
    .tip {{ background-color: {t['accent_soft']}; padding: 8px 12px; margin: 12px 0; color: {t['text']}; }}
    th {{ color: {t['muted']}; }}
    .color-row {{ margin: 3px 0; }}
</style>

<h2>Быстрый старт</h2>
<ol>
    <li><b>Выберите режим</b> в левом верхнем углу: {_img("phone", 16)} <b>iOS Syslog</b> — системные логи iPhone/iPad, {_img("gamepad", 16)} <b>Unity TCP</b> — полные логи Unity-игры на iPhone по USB или Wi-Fi (в системном логе iOS строки игры часто скрыты как &lt;private&gt;).</li>
    <li><b>Подключитесь:</b>
        <ul>
            <li><b>iOS</b> — подключите устройство по USB и выберите его в списке, логи пойдут сразу;</li>
            <li><b>Unity</b> — введите IP устройства в поле <b>IP</b> и нажмите «Подключиться».</li>
        </ul>
    </li>
    <li><b>Найдите нужное:</b> введите фильтр в поле вверху (например, <code>level:error</code>) — он применится сам, или ищите по логам через <b>Ctrl+F</b>.</li>
</ol>
<p>Статус подключения виден в строке состояния внизу окна.</p>

<hr>

<h2>Подключение</h2>

<h3>iOS Syslog</h3>
<ul>
    <li><b>Windows:</b> установите <a href="https://apps.microsoft.com/detail/9np83lwlpz9k">Apple Devices</a> из Microsoft Store</li>
    <li><b>Linux:</b> установите пакет <code>usbmuxd</code> (apt/pacman/dnf) и запустите <code>sudo systemctl start usbmuxd</code></li>
    <li><b>macOS:</b> ничего дополнительно ставить не нужно</li>
</ul>

<h3>Unity TCP</h3>
<p>Зачем: в системном логе iOS строки Unity-игры часто скрыты как <code>&lt;private&gt;</code>. Режим Unity TCP подключается к самой игре на iPhone и получает её логи целиком — <b>по USB</b> (проще всего: ни Wi-Fi, ни брандмауэр не нужны) или по Wi-Fi.</p>
<ul>
    <li>Компьютер с LogDog и устройство с игрой — <b>в одной сети</b> (Wi-Fi/LAN)</li>
    <li><b>Чтобы поймать логи с самого запуска</b>: подключите iPhone по USB и выберите его в списке (если он один — выберется сам). LogDog ждёт игру и подключается сразу, как она запустилась; перезапуск игры — подключится снова сам</li>
    <li>В том же списке — игры, найденные в Wi-Fi, IP прошлого раза и «Ввести IP вручную…». Кнопка рядом со списком — отключиться</li>
    <li>Билд Unity — только <b>Development Build</b> (File → Build Settings → ☑ Development Build). Релизный билд <b>не работает</b>: Unity не открывает порт для логов</li>
    <li>IP устройства на iOS: Настройки → Wi-Fi → ваша сеть → <b>IP-адрес</b></li>
    <li>Порт искать не нужно: запущенная игра сама сообщает его в сеть, LogDog его слышит и запоминает. Нужен конкретный порт — введите <code>IP:порт</code>, например <code>192.168.1.5:55123</code></li>
    <li>Игра не находится? Брандмауэр компьютера может не пропускать сообщения игры — разрешите LogDog входящий UDP-порт <code>54997</code>. Без них LogDog один раз переберёт порты <code>55000–55511</code> при нажатии «Подключиться»; если игру потом перезапустили — нажмите «Подключиться» ещё раз</li>
</ul>

<hr>

<h2>Раскраска логов</h2>
<p>LogDog определяет уровень каждой строки и подсвечивает её цветом (цвета меняются в настройках):</p>
<table>
    <tr><th>Уровень</th><th>Примеры</th></tr>
    <tr><td><b style="color:{log['error']}">■</b>&nbsp; Error / Fault / Fatal</td><td>&lt;Error&gt;, &lt;Fault&gt;</td></tr>
    <tr><td><b style="color:{log['warn']}">■</b>&nbsp; Warning / Warn</td><td>&lt;Warning&gt;, &lt;Warn&gt;</td></tr>
    <tr><td><b style="color:{log['info']}">■</b>&nbsp; Info / Notice</td><td>&lt;Info&gt;, &lt;Notice&gt;</td></tr>
    <tr><td><b style="color:{log['debug']}">■</b>&nbsp; Debug / Trace</td><td>&lt;Debug&gt;</td></tr>
</table>
<p>Строки с <code>Exception</code>, <code>NullReference</code>, <code>Crash</code>, <code>Failed</code>, <code>Assertion</code> и т.п. считаются <b>ошибками</b>, даже если Unity прислала их как Info.</p>

<hr>

<h2>Фильтр</h2>
<p>Поле <b>«Фильтр»</b> вверху окна. Фильтр применяется сам, как только вы перестали печатать, — ко всем уже полученным логам и к новым. <b>Enter</b> — применить сразу и сохранить в историю. Пока в фильтре ошибка, действует предыдущий.</p>

<h3>Простой поиск</h3>
<table>
    <tr><th>Вводите</th><th>Найдёт</th></tr>
    <tr><td><code>Applovin</code></td><td>Все строки с "Applovin"</td></tr>
    <tr><td><code>crash</code></td><td>Все строки с "crash" (без учёта регистра)</td></tr>
    <tr><td><code>Failed to fetch</code></td><td>Строки, где есть все три слова (слова подряд — это AND)</td></tr>
    <tr><td><code>Exception:</code></td><td>Текст с двоеточием ищется как есть</td></tr>
</table>

<h3>Поиск по полям</h3>
<table>
    <tr><th>Поле</th><th>Пример</th><th>Что ищет</th></tr>
    <tr><td><code>level</code></td><td><code>level:error</code></td><td>Уровень: error, warn, info, debug</td></tr>
    <tr><td><code>proc</code></td><td><code>proc:SpringBoard</code></td><td>Имя процесса (подстрока); с подсистемой — как в логе: <code>proc:MyGame(UnityFramework)</code></td></tr>
    <tr><td><code>pid</code></td><td><code>pid:1234</code></td><td>Точный ID процесса</td></tr>
    <tr><td><code>text</code></td><td><code>text:"network"</code></td><td>Текст строки (то же, что просто ввод)</td></tr>
</table>

<h3>Логические операторы и скобки</h3>
<table>
    <tr><th>Выражение</th><th>Что найдёт</th></tr>
    <tr><td><code>level:error AND proc:MyApp</code></td><td>Ошибки только из MyApp</td></tr>
    <tr><td><code>level:error OR level:warn</code></td><td>Ошибки и предупреждения</td></tr>
    <tr><td><code>NOT level:debug</code></td><td>Всё, кроме отладки</td></tr>
    <tr><td><code>(level:error OR level:warn) AND NOT proc:System</code></td><td>Проблемы не от System</td></tr>
</table>

<h3>Точные фразы</h3>
<table>
    <tr><th>Вводите</th><th>Найдёт</th></tr>
    <tr><td><code>text:"Has user consent"</code></td><td>Строки с точной фразой</td></tr>
    <tr><td><code>"NullReferenceException"</code></td><td>Строки с точным названием исключения</td></tr>
</table>

<h3>Подсказки и проверка</h3>
<p>Поле подсвечивает поля, значения и операторы, а ошибки подчёркивает и объясняет справа (незакрытая скобка, несуществующий уровень, <code>and</code> строчными — это оператор).</p>
<ul>
    <li>Пока печатаете, под полем появляется список подсказок, как в редакторе кода: <b>↑ / ↓</b> — выбрать, <b>Enter</b> или <b>Tab</b> — вставить, <b>Esc</b> — закрыть. <b>Ctrl+Space</b> — все варианты для этого места</li>
    <li>После <code>proc:</code> подсказываются имена процессов из уже полученных логов</li>
</ul>

<h3>История фильтров</h3>
<p>Значок {_img("history", 16)} в правой части поля — последние 50 фильтров. Клик — применить, {_img("close", 14)} слева от фильтра — удалить из истории.</p>

<hr>

<h2>Поиск по логам (Ctrl+F)</h2>
<p>В отличие от фильтра, поиск ничего не скрывает — он подсвечивает совпадения и переходит между ними:</p>
<ul>
    <li><b>↓</b>, <b>Enter</b> или <b>F3</b> — следующее совпадение; <b>↑</b>, <b>Shift+Enter</b> или <b>Shift+F3</b> — предыдущее</li>
    <li><b>Esc</b> — закрыть поиск</li>
</ul>

<hr>

<h2>Кнопки</h2>
<table>
    <tr><td width="36" align="center">{_img("pause")}</td><td>Пауза: экран замирает, новые логи копятся и появятся после паузы</td></tr>
    <tr><td width="36" align="center">{_img("flag")}</td><td>Маркер шага (<b>Ctrl+M</b>): строка «══ Покупка No Ads ══» с вашим названием; фильтр её не скрывает</td></tr>
    <tr><td width="36" align="center">{_img("trash")}</td><td>Очистить окно логов</td></tr>
    <tr><td width="36" align="center">{_img("save")}</td><td>Сохранить логи в <code>.log</code> файл</td></tr>
    <tr><td width="36" align="center">{_img("folder")}</td><td>Открыть сохранённый лог — с тем же фильтром, поиском и подсветкой</td></tr>
    <tr><td width="36" align="center">{_img("layers")}</td><td>Схлопывать одинаковые строки подряд (время не сравнивается): одна строка с «×37»</td></tr>
    <tr><td width="36" align="center">{_img("clock")}</td><td>Колонка слева: сколько прошло с предыдущей строки (<code>+7с</code>); в текст и копирование не попадает</td></tr>
    <tr><td width="36" align="center">{_img("panel_right")}</td><td>Панель справа: подробности строки, отслеживание, подсветка (см. ниже)</td></tr>
    <tr><td width="36" align="center">{_img("toolbox")}</td><td>Инструменты для iOS-устройства (см. ниже)</td></tr>
    <tr><td width="36" align="center">{_img("settings")}</td><td>Настройки</td></tr>
    <tr><td width="36" align="center">{_img("help")}</td><td>Эта справка (в правом верхнем углу)</td></tr>
</table>
<p>Галочка <b>«Автопрокрутка»</b> вверху — автоматически прокручивать к новым логам.</p>

<h3>Панель справа</h3>
<ul>
    <li><b>Подробности</b> — строка под курсором: уровень, время, процесс, pid; JSON — деревом, пары <code>ключ:значение</code> — таблицей</li>
    <li><b>Отслеживание</b> — что ищете в логах, словами или выражением фильтра (<code>revenue OR adrevenue</code>): сколько раз встретилось и когда последний раз, по всем полученным логам независимо от фильтра. Двойной щелчок — к последнему совпадению</li>
    <li><b>Подсветка</b> — слова заливаются цветом во всех логах. Быстрее — выделить слово и выбрать «Подсветить» в меню по правой кнопке; там же «Отслеживать»</li>
</ul>

<hr>

<h2>Инструменты</h2>
<p>Отдельное окно для работы с подключённым iOS-устройством:</p>
<ul>
    <li>{_img("info", 16)}&nbsp; <b>Информация об устройстве</b> — модель, iOS/билд, UDID, батарея, память</li>
    <li>{_img("apps", 16)}&nbsp; <b>Список приложений</b> — версии и иконки, поиск. Для выбранного приложения:
        <ul>
            <li><b>Данные игры → Очистить данные</b> — игра запустится как после переустановки, но без неё (сохранения, PlayerPrefs, кэш). Работает для сборок из TestFlight и для разработки; приложения из App Store iOS не открывает. Сначала закройте игру на iPhone. Если игра всё же «помнит» прогресс — перезагрузите iPhone.</li>
            <li><b>Данные игры → Скачать папку</b> и <b>Лог Unity</b> (<code>Documents/output.log</code>, если игра его пишет)</li>
            <li><b>Удалить</b> — удалить приложение с iPhone</li>
        </ul>
    </li>
    <li>{_img("package", 16)}&nbsp; <b>Установить .ipa</b> — сначала покажет версию, сборку и профиль и предупредит, если сборка не встанет (UDID нет в профиле, профиль истёк, нужна новее iOS, это сборка для TestFlight). Файл <code>.ipa</code> можно просто перетащить на окно</li>
    <li>{_img("bug", 16)}&nbsp; <b>Краш-отчёты iOS</b> — выгрузка <code>.ips</code> с поиском по приложению; сохраняется оригинал и читаемый <code>.log</code></li>
    <li>{_img("code", 16)}&nbsp; <b>Включить Developer Mode</b> на устройстве</li>
    <li>{_img("globe", 16)}&nbsp; <b>Язык и регион</b> iPhone — для проверки локализации и региональных окон согласия</li>
    <li>{_img("power", 16)}&nbsp; <b>Перезагрузить / выключить</b> iPhone</li>
    <li>{_img("shield", 16)}&nbsp; <b>Профили подготовки</b> — кто подписал сборки и до какого числа (истёкшие — красным)</li>
    <li>{_img("profile", 16)}&nbsp; <b>Конфигурационные профили</b> — сертификат прокси, VPN, MDM</li>
    <li>{_img("link", 16)}&nbsp; <b>Сбросить сопряжение</b> — если iPhone виден, но не подключается: на нём снова спросят «Доверять этому компьютеру?»</li>
</ul>
<p>{_img("bell", 16)}&nbsp; <b>Новые краши</b>: пока iPhone подключён, LogDog сообщает о новых краш-отчётах карточкой справа вверху — она сама исчезает. «Скачать» — сохранить отчёт. Пока карточка на экране, новые краши того же процесса добавляются к ней счётчиком. LogDog сам ничего не скрывает: от процесса, который падает раз за разом, отпишитесь кнопкой «Не показывать от …» (вернуть и выключить уведомления совсем — в Настройках).</p>

<hr>

<h2>Настройки</h2>
<ul>
    <li><b>Тема</b> (тёмная / светлая) и <b>размер шрифта</b></li>
    <li><b>Цвета логов</b> — кликните на цвет, чтобы выбрать свой для каждого уровня; «Сбросить» вернёт цвета темы</li>
    <li><b>Восстанавливать последний фильтр</b> при перезапуске</li>
</ul>

<div class="tip">
    Эту справку можно открыть в любой момент кнопкой {_img("help", 16)} в правом верхнем углу.
</div>
"""
