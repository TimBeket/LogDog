"""Какие новые краш-отчёты показывать уведомлением — без Qt.

Имя отчёта iOS: «<процесс>-ГГГГ-ММ-ДД-ЧЧММСС.ips» (бывает и с суффиксом
«.000» и т.п.). Отчёты о расходе ресурсов («…diskwrites_resource-…»,
«…cpu_resource-…») — не краши: их не показываем. JetsamEvent (iOS выгрузила
приложение из-за нехватки памяти) — показываем: для игр это важно.

Молча ничего не скрываем — от потока крашей пользователь защищается сам,
кнопкой «Не показывать от …» на карточке. Пока карточка процесса на экране,
его новые краши добавляются к ней счётчиком («и ещё N»), а не новыми
карточками; карточку закрыли или она исчезла — следующий краш покажется снова.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Iterable, List, Optional, Set

# с этого числа крашей подряд карточка подсказывает «часто падает — можно не показывать»
FREQUENT_CRASHES = 3

_NAME_RE = re.compile(r"^(?P<proc>.+?)-\d{4}-\d{2}-\d{2}-\d{6}")
_RESOURCE_SUFFIXES = ("_resource",)


@dataclass
class CrashReport:
    path: str       # путь на устройстве, как его отдаёт CrashReportsManager.ls
    process: str
    title: str      # для уведомления


def process_name(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    m = _NAME_RE.match(name)
    proc = m.group("proc") if m else name.rsplit(".", 1)[0]
    return proc


def describe(path: str) -> Optional[CrashReport]:
    """None — не краш (отчёт о ресурсах, не .ips)."""
    name = path.rsplit("/", 1)[-1]
    if not name.endswith((".ips", ".ips.synced")) and ".ips" not in name:
        return None
    proc = process_name(path)
    if proc.endswith(_RESOURCE_SUFFIXES):
        return None
    if proc == "JetsamEvent":
        return CrashReport(path, proc, "Нехватка памяти: iOS выгрузила приложения (JetsamEvent)")
    return CrashReport(path, proc, f"Новый краш: {proc}")


def new_reports(known: Set[str], current: Iterable[str]) -> List[CrashReport]:
    """Отчёты, которых не было в known (known дополняется). Первый вызов с
    пустым known — «база»: что уже лежало на устройстве, не новое."""
    fresh = []
    for path in current:
        if path in known:
            continue
        known.add(path)
        report = describe(path)
        if report is not None:
            fresh.append(report)
    return fresh


class AlertPolicy:
    """show — показать (новой карточкой или счётчиком на открытой); ignore —
    процесс пользователь сам отключил кнопкой «Не показывать от …»."""

    def __init__(self, is_muted: Callable[[str], bool]):
        self._is_muted = is_muted

    def decide(self, report: CrashReport) -> str:
        return "ignore" if self._is_muted(report.process) else "show"