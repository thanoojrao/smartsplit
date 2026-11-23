"""Split engine: the FROZEN contract from SPEC section 5.

The types and the `split_receipt` signature are the public contract pinned by
tests/acceptance/test_split_engine.py. Do not change the signature or the types
without asking the user (see CLAUDE.md).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from fractions import Fraction

from smartsplit.domain import QuestionReason, RuleKind, normalize_item_name
from smartsplit.engine.rounding import round_preserving_total


@dataclass(frozen=True)
class ItemInput:
    """One receipt line. `amount_cents` may be negative for a discount line."""

    id: str
    name: str
    amount_cents: int
    canonical: str | None = None


@dataclass(frozen=True)
class RuleInput:
    """A member's preference for an item key (already canonical/normalized)."""

    member_id: str
    item_key: str
    kind: RuleKind


@dataclass(frozen=True)
class Question:
    """Something the engine wants a human to confirm for one item."""

    item_id: str
    member_id: str | None
    reason: QuestionReason


@dataclass(frozen=True)
class Assignment:
    """Which members share an item, in group member order."""

    item_id: str
    member_ids: tuple[str, ...]


@dataclass(frozen=True)
class SplitResult:
    shares: dict[str, int]
    """Cents owed per member. Every member present; sums exactly to items + adjustments."""
    assignments: tuple[Assignment, ...]
    """One per input item, in input order."""
    questions: tuple[Question, ...] = field(default_factory=tuple)
    """In input item order, then member order."""


type _Override = Sequence[str] | Mapping[str, int]
type _Weights = dict[str, int]
"""Member → positive weight, in member order."""


def split_receipt(
    items: Sequence[ItemInput],
    members: Sequence[str],
    rules: Sequence[RuleInput] = (),
    adjustments_cents: int = 0,
    overrides: Mapping[str, Sequence[str] | Mapping[str, int]] | None = None,
) -> SplitResult:
    """Split a receipt among group members, applying preference rules.

    See SPEC section 5 for the exact semantics, ordering, and rounding.
    """
    overrides = overrides or {}
    _validate(items, members, overrides)
    member_set = set(members)
    relevant_rules = [rule for rule in rules if rule.member_id in member_set]

    assignments: list[Assignment] = []
    questions: list[Question] = []
    subtotals = dict.fromkeys(members, Fraction(0))
    for item in items:
        if item.id in overrides:
            weights = _override_weights(overrides[item.id], members)
        else:
            weights, item_questions = _rule_weights(item, members, relevant_rules)
            questions.extend(item_questions)
        assignments.append(Assignment(item.id, tuple(weights)))
        total_weight = sum(weights.values())
        for member, weight in weights.items():
            subtotals[member] += Fraction(item.amount_cents * weight, total_weight)

    exact = _add_adjustments(subtotals, adjustments_cents)
    shares = dict(zip(members, round_preserving_total(list(exact.values())), strict=True))
    return SplitResult(shares, tuple(assignments), tuple(questions))


def _validate(
    items: Sequence[ItemInput], members: Sequence[str], overrides: Mapping[str, _Override]
) -> None:
    if not members:
        raise ValueError("a split needs at least one member")
    if len(set(members)) != len(members):
        raise ValueError("members must be unique")
    item_ids = [item.id for item in items]
    if len(set(item_ids)) != len(item_ids):
        raise ValueError("item ids must be unique")
    member_set = set(members)
    for item_id, override in overrides.items():
        if item_id not in item_ids:
            raise ValueError(f"override for unknown item {item_id!r}")
        if isinstance(override, str):
            raise ValueError("an override lists members; got a single string")
        if not override:
            raise ValueError(f"empty override for item {item_id!r}")
        if not set(override) <= member_set:
            raise ValueError(f"override for item {item_id!r} names a non-member")
        if isinstance(override, Mapping) and not all(
            _is_positive_int(weight) for weight in override.values()
        ):
            raise ValueError(f"override weights for item {item_id!r} must be positive integers")


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _override_weights(override: _Override, members: Sequence[str]) -> _Weights:
    """A list override is an equal split; a mapping carries the weights as given."""
    if isinstance(override, Mapping):
        return {member: override[member] for member in members if member in override}
    return {member: 1 for member in members if member in override}


def _rule_weights(
    item: ItemInput, members: Sequence[str], rules: Sequence[RuleInput]
) -> tuple[_Weights, list[Question]]:
    """Apply SPEC section 5 steps 1 and 3-5 to one item; rule-based shares are always equal."""
    key = item.canonical if item.canonical is not None else normalize_item_name(item.name)
    kinds_by_member: dict[str, set[RuleKind]] = {}
    for rule in rules:
        if rule.item_key == key:
            kinds_by_member.setdefault(rule.member_id, set()).add(rule.kind)

    def has(member: str, kind: RuleKind) -> bool:
        return kind in kinds_by_member.get(member, set())

    only = [member for member in members if has(member, RuleKind.ONLY)]
    if only:
        return dict.fromkeys(only, 1), []

    eligible = [member for member in members if not has(member, RuleKind.EXCLUDE)]
    if not eligible:
        return dict.fromkeys(members, 1), [
            Question(item.id, None, QuestionReason.NO_ELIGIBLE_MEMBERS)
        ]
    questions = [
        Question(item.id, member, QuestionReason.SOFT_RULE)
        for member in eligible
        if has(member, RuleKind.SOFT_EXCLUDE)
    ]
    return dict.fromkeys(eligible, 1), questions


def _add_adjustments(subtotals: dict[str, Fraction], adjustments_cents: int) -> dict[str, Fraction]:
    """Spread adjustments by subtotals clamped at 0, or equally if every clamped subtotal is 0.

    Clamping means nobody is paid part of the tip because a discount was assigned to them.
    """
    clamped = {member: max(subtotal, Fraction(0)) for member, subtotal in subtotals.items()}
    weight_total = sum(clamped.values(), Fraction(0))
    if weight_total == 0:
        clamped = dict.fromkeys(subtotals, Fraction(1))
        weight_total = Fraction(len(subtotals))
    return {
        member: subtotal + adjustments_cents * clamped[member] / weight_total
        for member, subtotal in subtotals.items()
    }
