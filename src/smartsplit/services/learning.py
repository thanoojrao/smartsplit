"""Learning rules from saved bills (SPEC section 6.5)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from smartsplit.domain.enums import AnswerOutcome, RuleSource
from smartsplit.domain.model import AnswerObservation, Rule
from smartsplit.domain.values import LocalScope
from smartsplit.engine import learned_kind, observe
from smartsplit.ports.repository import UnitOfWork
from smartsplit.ports.system import IdGenerator


@dataclass(frozen=True, slots=True)
class LineAnswer:
    """One person whose share of one saved line was answered or edited, and the final line."""

    person_id: str
    item_key: str
    assignees: tuple[str, ...]
    weighted: bool


def learn_from_bill(
    uow: UnitOfWork,
    ids: IdGenerator,
    *,
    scope: LocalScope,
    bill_id: str,
    added_by: str,
    answers: Sequence[LineAnswer],
    now: datetime,
) -> tuple[Rule, ...]:
    """Record what this bill's answers showed, then create or replace learned rules.

    One bill gives at most one observation per (person, item key), so two milk lines on one
    receipt can't teach a rule by themselves; lines that disagree count as `included`. Learned
    rules are attributed to the bill's adder. Returns the rules created or replaced.
    """
    outcomes: dict[tuple[str, str], set[AnswerOutcome]] = {}
    for answer in answers:
        outcome = observe(answer.person_id, answer.assignees, weighted=answer.weighted)
        outcomes.setdefault((answer.person_id, answer.item_key), set()).add(outcome)

    learned: list[Rule] = []
    for (person_id, item_key), seen in outcomes.items():
        outcome = seen.pop() if len(seen) == 1 else AnswerOutcome.INCLUDED
        uow.observations.add(AnswerObservation(scope, person_id, item_key, outcome, bill_id, now))
        rule = _learn(
            uow,
            ids,
            scope=scope,
            person_id=person_id,
            item_key=item_key,
            added_by=added_by,
            now=now,
        )
        if rule is not None:
            learned.append(rule)
    return tuple(learned)


def _learn(
    uow: UnitOfWork,
    ids: IdGenerator,
    *,
    scope: LocalScope,
    person_id: str,
    item_key: str,
    added_by: str,
    now: datetime,
) -> Rule | None:
    """Create or replace the learned rule the observations now teach, if it changes anything."""
    existing = uow.rules.find(scope, person_id, item_key)
    kind = learned_kind(uow.observations.for_subject_item(scope, person_id, item_key), existing)
    if kind is None:
        return None
    if existing and existing.kind is kind and existing.source is RuleSource.LEARNED:
        return None
    rule = Rule(ids.new_id(), person_id, item_key, kind, scope, added_by, RuleSource.LEARNED, now)
    uow.rules.put(rule)
    return rule
