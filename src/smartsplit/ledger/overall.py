"""One answer to "what do I owe Sam?" across every group and personal split (SPEC section 9)."""

from collections.abc import Sequence

from smartsplit.domain.values import Context
from smartsplit.ledger.balances import pair_debts
from smartsplit.ledger.model import ContextLedger, OverallBalance, Transfer


def owed_to(me: str, transfers: Sequence[Transfer]) -> dict[str, int]:
    """Signed amount each other person owes `me` in one context's pair view (< 0: I owe them)."""
    owed: dict[str, int] = {}
    for transfer in transfers:
        if transfer.to_id == me:
            owed[transfer.from_id] = owed.get(transfer.from_id, 0) + transfer.amount_cents
        elif transfer.from_id == me:
            owed[transfer.to_id] = owed.get(transfer.to_id, 0) - transfer.amount_cents
    return owed


def overall_between(me: str, other: str, ledgers: Sequence[ContextLedger]) -> OverallBalance:
    """Sum of what `other` owes me in each context's pair view, with the per-context breakdown."""
    breakdown = _breakdowns(me, ledgers).get(other, [])
    return OverallBalance(other, sum(cents for _, cents in breakdown), tuple(breakdown))


def overall_for(me: str, ledgers: Sequence[ContextLedger]) -> tuple[OverallBalance, ...]:
    """Everyone I have anything open with, by id; nets of 0 are kept when a context isn't 0."""
    by_other = _breakdowns(me, ledgers)
    return tuple(
        OverallBalance(other, sum(cents for _, cents in by_other[other]), tuple(by_other[other]))
        for other in sorted(by_other)
    )


def _breakdowns(me: str, ledgers: Sequence[ContextLedger]) -> dict[str, list[tuple[Context, int]]]:
    by_other: dict[str, list[tuple[Context, int]]] = {}
    for ledger in ledgers:
        for other, cents in owed_to(me, pair_debts(ledger)).items():
            if cents != 0:
                by_other.setdefault(other, []).append((ledger.context, cents))
    return by_other
