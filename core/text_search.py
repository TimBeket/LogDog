"""Поиск подстроки без учёта регистра с позициями для QTextDocument. Без Qt.

QTextDocument считает позиции в UTF-16: эмодзи и другие символы вне BMP —
две единицы, а в Python-строке — один символ. Отсюда utf16_positions.

Поиск — lower() + str.find: в разы быстрее регулярки с IGNORECASE (у неё нет
быстрого поиска подстроки). Если lower() меняет длину текста (редкие буквы
вроде «İ»), позиции съехали бы — тогда регулярка.
"""
import re
from bisect import bisect_left
from typing import List

_ASTRAL = re.compile("[\U00010000-\U0010FFFF]")


def utf16_len(text: str) -> int:
    return len(text) + len(_ASTRAL.findall(text))


def find_all(text: str, needle: str) -> List[int]:
    """Начала всех непересекающихся вхождений needle (без учёта регистра),
    в символах Python."""
    needle = needle.lower()
    if not needle:
        return []
    low = text.lower()
    if len(low) != len(text):
        return [m.start() for m in re.finditer(re.escape(needle), text, re.IGNORECASE)]
    found, step = [], len(needle)
    i = low.find(needle)
    while i != -1:
        found.append(i)
        i = low.find(needle, i + step)
    return found


def utf16_positions(text: str, positions: List[int]) -> List[int]:
    """Позиции в символах Python → в единицах UTF-16 (как у QTextDocument)."""
    if not positions or text.isascii():
        return positions
    astral = [m.start() for m in _ASTRAL.finditer(text)]
    if not astral:
        return positions
    return [i + bisect_left(astral, i) for i in positions]
