"""Отслеживание: свои правила-фильтры, для каждого — сколько раз совпало и когда.

Правило — выражение в синтаксисе фильтра (core.filter), поэтому
`revenue OR adrevenue OR af_ad_revenue` ловит событие, как бы его ни назвали
в логах. Считается по всем полученным записям, независимо от основного
фильтра. Без Qt.
"""
from dataclasses import dataclass, field
from typing import Iterable, List, Optional

from core.filter import LogFilter


@dataclass
class WatchRule:
    expression: str
    enabled: bool = True
    count: int = 0
    last_entry_id: Optional[int] = None
    last_raw: str = ""
    _filter: LogFilter = field(default_factory=LogFilter, repr=False, compare=False)

    def __post_init__(self):
        self._filter.set_filter(self.expression)

    def matches(self, props: dict) -> bool:
        return bool(self.expression.strip()) and self._filter.match(props)

    def reset(self):
        self.count, self.last_entry_id, self.last_raw = 0, None, ""


class WatchList:
    def __init__(self, expressions: Iterable[tuple] = ()):
        self.rules: List[WatchRule] = [WatchRule(e, enabled) for e, enabled in expressions]

    def feed(self, entries: Iterable[dict]) -> bool:
        """Учесть новые записи. True — что-то изменилось (перерисовать панель)."""
        changed = False
        for entry in entries:
            for rule in self.rules:
                if rule.enabled and rule.matches(entry["props"]):
                    rule.count += 1
                    rule.last_entry_id = entry.get("id")
                    rule.last_raw = entry["raw"]
                    changed = True
        return changed

    def recount(self, entries: Iterable[dict]) -> None:
        for rule in self.rules:
            rule.reset()
        self.feed(entries)

    def add(self, expression: str) -> WatchRule:
        rule = WatchRule(expression.strip())
        self.rules.append(rule)
        return rule

    def remove(self, index: int) -> None:
        del self.rules[index]

    def to_settings(self) -> list:
        return [[r.expression, r.enabled] for r in self.rules]
