"""Spotting a receipt added twice (SPEC section 10.4, use case C11)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from smartsplit.domain.values import Cents, Context, GroupContext


@dataclass(frozen=True, slots=True)
class DuplicateCandidate:
    """A saved bill (neither reversed nor reversing) or another open draft to compare with."""

    id: str
    is_draft: bool
    context: Context
    total_cents: Cents
    purchased_at: date | None
    people: frozenset[str]


def find_likely_duplicate(
    context: Context,
    total_cents: Cents,
    purchased_at: date,
    people: frozenset[str],
    candidates: Sequence[DuplicateCandidate],
    *,
    window_days: int,
) -> DuplicateCandidate | None:
    """The first candidate with the same total, within `window_days` of the purchase date, in
    the same group (or, for personal splits, between the same people). A candidate without a
    date counts as close in time."""
    for candidate in candidates:
        same_place = (
            candidate.context == context
            if isinstance(context, GroupContext)
            else candidate.context == context and candidate.people == people
        )
        close = (
            candidate.purchased_at is None
            or abs((candidate.purchased_at - purchased_at).days) <= window_days
        )
        if same_place and close and candidate.total_cents == total_cents:
            return candidate
    return None
