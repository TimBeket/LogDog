"""Unity TCP: поиск порта (анонсы, перебор) и разбор потока Player Connection."""
import socket
import threading

import pytest

from transports import unity_socket as us
from transports.unity_socket import extract_text_runs, flush_tail, parse_announce, parse_target

# Двоичный заголовок сообщения (GUID + длина) — между текстами в потоке.
HEADER = b"\x8f\x00\x8b\x00\x01\x00\x00\x00\x9f\x00"


def test_parse_target():
    assert parse_target(" 192.168.1.5 ") == ("192.168.1.5", None)
    assert parse_target("192.168.1.5:55123") == ("192.168.1.5", 55123)
    assert parse_target("192.168.1.5:99999") == ("192.168.1.5:99999", None)


def test_parse_announce_prefers_packet_source():
    payload = (b"[IP] 10.211.55.4 [Port] 55376 [Flags] 3 [Guid] 1410689715 [EditorId] 1006284310 "
               b"[Version] 1048832 [Id] AndroidPlayer(Pixel):56000 [Debug] 1 "
               b"[PackageName] AndroidPlayer [ProjectName] My Game")
    assert parse_announce(payload, "192.168.1.7") == ("192.168.1.7", 55376, "My Game")
    assert parse_announce(b"garbage", "192.168.1.7") is None


def test_text_runs_keep_cyrillic():
    texts, tail = extract_text_runs(HEADER + "Ошибка загрузки уровня".encode() + HEADER)
    assert texts == ["Ошибка загрузки уровня"] and tail == b""


def test_message_split_between_packets_is_glued():
    message = "Загрузка уровня 3 завершена".encode()
    first, second = HEADER + message[:11], message[11:] + HEADER  # разрыв посреди буквы
    texts, tail = extract_text_runs(first)
    assert texts == [] and tail
    texts, tail = extract_text_runs(tail + second)
    assert texts == ["Загрузка уровня 3 завершена"] and tail == b""


def test_tail_is_flushed_when_stream_goes_quiet():
    texts, tail = extract_text_runs(HEADER + b"last message")
    assert texts == [] and flush_tail(tail) == ["last message"]


def test_short_binary_noise_is_ignored():
    texts, _ = extract_text_runs(HEADER + b"ab" + HEADER + b"real log line" + HEADER)
    assert texts == ["real log line"]


# ── Подключение к настоящему сокету ──────────────────────────────────────────

