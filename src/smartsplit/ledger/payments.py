"""Where a payment goes, and squaring up two people (SPEC section 9)."""

from collections.abc import Sequence
from datetime import UTC, datetime

from smartsplit.domain.values import Context, GroupContext, PersonalContext, Share
from smartsplit.ledger.balances import balances, pair_debts, simplify_debts
from smartsplit.ledger.model import Allocation, ContextLedger, Transfer
from smartsplit.ledger.overall import owed_to

_MAX_SQUARE_UP_ROUNDS = 100
"""Re-simplifying after each settlement converges in a few rounds; this only guards bugs."""


def allocate_payment(
    payer: str,
    payee: str,
    amount: int,
    ledgers: Sequence[ContextLedger],
    named: Context | None,
) -> tuple[tuple[Allocation, ...], int]:
    """Split one real payment from `payer` to `payee` across contexts.

    A named context (the group chat it was said in, or "for the trip") takes all of it.
    Otherwise it pays off the contexts where payer owes payee, largest first, ties to the
    context whose oldest bill between the two is oldest; anything beyond what payer owes goes
    to the personal context (payee now owes payer). Returns the allocations and the overpaid
    part: beyond what payer owed in total, or in the named context.
    """
    if amount <= 0:
        raise ValueError("a payment must be positive")
    if named is not None:
        owed = _owes(
            payer, payee, next((ledger for ledger in ledgers if ledger.context == named), None)
        )
        return (Allocation(named, amount),), max(0, amount - owed)

    candidates = [(n, ledger, _owes(payer, payee, ledger)) for n, ledger in enumerate(ledgers)]
    debts = sorted(
        (c for c in candidates if c[2] > 0),
        key=lambda c: (-c[2], _oldest_bill_between(c[1], payer, payee), c[0]),
    )
    allocations: dict[Context, int] = {}
    left = amount
    for _, ledger, owed in debts:
        if left == 0:
            break
        part = min(left, owed)
        allocations[ledger.context] = part
        left -= part
    if left:
        allocations[PersonalContext()] = allocations.get(PersonalContext(), 0) + left
    return tuple(Allocation(c, cents) for c, cents in allocations.items()), left


def square_up(
    a: str, b: str, ledgers: Sequence[ContextLedger]
) -> tuple[tuple[Context, Transfer], ...]:
    """Settlements that clear every group's pair amount between a and b, plus one personal
    settlement in the opposite direction, so the rows net to zero: no money changes hands,
    and whatever was owed overall now sits in the personal splits.

    Settling a group's shown pair amount can reshuffle the greedy plan, so each group is
    settled repeatedly until the pair amount it shows is 0.
    """
    rows: list[tuple[Context, Transfer]] = []
    total = 0
    for ledger in ledgers:
        if isinstance(ledger.context, GroupContext):
            settled = _clear_group_pair(a, b, ledger)
            if settled:
                rows.append((ledger.context, _transfer(a, b, settled)))
                total += settled
    if total:
        rows.append((PersonalContext(), _transfer(b, a, total)))
    return tuple(rows)


def _clear_group_pair(a: str, b: str, ledger: ContextLedger) -> int:
    """Total that a must pay b (negative: b pays a) so the group shows nothing between them."""
    current = {share.person_id: share.cents for share in balances(ledger)}
    settled = 0
    for _ in range(_MAX_SQUARE_UP_ROUNDS):
        shares = [Share(person, cents) for person, cents in current.items()]
        owed = owed_to(b, simplify_debts(shares, ledger.member_order)).get(a, 0)
        if owed == 0:
            return settled
        current[a] = current.get(a, 0) + owed
        current[b] = current.get(b, 0) - owed
        settled += owed
    raise RuntimeError("square-up did not converge")


def _owes(payer: str, payee: str, ledger: ContextLedger | None) -> int:
    if ledger is None:
        return 0
    return owed_to(payee, pair_debts(ledger)).get(payer, 0)


def _oldest_bill_between(ledger: ContextLedger, a: str, b: str) -> datetime:
    """When the first bill between the two (both in it, or one paid) was added; contexts
    without one sort last."""
    times = [
        bill.created_at
        for bill in ledger.bills
        if bill.reverses_id is None and {a, b} <= {*bill.participants, bill.payer_id}
    ]
    return min(times, default=datetime.max.replace(tzinfo=UTC))


def _transfer(debtor: str, creditor: str, cents: int) -> Transfer:
    """A transfer of `cents` from debtor to creditor, flipped when `cents` is negative."""
    if cents > 0:
        return Transfer(debtor, creditor, cents)
    return Transfer(creditor, debtor, -cents)
