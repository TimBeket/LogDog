"""Логи Unity Development Build по TCP (Player Connection).

Как находим порт игры, не сканируя сеть без нужды:

1. Порт, указанный явно (`192.168.1.5:55123`), — только он.
2. Анонсы Unity: запущенная игра раз в секунду рассылает UDP-мультикаст
   225.0.0.222 со своим IP и портом — так игры находят Unity Editor и Rider.
   Слушаем их всё время ожидания: перезапущенная игра (с новым портом)
   находится сама.
3. Последний удачный порт для этого IP — одна попытка подключения.
4. Перебор 55000–55511 (из этого диапазона Unity берёт порт) — только раз за
   нажатие «Подключиться» и только если анонсов нет (мультикаст режут
   некоторые Wi-Fi-сети). Постоянный перебор сотен портов системы защиты
   сети принимают за сканирование портов, поэтому сами его не повторяем.
"""
import asyncio
import re
import select
import socket
import struct
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from PySide6.QtCore import QThread, Signal

from transports.base import BaseReader
from utils.logger import logger

MULTICAST_GROUP = "225.0.0.222"
# Порты анонсов в разных версиях Unity (так же их слушает отладчик Unity
# для MonoDevelop/Rider).
MULTICAST_PORTS = (54997, 34997, 57997, 58997)
PLAYER_PORTS = range(55000, 55512)

_SCAN_WORKERS = 32
_SCAN_TIMEOUT_SEC = 0.25
# Сколько ждать анонс перед перебором портов: Unity шлёт его раз в секунду.
_ANNOUNCE_WAIT_SEC = 3.0
_RETRY_INTERVAL_SEC = 3.0

_ANNOUNCE_RE = re.compile(r"\[IP\] (?P<ip>\S+) \[Port\] (?P<port>\d+)")
# название — до конца анонса; по USB за ним сразу идут двоичные данные потока
_PROJECT_RE = re.compile(r"\[ProjectName\] (?P<name>[^\x00\r\n]+)")
_PLATFORM_RE = re.compile(r"\[Id\] (?P<platform>[A-Za-z]+?)(?:Player)?\(")
# Анонс приходит раз в секунду; не было 6 с — игру закрыли
_GAME_TTL_SEC = 6.0

# Текст между двоичными заголовками сообщений Player Connection: печатные
# ASCII и целые UTF-8-последовательности (кириллица в логах игры), от 5 символов.
_TEXT_RUN = re.compile(
    rb"(?:[\x20-\x7E\t\r\n]|[\xC2-\xDF][\x80-\xBF]|[\xE0-\xEF][\x80-\xBF]{2}|[\xF0-\xF4][\x80-\xBF]{3}){5,}"
)
# Начало многобайтного UTF-8-символа, оборванное концом пакета.
_INCOMPLETE_UTF8_TAIL = re.compile(rb"(?:[\xC2-\xF4]|[\xE0-\xF4][\x80-\xBF]|[\xF0-\xF4][\x80-\xBF]{2})\Z")
# Потолок недочитанного хвоста: без него поток без двоичных разделителей копился бы в памяти.
_MAX_PENDING = 64 * 1024


def parse_target(text: str) -> tuple[str, int | None]:
    """'192.168.1.5' -> ('192.168.1.5', None); '192.168.1.5:55123' -> (…, 55123)."""
    text = text.strip()
    host, sep, port = text.rpartition(":")
    if sep and host and port.isdigit() and 0 < int(port) < 65536:
        return host, int(port)
    return text, None


def parse_announce(payload: bytes, source_ip: str) -> tuple[str, int, str] | None:
    """Анонс Unity -> (ip игры, порт Player Connection, название проекта).

    Формат: "[IP] 10.0.0.4 [Port] 55376 [Flags] 3 [Guid] … [Id] AndroidPlayer(…)
    [Debug] 1 [PackageName] … [ProjectName] …". IP из анонса бывает
    недоступным (на iPhone — адрес мобильной сети), поэтому, если он не
    совпадает с отправителем пакета, берём отправителя.
    """
    text = payload.decode("utf-8", errors="replace")
    m = _ANNOUNCE_RE.search(text)
    if not m:
        return None
    port = int(m.group("port"))
    if not 0 < port < 65536:
        return None
    project = _PROJECT_RE.search(text)
    return source_ip or m.group("ip"), port, project.group("name").strip() if project else ""


