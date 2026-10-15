"""Мелкие разборы записи лога без Qt: время, текст без времени, разница во времени.

Время берётся из самой строки: syslog iOS («Oct 15 14:02:11», без года и
долей секунды) или метка, которую LogDog ставит строкам Unity
(«2026-10-15 14:02:11»). Поэтому разница — с точностью до секунды.
"""
import re
from datetime import datetime
from typing import Optional

_IOS_TIME = re.compile(r'^\s*([A-Z][a-z]{2})\s+(\d{1,2})\s+(\d{2}):(\d{2}):(\d{2})')
_ISO_TIME = re.compile(r'^\s*(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})')
_MONTHS = {m: i for i, m in enumerate(
    ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), start=1)}


def entry_time(raw: str) -> Optional[float]:
    """Секунды (условные: для разницы между записями) или None, если времени нет."""
    m = _ISO_TIME.match(raw)
    if m:
        y, mo, d, h, mi, s = map(int, m.groups())
        try:
            return datetime(y, mo, d, h, mi, s).timestamp()
        except ValueError:
            return None
    m = _IOS_TIME.match(raw)
    if m and m.group(1) in _MONTHS:
        # Года в syslog нет — текущий (а для «декабря» в январе — прошлый):
        # иначе разница с маркером LogDog (у него полная дата) была бы в годах.
        now = datetime.now()
        try:
            when = datetime(now.year, _MONTHS[m.group(1)], int(m.group(2)),
                            int(m.group(3)), int(m.group(4)), int(m.group(5)))
            if (when - now).days > 1:
                when = when.replace(year=now.year - 1)
            return when.timestamp()
        except ValueError:
            return None
    return None


_HEADER_RE = re.compile(r'^.*?<\w+>:\s*')


def message_body(raw: str) -> str:
    """Текст сообщения без шапки syslog («… процесс[pid] <Notice>: »)."""
    text = message_key(raw)
    m = _HEADER_RE.match(text)
    return text[m.end():] if m else text


def message_key(raw: str) -> str:
    """Текст записи без времени в начале — по нему схлопываются повторы."""
    for pattern in (_ISO_TIME, _IOS_TIME):
        m = pattern.match(raw)
        if m:
            return raw[m.end():].strip()
    return raw.strip()


MAX_DELTA_SEC = 24 * 3600  # больше — часы устройства и компьютера разошлись, не показываем


def format_delta(seconds: float) -> str:
    """'+3с', '+1м05с', '+2ч10м'; '' — для нуля (строки в ту же секунду)."""
    seconds = int(round(seconds))
    if seconds <= 0 or seconds > MAX_DELTA_SEC:
        return ""
    if seconds < 60:
        return f"+{seconds}с"
    if seconds < 3600:
        return f"+{seconds // 60}м{seconds % 60:02d}с"
    return f"+{seconds // 3600}ч{seconds % 3600 // 60:02d}м"