def _player(port_range=None):
    """Локальный «Unity-плеер»: принимает соединение, шлёт два сообщения и закрывает."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    for port in port_range or [0]:
        try:
            server.bind(("127.0.0.1", port))
            break
        except OSError:
            continue
    else:
        pytest.skip("нет свободного порта в диапазоне Unity")
    server.listen(5)

    def serve():
        while True:
            try:
                conn, _ = server.accept()
            except OSError:
                return
            with conn:
                try:  # проверка порта закрывает соединение сразу — отправка может упасть
                    conn.sendall(HEADER + "Привет из игры".encode() + HEADER + b"second line" + HEADER)
                except OSError:
                    pass

    threading.Thread(target=serve, daemon=True).start()
    return server


def _collect(qtbot, reader, count=2):
    lines = []
    reader.lines_ready.connect(lines.extend)
    reader.start()
    try:
        qtbot.waitUntil(lambda: len([l for l in lines if "[LogDog:System]" not in l]) >= count, timeout=15000)
    finally:
        reader.stop()
        reader.wait(5000)
    return lines


def test_explicit_port_connects_without_scanning(qtbot, monkeypatch):
    server = _player()
    port = server.getsockname()[1]
    monkeypatch.setattr(us.UnityTCPReader, "scan_unity_port", lambda self: pytest.fail("перебор портов"))
    monkeypatch.setattr(us, "AnnounceListener", lambda *_: pytest.fail("анонсы при явном порте"))
    try:
        lines = _collect(qtbot, us.UnityTCPReader(f"127.0.0.1:{port}"))
    finally:
        server.close()
    logs = [l.split(" ", 2)[2] for l in lines if "[LogDog:System]" not in l]
    assert logs[:2] == ["Привет из игры", "second line"]


def test_scan_finds_port_once_when_no_announces(qtbot, monkeypatch):
    server = _player(us.PLAYER_PORTS)
    port = server.getsockname()[1]
    monkeypatch.setattr(us, "_ANNOUNCE_WAIT_SEC", 0.1)
    scans = []
    original_scan = us.UnityTCPReader.scan_unity_port
    monkeypatch.setattr(us.UnityTCPReader, "scan_unity_port",
                        lambda self: scans.append(1) or original_scan(self))
    reader = us.UnityTCPReader("127.0.0.1")
    found = []
    reader.port_found.connect(found.append)
    try:
        _collect(qtbot, reader)
    finally:
        server.close()
    # «Плеер» закрывает соединение после двух строк — LogDog переподключается
    # по найденному порту, а не перебирает порты заново.
    assert set(found) == {port} and scans == [1]



ANNOUNCE = (b"[IP] 10.0.0.4 [Port] 55376 [Flags] 3 [Guid] 1 [EditorId] 2 [Version] 1048832 "
            b"[Id] AndroidPlayer(Pixel-7):56000 [Debug] 1 [PackageName] AndroidPlayer [ProjectName] My Game")


def test_announce_platform():
    assert us.announce_platform(ANNOUNCE) == "Android"
    assert us.announce_platform(ANNOUNCE.replace(b"AndroidPlayer(", b"iPhonePlayer(")) == "iPhone"


def test_game_discovery_lists_and_expires_games(qtbot, monkeypatch):
    clock = [100.0]
    batches = [[(("192.168.1.7", 55376, "My Game"), ANNOUNCE)], [], []]

    class FakeListener:
        def __init__(self, target):
            assert target is None
        def poll(self, timeout, raw=False):
            clock[0] += 4.0  # каждый опрос — 4 «секунды»
            return batches.pop(0) if batches else []
        def close(self):
            pass

    monkeypatch.setattr(us, "AnnounceListener", FakeListener)
    monkeypatch.setattr(us, "HAS_USB", False)  # тесту не нужен настоящий iPhone по USB
    monkeypatch.setattr(us.time, "monotonic", lambda: clock[0])
    discovery = us.GameDiscovery()
    seen = []
    discovery.games_changed.connect(seen.append)
    discovery.start()
    qtbot.waitUntil(lambda: len(seen) >= 2, timeout=3000)
    discovery.stop()
    discovery.wait(2000)
    assert seen[0] == [{"via": "wifi", "ip": "192.168.1.7", "port": 55376, "project": "My Game",
                        "platform": "Android"}]
    assert seen[1] == []  # анонсов больше 6 с нет — игра закрыта


def test_project_name_followed_by_binary_stream():
    """По USB сразу за названием проекта идут двоичные данные потока."""
    payload = (b"[IP] 192.168.1.105 [Port] 55000 [Flags] 2147483650 [Guid] 1 [EditorId] 2 [Version] 1048832 "
               b"[Id] iPhonePlayer(8,localhost):56000 [Debug] 0 [PackageName] iPhonePlayer [ProjectName] My Game+"
               b"\x00\x8fN\xa5g [HM] log line")
    assert parse_announce(payload, "") == ("192.168.1.105", 55000, "My Game+")
    assert us.announce_platform(payload) == "iPhone"


def test_usb_reader_streams_through_usb_socket(qtbot, monkeypatch):
    """Режим «iPhone по USB»: порт ищется по кабелю, логи — через usbmux-сокет."""
    ours, game = socket.socketpair()
    game.sendall(HEADER + "Привет по USB".encode() + HEADER + b"second line" + HEADER)
    monkeypatch.setattr(us, "usb_scan", lambda serial, ports=None: [55000])
    monkeypatch.setattr(us, "usb_probe", lambda serial, port: False)
    monkeypatch.setattr(us, "usb_connect", lambda serial, port: ours)
    monkeypatch.setattr(us, "AnnounceListener", lambda *_: pytest.fail("мультикаст не нужен для USB"))
    reader = us.UnityTCPReader("usb:00008140-TEST")
    found = []
    reader.port_found.connect(found.append)
    try:
        lines = _collect(qtbot, reader)
    finally:
        game.close()
    assert [l.split(" ", 2)[2] for l in lines if "[LogDog:System]" not in l][:2] == ["Привет по USB", "second line"]
    assert found[0] == 55000