def extract_text_runs(buffer: bytes) -> tuple[list[str], bytes]:
    """Текстовые куски из потока Player Connection -> (тексты, хвост).

    Хвост — текст, который упирается в конец принятых данных: сообщение
    могло прийти в двух TCP-пакетах, его продолжение склеится со следующим
    пакетом (или хвост отдаётся целиком, когда данных долго нет — flush_tail).
    """
    runs = list(_TEXT_RUN.finditer(buffer))
    if runs:
        last = runs[-1]
        after = buffer[last.end():]
        if (not after or _INCOMPLETE_UTF8_TAIL.fullmatch(after)) and len(buffer) - last.start() < _MAX_PENDING:
            return _decode(runs[:-1]), buffer[last.start():]
    # Текст следующего сообщения может начинаться с разорванного символа.
    broken = _INCOMPLETE_UTF8_TAIL.search(buffer)
    return _decode(runs), broken.group() if broken else b""


def _decode(runs) -> list[str]:
    return [r.group().decode("utf-8", errors="replace") for r in runs]


def flush_tail(tail: bytes) -> list[str]:
    m = _TEXT_RUN.search(tail)
    return [m.group().decode("utf-8", errors="replace")] if m else []


def _is_service_text(text: str) -> bool:
    """Служебные куски протокола, а не логи игры."""
    return text.startswith("USER") or "[Flags]" in text or "[EditorId]" in text


# ── Unity по USB ─────────────────────────────────────────────────────────────
# iPhone по кабелю: порт игры проверяется и логи читаются через usbmux — без
# Wi-Fi, брандмауэра и мультикаста (анонсы игры с iPhone по сети доходят не
# всегда). Перебор портов здесь — по кабелю, а не по сети, его можно делать
# сколько угодно: 512 портов — доли секунды. Проверено на iPhone с dev-сборкой.

try:
    from pymobiledevice3.usbmux import list_devices as _usb_list_devices
    from pymobiledevice3.lockdown import create_using_usbmux as _usb_lockdown
    HAS_USB = True
except ImportError:
    HAS_USB = False

USB_PREFIX = "usb:"
_USB_POLL_SEC = 0.25
_USB_CONNECT_TIMEOUT_SEC = 1.5


async def _usb_device(serial: str):
    for device in await _usb_list_devices():
        if device.serial == serial and device.connection_type == "USB":
            return device
    return None


async def _usb_open_ports(device, ports=PLAYER_PORTS) -> list[int]:
    found: list[int] = []
    gate = asyncio.Semaphore(16)

    async def probe(port):
        async with gate:
            try:
                sock = await asyncio.wait_for(device.connect(port), _USB_CONNECT_TIMEOUT_SEC)
            except Exception:
                return
            found.append(port)
            sock.close()
    await asyncio.gather(*(probe(p) for p in ports))
    return sorted(found)


async def _usb_handshake(device, port: int, seconds: float = 1.5) -> bytes:
    """Первые данные игры: в начале — та же «визитка», что в анонсе по сети."""
    sock = await asyncio.wait_for(device.connect(port), _USB_CONNECT_TIMEOUT_SEC)
    sock.settimeout(0.3)
    data, deadline = b"", time.monotonic() + seconds
    try:
        while time.monotonic() < deadline and b"[ProjectName]" not in data[:2048]:
            try:
                chunk = sock.recv(4096)
            except OSError:
                continue
            if not chunk:
                break
            data += chunk
    finally:
        sock.close()
    return data


async def find_usb_games() -> list[dict]:
    """iPhone, подключённые по USB, и Unity-игры на них. iPhone без
    запущенной игры тоже в списке (port=None): его выбирают заранее, чтобы
    поймать логи игры с самого запуска."""
    games = []
    for device in await _usb_list_devices():
        if device.connection_type != "USB":
            continue
        ports = await _usb_open_ports(device)
        name = ""
        try:
            lockdown = await _usb_lockdown(device.serial)
            name = await lockdown.get_value(None, "DeviceName") or ""
            await lockdown.close()
        except Exception:
            pass
        if not ports:
            games.append({"via": "usb", "serial": device.serial, "device": name, "port": None,
                          "ip": "", "project": "", "platform": "iPhone"})
        for port in ports:
            try:
                data = await _usb_handshake(device, port)
            except Exception:
                data = b""
            start = data.find(b"[IP]")
            announce = parse_announce(data[start:start + 1024], "") if start >= 0 else None
            games.append({"via": "usb", "serial": device.serial, "device": name, "port": port,
                          "ip": announce[0] if announce else "", "project": announce[2] if announce else "",
                          "platform": announce_platform(data[start:start + 1024]) if start >= 0 else "iPhone"})
    return games


