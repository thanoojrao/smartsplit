"""Split engine: the FROZEN contract from SPEC section 5.

The types and the `split_receipt` signature are the public contract pinned by
tests/acceptance/test_split_engine.py. Implement the body; do not change the
signature or the types without asking the user (see CLAUDE.md).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from smartsplit.domain import QuestionReason, RuleKind


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
    raise NotImplementedError("M1: implement per SPEC section 5")
