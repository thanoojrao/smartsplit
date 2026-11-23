"""Postgres stores for items, aliases, rules, answer observations and model usage."""

from collections.abc import Collection
from datetime import date

from sqlalchemy import ColumnElement, Row, and_, delete, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from smartsplit.adapters.db import tables as t
from smartsplit.adapters.db.base import Store
from smartsplit.adapters.db.mapping import (
    local_scope_from,
    scope_columns,
    scope_from,
)
from smartsplit.domain.enums import AnswerOutcome, RuleKind, RuleSource
from smartsplit.domain.model import (
    AnswerObservation,
    ItemAlias,
    LlmUsage,
    Rule,
)
from smartsplit.domain.values import LocalScope, RuleScope


class ItemStore(Store):
    def ensure(self, key: str) -> None:
        self._execute(pg_insert(t.items).values(key=key).on_conflict_do_nothing())

    def keys(self) -> frozenset[str]:
        return frozenset(self._execute(select(t.items.c.key)).scalars())


class AliasStore(Store):
    def put(self, alias: ItemAlias) -> None:
        kind, ref = scope_columns(alias.scope)
        statement = pg_insert(t.item_aliases).values(
            scope_kind=kind, scope_ref=ref, raw_name=alias.raw_name, item_key=alias.item_key
        )
        self._execute(
            statement.on_conflict_do_update(
                index_elements=["scope_kind", "scope_ref", "raw_name"],
                set_={"item_key": statement.excluded.item_key},
            )
        )

    def delete(self, scope: LocalScope, raw_name: str) -> None:
        kind, ref = scope_columns(scope)
        c = t.item_aliases.c
        self._execute(
            delete(t.item_aliases).where(
                c.scope_kind == kind, c.scope_ref == ref, c.raw_name == raw_name
            )
        )

    def for_scope(self, scope: LocalScope) -> tuple[ItemAlias, ...]:
        kind, ref = scope_columns(scope)
        c = t.item_aliases.c
        rows = self._execute(
            select(c.raw_name, c.item_key)
            .where(c.scope_kind == kind, c.scope_ref == ref)
            .order_by(c.raw_name)
        )
        return tuple(ItemAlias(scope, r.raw_name, r.item_key) for r in rows)


def _rule(row: Row[tuple[object, ...]]) -> Rule:
    m = row._mapping
    return Rule(
        m["id"],
        m["subject_id"],
        m["item_key"],
        RuleKind(m["kind"]),
        scope_from(m["scope_kind"], m["scope_ref"]),
        m["author_id"],
        RuleSource(m["source"]),
        m["created_at"],
    )


class RuleStore(Store):
    def get(self, rule_id: str) -> Rule | None:
        row = self._execute(select(t.rules).where(t.rules.c.id == rule_id)).first()
        return _rule(row) if row else None

    def find(self, scope: RuleScope, subject_id: str, item_key: str) -> Rule | None:
        row = self._execute(select(t.rules).where(_rule_slot(scope, subject_id, item_key))).first()
        return _rule(row) if row else None

    def put(self, rule: Rule) -> None:
        """One statement, so two people changing the same rule at once can't collide."""
        kind, ref = scope_columns(rule.scope)
        statement = pg_insert(t.rules).values(
            id=rule.id,
            subject_id=rule.subject_id,
            item_key=rule.item_key,
            kind=rule.kind.value,
            scope_kind=kind,
            scope_ref=ref,
            author_id=rule.author_id,
            source=rule.source.value,
            created_at=rule.created_at,
        )
        replaced = ("id", "kind", "author_id", "source", "created_at")
        self._execute(
            statement.on_conflict_do_update(
                index_elements=["scope_kind", "scope_ref", "subject_id", "item_key"],
                set_={column: statement.excluded[column] for column in replaced},
            )
        )

    def delete(self, rule_id: str) -> None:
        self._execute(delete(t.rules).where(t.rules.c.id == rule_id))

    def for_subjects(self, subject_ids: Collection[str]) -> tuple[Rule, ...]:
        c = t.rules.c
        rows = self._execute(
            select(t.rules).where(c.subject_id.in_(list(subject_ids))).order_by(c.created_at, c.id)
        )
        return tuple(_rule(r) for r in rows)


def _rule_slot(scope: RuleScope, subject_id: str, item_key: str) -> ColumnElement[bool]:
    kind, ref = scope_columns(scope)
    c = t.rules.c
    return and_(
        c.scope_kind == kind, c.scope_ref == ref, c.subject_id == subject_id, c.item_key == item_key
    )


class ObservationStore(Store):
    def add(self, observation: AnswerObservation) -> None:
        kind, ref = scope_columns(observation.scope)
        self._execute(
            insert(t.answer_observations).values(
                scope_kind=kind,
                scope_ref=ref,
                subject_id=observation.subject_id,
                item_key=observation.item_key,
                outcome=observation.outcome.value,
                bill_id=observation.bill_id,
                observed_at=observation.observed_at,
            )
        )

    def for_subject_item(
        self, scope: LocalScope, subject_id: str, item_key: str
    ) -> tuple[AnswerObservation, ...]:
        kind, ref = scope_columns(scope)
        c = t.answer_observations.c
        rows = self._execute(
            select(t.answer_observations)
            .where(
                c.scope_kind == kind,
                c.scope_ref == ref,
                c.subject_id == subject_id,
                c.item_key == item_key,
            )
            .order_by(c.observed_at, c.seq)
        )
        return tuple(
            AnswerObservation(
                local_scope_from(r.scope_kind, r.scope_ref),
                subject_id,
                item_key,
                AnswerOutcome(r.outcome),
                r.bill_id,
                r.observed_at,
            )
            for r in rows
        )


class LlmUsageStore(Store):
    def get(self, counter: str, day: date) -> LlmUsage | None:
        c = t.llm_usage.c
        calls = self._execute(select(c.calls).where(c.counter == counter, c.day == day)).scalar()
        return LlmUsage(counter, day, calls) if calls is not None else None

    def increment(self, counter: str, day: date) -> int:
        statement = pg_insert(t.llm_usage).values(counter=counter, day=day, calls=1)
        upsert = statement.on_conflict_do_update(
            index_elements=["counter", "day"], set_={"calls": t.llm_usage.c.calls + 1}
        ).returning(t.llm_usage.c.calls)
        return int(self._execute(upsert).scalar_one())
