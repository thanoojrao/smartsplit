"""Plain data for the operator's read endpoints (SPEC section 11): balances and rules."""

from dataclasses import dataclass

from smartsplit.domain.enums import RuleKind, RuleSource
from smartsplit.ledger import balances, overall_for, pair_debts
from smartsplit.ports.repository import UnitOfWork
from smartsplit.services.ledgers import context_name, group_ledger, ledgers_for
from smartsplit.services.rules_chat import scope_label


@dataclass(frozen=True, slots=True)
class Balance:
    person_id: str
    name: str
    cents: int
    """Positive: is owed money."""


@dataclass(frozen=True, slots=True)
class Debt:
    from_id: str
    to_id: str
    cents: int


@dataclass(frozen=True, slots=True)
class GroupReport:
    group_id: str
    name: str
    balances: tuple[Balance, ...]
    settle_up: tuple[Debt, ...]


@dataclass(frozen=True, slots=True)
class PartReport:
    context: str
    cents: int


@dataclass(frozen=True, slots=True)
class WithReport:
    other_id: str
    name: str
    cents: int
    """Positive: they owe the person."""
    by_context: tuple[PartReport, ...]


@dataclass(frozen=True, slots=True)
class RuleReport:
    item: str
    kind: RuleKind
    scope: str
    author_id: str
    source: RuleSource


def group_report(uow: UnitOfWork, group_id: str) -> GroupReport | None:
    group = uow.groups.get(group_id)
    if group is None:
        return None
    ledger = group_ledger(uow, group_id)
    return GroupReport(
        group.id,
        group.name,
        tuple(Balance(s.person_id, _name(uow, s.person_id), s.cents) for s in balances(ledger)),
        tuple(Debt(t.from_id, t.to_id, t.amount_cents) for t in pair_debts(ledger)),
    )


def person_report(uow: UnitOfWork, person_id: str) -> tuple[WithReport, ...] | None:
    if uow.people.get(person_id) is None:
        return None
    return tuple(
        WithReport(
            b.other_id,
            _name(uow, b.other_id),
            b.net_cents,
            tuple(PartReport(context_name(uow, c), cents) for c, cents in b.breakdown),
        )
        for b in overall_for(person_id, ledgers_for(uow, person_id))
    )


def rules_report(uow: UnitOfWork, person_id: str) -> tuple[RuleReport, ...] | None:
    if uow.people.get(person_id) is None:
        return None
    return tuple(
        RuleReport(r.item_key, r.kind, scope_label(uow, r.scope), r.author_id, r.source)
        for r in uow.rules.for_subjects([person_id])
    )


def _name(uow: UnitOfWork, person_id: str) -> str:
    person = uow.people.get(person_id)
    return person.display_name if person else ""