def usb_probe(serial: str, port: int) -> bool:
    async def run():
        device = await _usb_device(serial)
        return bool(device and port in await _usb_open_ports(device, [port]))
    try:
        return asyncio.run(run())
    except Exception:
        return False


def usb_scan(serial: str, ports=PLAYER_PORTS) -> list[int]:
    async def run():
        device = await _usb_device(serial)
        return await _usb_open_ports(device, ports) if device else []
    try:
        return asyncio.run(run())
    except Exception:
        return []


def usb_connect(serial: str, port: int) -> socket.socket:
    async def run():
        device = await _usb_device(serial)
        if device is None:
            raise OSError("iPhone не подключён по USB")
        return await asyncio.wait_for(device.connect(port), 5.0)
    return asyncio.run(run())


class AnnounceListener:
    """Слушает UDP-анонсы Unity-игр. Без Qt, опрос — poll()."""

    def __init__(self, target_ip: str | None):
        """target_ip=None — слушать анонсы всех игр в сети (поиск игр)."""
        try:
            self.target_ip = socket.gethostbyname(target_ip) if target_ip else None  # имя → IP
        except OSError:
            self.target_ip = target_ip
        self._sockets: list[socket.socket] = []
        local_ip = self._local_ip_towards(self.target_ip) if self.target_ip else None
        for port in MULTICAST_PORTS:
            sock = self._open(port, local_ip)
            if sock is not None:
                self._sockets.append(sock)
        if not self._sockets:
            logger.warning("Unity announce listener: no multicast port could be opened")

    @staticmethod
    def _local_ip_towards(target_ip: str) -> str | None:
        """Свой адрес в сети игры: в группу вступаем именно на этом интерфейсе
        (по умолчанию ОС выбрала бы любой — например, VPN). UDP connect()
        пакетов не отправляет, только выбирает маршрут."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((target_ip, 9))
                return s.getsockname()[0]
        except OSError:
            return None

    @staticmethod
    def _open(port: int, local_ip: str | None) -> socket.socket | None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            # Тот же порт может слушать Unity Editor или Rider на этом компьютере.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            sock.bind(("", port))
            iface = socket.inet_aton(local_ip) if local_ip else struct.pack("=I", socket.INADDR_ANY)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                            socket.inet_aton(MULTICAST_GROUP) + iface)
            sock.setblocking(False)
            return sock
        except OSError as e:
            logger.debug("Unity announce port %d unavailable: %s", port, e)
            sock.close()
            return None

    def poll(self, timeout: float, raw: bool = False) -> list:
        """Анонсы от target_ip (или всех, если он None) за время timeout
        (может вернуть раньше). raw=True — ещё и текст анонса."""
        if not self._sockets:
            time.sleep(timeout)
            return []
        found = []
        readable, _, _ = select.select(self._sockets, [], [], timeout)
        for sock in readable:
            while True:
                try:
                    payload, (source_ip, _) = sock.recvfrom(4096)
                except (BlockingIOError, InterruptedError):
                    break
                except OSError:
                    break
                announce = parse_announce(payload, source_ip)
                if announce and (self.target_ip is None or self.target_ip in (announce[0], source_ip)):
                    found.append((announce, payload) if raw else announce)
        return found

    def close(self):
        for sock in self._sockets:
            try:
                sock.close()
            except OSError:
                pass
        self._sockets = []


class UnityTCPReader(BaseReader):
    """Connects to a Unity application over TCP socket and cleans binary artifacts."""

    # порт, к которому удалось подключиться, — MainWindow запоминает его
    port_found = Signal(int)

    def __init__(self, target: str, port_hint: int | None = None, parent=None):
        """target — «IP», «IP:порт» или «usb:<серийный номер iPhone>»."""
        super().__init__(parent)
        self.usb_serial = target[len(USB_PREFIX):] if target.startswith(USB_PREFIX) else None
        if self.usb_serial:
            self.target_ip, self.explicit_port = "iPhone по USB", None
        else:
            self.target_ip, self.explicit_port = parse_target(target)
        self.port_hint = port_hint
        self._socket = None

    # ── Поиск порта ──────────────────────────────────────────────────────

    def _probe(self, port: int, timeout: float = 1.0) -> bool:
        if self.usb_serial:
            return usb_probe(self.usb_serial, port)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                return s.connect_ex((self.target_ip, port)) == 0
        except OSError:
            return False

    def scan_unity_port(self) -> int:
        """Перебор PLAYER_PORTS, -1 — не нашли (или остановили)."""
        if self.usb_serial:  # по кабелю, не по сети — быстро и без вопросов к брандмауэру
            ports = usb_scan(self.usb_serial)
            return ports[0] if ports else -1
        logger.info("Scanning Unity ports on %s...", self.target_ip)
        self.status_changed.emit(f"Анонсов Unity нет — ищу порт игры на {self.target_ip}...")

        def check_port(port):
            if self._is_running and self._probe(port, _SCAN_TIMEOUT_SEC):
                return port
            return -1

        found_port = -1
        with ThreadPoolExecutor(max_workers=_SCAN_WORKERS) as executor:
            futures = [executor.submit(check_port, p) for p in PLAYER_PORTS]
            for future in as_completed(futures):
                if not self._is_running or future.result() != -1:
                    found_port = future.result() if self._is_running else -1
                    for f in futures:
                        f.cancel()
                    break
        if found_port != -1:
            logger.info("Found Unity port: %d", found_port)
        return found_port

    def _wait_for_port(self, listener: AnnounceListener | None, scan_allowed: bool) -> int:
        """Ждёт, пока найдётся порт игры. -1 — остановили или пора повторить."""
        if self.usb_serial:
            return self._wait_usb_game()
        if listener is None:  # порт указан явно
            if self._probe(self.explicit_port):
                return self.explicit_port
            self._sleep_listening(None, _RETRY_INTERVAL_SEC, f"Жду игру на {self.target_ip}:{self.explicit_port}...")
            return -1

        if self.port_hint and self._probe(self.port_hint):
            return self.port_hint

        wait = _ANNOUNCE_WAIT_SEC if scan_allowed else _RETRY_INTERVAL_SEC
        hint = "" if scan_allowed else " Если игру перезапустили, а она не находится — нажмите «Подключиться» ещё раз."
        port = self._sleep_listening(listener, wait, f"Жду игру Unity на {self.target_ip}...{hint}")
        if port != -1 or not self._is_running or not scan_allowed:
            return port
        return self.scan_unity_port()

    def _wait_usb_game(self) -> int:
        """Ждёт игру на iPhone по кабелю и подключается сразу, как она
        запустилась, — чтобы поймать логи с самого старта. Каждые 0,25 с —
        прошлый порт и 55000 (1 мс), заодно по 64 порта из 512 по кругу:
        новый порт находится за ≤2 с, а полный обход каждый раз грузил бы
        процессор (130 мс на обход)."""
        self.status_changed.emit("Жду запуска Unity-игры на iPhone (USB): запустите Development Build — "
                                 "логи пойдут с самого начала")
        hot = [p for p in dict.fromkeys([self.port_hint, PLAYER_PORTS[0]]) if p]
        chunk = 0
        while self._is_running:
            found = usb_scan(self.usb_serial, hot + list(PLAYER_PORTS[chunk * 64:(chunk + 1) * 64]))
            if found:
                return found[0] if self.port_hint not in found else self.port_hint
            chunk = (chunk + 1) % (len(PLAYER_PORTS) // 64)
            time.sleep(_USB_POLL_SEC)
        return -1

    def _sleep_listening(self, listener: AnnounceListener | None, seconds: float, status: str) -> int:
        self.status_changed.emit(status)
        deadline = time.monotonic() + seconds
        while self._is_running and time.monotonic() < deadline:
            if listener is None:
                time.sleep(0.2)
                continue
            for ip, port, project in listener.poll(0.2):
                logger.info("Unity announce: %s:%d %s", ip, port, project)
                if self._probe(port):
                    return port
        return -1

    # ── Чтение ───────────────────────────────────────────────────────────

    def run(self):
        listener = None if (self.explicit_port or self.usb_serial) else AnnounceListener(self.target_ip)
        scan_allowed = True
        try:
            while self._is_running:
                self.state_changed.emit("waiting")
                port = self._wait_for_port(listener, scan_allowed)
                # перебор — один раз за «Подключиться», дальше только анонсы
                scan_allowed = False
                if port == -1:
                    continue
                self.port_hint = port
                self.port_found.emit(port)
                self._stream(port)
        finally:
            if listener is not None:
                listener.close()

    def _emit_texts(self, texts: list[str]):
        # Локальная метка времени: по ней LogProcessor видит начало новой
        # записи (иначе всё склеилось бы в одну). Переводы строк внутри куска
        # не режем — многострочный стек вызовов остаётся одной записью.
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [f"{now_str} {t.strip()}" for t in texts if t.strip() and not _is_service_text(t.strip())]
        if lines:
            self.lines_ready.emit(lines)

    def _stream(self, port: int):
        tail = b""
        try:
            self.status_changed.emit(f"Подключение к {self.target_ip}:{port}...")
            if self.usb_serial:
                self._socket = usb_connect(self.usb_serial, port)
            else:
                self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self._socket.settimeout(5.0)
                self._socket.connect((self.target_ip, port))
            self.status_changed.emit(f"Сбор логов Unity ({self.target_ip}, порт {port})...")
            self.state_changed.emit("streaming")
            self._socket.settimeout(0.5)  # Fast timeout to allow interrupt checking

            while self._is_running:
                try:
                    data = self._socket.recv(8192)
                except socket.timeout:
                    # Данных нет полсекунды — недочитанный хвост уже не продолжится.
                    if tail:
                        self._emit_texts(flush_tail(tail))
                        tail = b""
                    continue
                if not data:
                    self._emit_texts(flush_tail(tail))
                    tail = b""
                    self.emit_system_message("Unity TCP соединение закрыто. Ожидание игры...")
                    return
                texts, tail = extract_text_runs(tail + data)
                self._emit_texts(texts)
        except OSError as e:
            if self._is_running:
                logger.warning("UnityTCP stream error: %r", e)
                self.emit_system_message(f"Ошибка соединения: {e}. Ожидание игры...")
        finally:
            if self._socket:
                try:
                    self._socket.close()
                except OSError:
                    pass
                self._socket = None

    def stop(self):
        super().stop()
        # Локальная копия: stop() зовут из потока окна, а поток чтения в это
        # время может обнулить self._socket (finally в _stream).
        sock = self._socket
        if sock:
            try:
                # Use shutdown to interrupt recv wait immediately
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass


def announce_platform(payload: bytes) -> str:
    """«[Id] AndroidPlayer(Pixel-7)» → «Android»."""
    m = _PLATFORM_RE.search(payload.decode("utf-8", errors="replace"))
    return m.group("platform") if m else ""


class GameDiscovery(QThread):
    """Unity-игры: на iPhone по USB и в сети по их анонсам — чтобы не вводить IP."""

    # [{"via": "usb"|"wifi", "ip", "port", "project", "platform", ("serial", "device")}]
    games_changed = Signal(list)
    USB_RESCAN_SEC = 3.0  # только что подключённый iPhone появляется в списке быстро

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_running = True

    def run(self):
        listener = AnnounceListener(None)
        seen: dict = {}  # (ip, port) -> (игра, когда последний раз)
        usb_games: list = []
        next_usb_scan = 0.0
        last: list = []
        try:
            while self._is_running:
                now = time.monotonic()
                if HAS_USB and now >= next_usb_scan:
                    try:
                        usb_games = asyncio.run(find_usb_games())
                    except Exception as e:
                        logger.debug("USB Unity scan failed: %s", e)
                        usb_games = []
                    next_usb_scan = time.monotonic() + self.USB_RESCAN_SEC
                for (ip, port, project), payload in listener.poll(0.5, raw=True):
                    seen[(ip, port)] = ({"via": "wifi", "ip": ip, "port": port, "project": project,
                                         "platform": announce_platform(payload)}, now)
                for key in [k for k, (_, when) in seen.items() if now - when > _GAME_TTL_SEC]:
                    del seen[key]
                wifi = sorted((g for g, _ in seen.values()), key=lambda g: (g["project"].lower(), g["ip"]))
                games = usb_games + wifi  # по кабелю — надёжнее, они первыми
                if games != last:
                    last = games
                    self.games_changed.emit(games)
        finally:
            listener.close()

    def stop(self):
        self._is_running = False
