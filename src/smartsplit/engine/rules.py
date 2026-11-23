"""Which rules apply to one bill (SPEC section 6.3)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from smartsplit.domain.enums import RuleSource
from smartsplit.domain.model import Rule
from smartsplit.domain.values import (
    Context,
    Everywhere,
    GroupContext,
    GroupScope,
    NotesScope,
    PersonalContext,
)
from smartsplit.engine.split import RuleInput


@dataclass(frozen=True, slots=True)
class ResolvedRule:
    """The engine's input plus the rule it came from, so summaries can say who set it and where."""

    input: RuleInput
    rule: Rule


def resolve_rules(
    rules: Sequence[Rule], participants: Sequence[str], context: Context, added_by: str
) -> tuple[ResolvedRule, ...]:
    """Pick at most one rule per (participant, item key) for this bill.

    Only rules the bill's context controls apply: everyone's own Everywhere rules, plus this
    group's rules (group bills) or the adder's notes (personal splits). The most specific scope
    wins, then stated over learned, then the newest. Results are in participant order, then by
    item key.
    """
    order = {person: n for n, person in enumerate(participants)}
    best: dict[tuple[str, str], Rule] = {}
    for rule in rules:
        if rule.subject_id not in order or not _applies(rule, context, added_by):
            continue
        slot = (rule.subject_id, rule.item_key)
        current = best.get(slot)
        if current is None or _precedence(rule) > _precedence(current):
            best[slot] = rule
    chosen = sorted(best.values(), key=lambda r: (order[r.subject_id], r.item_key))
    return tuple(ResolvedRule(RuleInput(r.subject_id, r.item_key, r.kind), r) for r in chosen)


def _applies(rule: Rule, context: Context, added_by: str) -> bool:
    match rule.scope, context:
        case Everywhere(), _:
            return True
        case GroupScope(group_id), GroupContext(bill_group):
            return group_id == bill_group
        case NotesScope(owner_id), PersonalContext():
            return owner_id == added_by
        case _:
            return False


def _precedence(rule: Rule) -> tuple[bool, bool, datetime, str]:
    """Larger wins: local scope, then stated, then newest (id breaks exact-time ties)."""
    return (
        not isinstance(rule.scope, Everywhere),
        rule.source is RuleSource.STATED,
        rule.created_at,
        rule.id,
    )
