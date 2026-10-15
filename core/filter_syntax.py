"""Разбор текста фильтра для поля ввода: подсветка, ошибки и подсказки.

Без Qt. Токены — те же, что у LogFilter (core.filter.tokenize_with_positions),
поэтому подсветка и проверка не расходятся с тем, что реально ищется.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Optional

from core.filter import FIELDS, LEVEL_ALIASES, LEVEL_VALUES, OPERATORS, tokenize_with_positions

_LEVEL_HINTS = {"error": "ошибки", "warn": "предупреждения", "info": "информация", "debug": "отладка"}

FIELD_HINTS = {
    "level": "уровень: error, warn, info, debug",
    "proc": "процесс (часть имени)",
    "pid": "ID процесса, число",
    "text": "текст; фразу — в кавычках",
}


@dataclass
class Span:
    start: int
    end: int
    kind: str  # field | value | operator | paren | string


@dataclass
class Problem:
    start: int
    end: int
    message: str
    severity: str = "error"  # error | warning


@dataclass
class Analysis:
    spans: List[Span] = field(default_factory=list)
    problems: List[Problem] = field(default_factory=list)


@dataclass
class Suggestion:
    text: str   # что вставить вместо набранного начала
    hint: str = ""


@dataclass
class Completion:
    start: int  # заменяется text[start:end] — уже набранное начало
    end: int
    items: List[Suggestion]
    context: str  # подсказка, что здесь можно ввести


def _split_field(token: str):
    """'level:err' -> ('level', 'err'), если это поле фильтра; иначе None."""
    name, sep, value = token.partition(':')
    if sep and name.lower() in FIELDS:
        return name.lower(), value
    return None


def _is_quoted(token: str) -> bool:
    return token[:1] in ('"', "'")


def analyze(text: str) -> Analysis:
    result = Analysis()
    tokens = tokenize_with_positions(text)
    open_parens: List[int] = []
    expect_operand = True  # в начале, после AND/OR/NOT и «(» нужно условие
    last_operator: Optional[tuple] = None

    for token, start, end in tokens:
        up = token.upper()
        if up in OPERATORS:
            result.spans.append(Span(start, end, "operator"))
            typed = text[start:end]
            if typed != up:
                result.problems.append(Problem(
                    start, end, f"«{typed}» читается как оператор {up}. Чтобы искать само слово, "
                                f'возьмите его в кавычки: "{typed}"', "warning"))
            if up != "NOT" and expect_operand:
                result.problems.append(Problem(start, end, f"Перед {up} нет условия"))
            expect_operand = True
            last_operator = (up, start, end)
            continue
        if token == '(':
            result.spans.append(Span(start, end, "paren"))
            open_parens.append(start)
            expect_operand = True
            continue
        if token == ')':
            result.spans.append(Span(start, end, "paren"))
            if not open_parens:
                result.problems.append(Problem(start, end, "Лишняя закрывающая скобка"))
            else:
                if expect_operand:
                    result.problems.append(Problem(open_parens[-1], end, "Пустые скобки"))
                open_parens.pop()
            expect_operand = False
            continue

        # условие
        expect_operand = False
        last_operator = None
        if _is_quoted(token):
            result.spans.append(Span(start, end, "string"))
            if len(token) < 2 or token[-1] != token[0]:
                result.problems.append(Problem(start, end, "Кавычка не закрыта"))
            continue
        parsed = _split_field(token)
        if parsed is None:
            continue  # обычный текст — без подсветки
        name, value = parsed
        value_start = start + len(name) + 1
        result.spans.append(Span(start, value_start, "field"))
        if value:
            result.spans.append(Span(value_start, end, "string" if _is_quoted(value) else "value"))
        bare = value.strip("\"'").lower()
        if not value:
            result.problems.append(Problem(start, end, f"После «{name}:» нет значения — "
                                                       "условие ничего не отсеивает", "warning"))
        elif name == "level" and bare not in LEVEL_ALIASES:
            result.problems.append(Problem(value_start, end, f"Нет уровня «{bare}». "
                                                             "Есть: error, warn, info, debug"))
        elif name == "pid" and not bare.isdigit():
            result.problems.append(Problem(value_start, end, "pid — это число"))

    if last_operator is not None:
        up, start, end = last_operator
        result.problems.append(Problem(start, end, f"После {up} нужно условие"))
    for start in open_parens:
        result.problems.append(Problem(start, start + 1, "Скобка не закрыта"))
    return result


def complete(text: str, cursor: int, procs: Iterable[str] = ()) -> Optional[Completion]:
    """Что можно ввести в позиции курсора. None — подсказывать нечего
    (курсор внутри кавычек, pid:/text: и т.п.)."""
    tokens = tokenize_with_positions(text)
    current = next(((t, s, e) for t, s, e in tokens if s < cursor <= e), None)
    before = [t for t, s, e in tokens if e <= (current[1] if current else cursor)]

    expect_operand = True
    open_parens = 0
    for token in before:
        up = token.upper()
        if up in OPERATORS or token == '(':
            expect_operand = True
            open_parens += token == '('
        elif token == ')':
            expect_operand = False
            open_parens = max(0, open_parens - 1)
        else:
            expect_operand = False

    if current is None:
        start, prefix = cursor, ""
    else:
        token, start, _ = current
        prefix = token[:cursor - start]
        if prefix.upper() in OPERATORS and cursor == current[2]:
            return None  # оператор уже набран — дальше пробел
        if prefix in ('(', ')'):
            return None

    if _is_quoted(prefix):
        return None
    parsed = _split_field(prefix)
    if parsed is not None:
        name, value = parsed
        value_start = start + len(name) + 1
        if name == "level":
            items = [Suggestion(v + " ", _LEVEL_HINTS[v]) for v in LEVEL_VALUES
                     if v.startswith(value.lower()) and v != value.lower()]
            return Completion(value_start, cursor, items, "error · warn · info · debug")
        if name == "proc":
            low = value.lower()
            matches = [p for p in procs if p.lower().startswith(low) and p.lower() != low]
            matches += [p for p in procs if low in p.lower() and p not in matches and p.lower() != low]
            items = [Suggestion((f'"{p}"' if " " in p else p) + " ", f"процесс {p}") for p in matches[:30]]
            return Completion(value_start, cursor, items,
                              "имя процесса из полученных логов" if procs else "часть имени процесса")
        return Completion(value_start, cursor, [], FIELD_HINTS[name])

    low = prefix.lower()
    if expect_operand:
        candidates = [Suggestion(f + ":", FIELD_HINTS[f]) for f in FIELDS]
        candidates += [Suggestion("NOT ", "NOT: исключить"), Suggestion("(", "группа условий")]
        context = "level:  proc:  pid:  text:  NOT  (  — или просто текст"
    else:
        candidates = [Suggestion("AND ", "AND: оба условия"), Suggestion("OR ", "OR: любое из условий")]
        if open_parens:
            candidates.append(Suggestion(") ", "закрыть скобку"))
        context = "AND  OR" + ("  )" if open_parens else "") + "  — или ещё слово (будет AND)"
    items = [c for c in candidates if c.text.lower().startswith(low) and c.text.strip().lower() != low]
    return Completion(start, cursor, items, context)
