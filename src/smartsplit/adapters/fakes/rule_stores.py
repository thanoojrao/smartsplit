"""In-memory stores for items, aliases, rules, answer observations and model usage."""

from collections.abc import Collection
from datetime import date

from smartsplit.adapters.fakes.base import insert
from smartsplit.domain.model import (
    AnswerObservation,
    ItemAlias,
    LlmUsage,
    Rule,
)
from smartsplit.domain.values import LocalScope, RuleScope


class ItemStore:
    def __init__(self) -> None:
        self.records: set[str] = set()

    def ensure(self, key: str) -> None:
        self.records.add(key)

    def keys(self) -> frozenset[str]:
        return frozenset(self.records)


class AliasStore:
    def __init__(self) -> None:
        self.records: dict[tuple[LocalScope, str], ItemAlias] = {}

    def put(self, alias: ItemAlias) -> None:
        self.records[(alias.scope, alias.raw_name)] = alias

    def delete(self, scope: LocalScope, raw_name: str) -> None:
        self.records.pop((scope, raw_name), None)

    def for_scope(self, scope: LocalScope) -> tuple[ItemAlias, ...]:
        mine = [a for a in self.records.values() if a.scope == scope]
        return tuple(sorted(mine, key=lambda a: a.raw_name))


class RuleStore:
    def __init__(self) -> None:
        self.records: dict[str, Rule] = {}

    def get(self, rule_id: str) -> Rule | None:
        return self.records.get(rule_id)

    def find(self, scope: RuleScope, subject_id: str, item_key: str) -> Rule | None:
        return next(
            (
                r
                for r in self.records.values()
                if (r.scope, r.subject_id, r.item_key) == (scope, subject_id, item_key)
            ),
            None,
        )

    def put(self, rule: Rule) -> None:
        existing = self.find(rule.scope, rule.subject_id, rule.item_key)
        if existing:
            del self.records[existing.id]
        insert(self.records, rule.id, rule)

    def delete(self, rule_id: str) -> None:
        self.records.pop(rule_id, None)

    def for_subjects(self, subject_ids: Collection[str]) -> tuple[Rule, ...]:
        mine = [r for r in self.records.values() if r.subject_id in subject_ids]
        return tuple(sorted(mine, key=lambda r: (r.created_at, r.id)))


class ObservationStore:
    def __init__(self) -> None:
        self.records: list[AnswerObservation] = []

    def add(self, observation: AnswerObservation) -> None:
        self.records.append(observation)

    def for_subject_item(
        self, scope: LocalScope, subject_id: str, item_key: str
    ) -> tuple[AnswerObservation, ...]:
        mine = [
            o
            for o in self.records
            if (o.scope, o.subject_id, o.item_key) == (scope, subject_id, item_key)
        ]
        return tuple(sorted(mine, key=lambda o: o.observed_at))


class LlmUsageStore:
    def __init__(self) -> None:
        self.records: dict[tuple[str, date], LlmUsage] = {}

    def get(self, counter: str, day: date) -> LlmUsage | None:
        return self.records.get((counter, day))

    def increment(self, counter: str, day: date) -> int:
        current = self.records.get((counter, day))
        calls = (current.calls if current else 0) + 1
        self.records[(counter, day)] = LlmUsage(counter, day, calls)
        return calls
