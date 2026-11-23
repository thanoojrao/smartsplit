"""Balances and who owes whom inside one context (SPEC section 9)."""

from collections.abc import Callable, Sequence

from smartsplit.domain.values import GroupContext, Share
from smartsplit.ledger.model import ContextLedger, Transfer


def balances(ledger: ContextLedger) -> tuple[Share, ...]:
    """Each person's balance: bills paid - shares + settlements sent - settlements received.

    Reversing bills and settlements carry negated amounts, so they cancel by plain addition.
    People are listed in member order, then anyone else who appears, by id. Always sums to 0.
    """
    totals: dict[str, int] = dict.fromkeys(ledger.member_order, 0)
    for bill in ledger.bills:
        totals[bill.payer_id] = totals.get(bill.payer_id, 0) + bill.total_cents
        for share in bill.shares:
            totals[share.person_id] = totals.get(share.person_id, 0) - share.cents
    for settlement in ledger.settlements:
        totals[settlement.from_id] = totals.get(settlement.from_id, 0) + settlement.amount_cents
        totals[settlement.to_id] = totals.get(settlement.to_id, 0) - settlement.amount_cents
    return tuple(Share(person, totals[person]) for person in _ordered(totals, ledger.member_order))


def simplify_debts(balances: Sequence[Share], order: Sequence[str]) -> tuple[Transfer, ...]:
    """Greedy settle-up plan: the largest debtor pays the largest creditor, repeatedly.

    Few transfers, not guaranteed minimal; ties go to the person earlier in `order` (then id),
    so the plan is deterministic. Balances must sum to 0.
    """
    if sum(share.cents for share in balances) != 0:
        raise ValueError("balances must sum to 0")
    rank = rank_by(order)
    owed = {s.person_id: s.cents for s in balances if s.cents > 0}
    owing = {s.person_id: -s.cents for s in balances if s.cents < 0}
    transfers: list[Transfer] = []
    while owing:
        debtor = min(owing, key=lambda p: (-owing[p], rank(p)))
        creditor = min(owed, key=lambda p: (-owed[p], rank(p)))
        amount = min(owing[debtor], owed[creditor])
        transfers.append(Transfer(debtor, creditor, amount))
        for side, person in ((owing, debtor), (owed, creditor)):
            side[person] -= amount
            if side[person] == 0:
                del side[person]
    return tuple(transfers)


def pair_debts(ledger: ContextLedger) -> tuple[Transfer, ...]:
    """Who owes whom in this context, as shown to people.

    A group uses its simplified plan (the group balance is the truth inside a group). Personal
    splits are never simplified across people: each participant owes the payer their share,
    less what they have settled with that payer.
    """
    if isinstance(ledger.context, GroupContext):
        return simplify_debts(balances(ledger), ledger.member_order)
    owes: dict[tuple[str, str], int] = {}
    for bill in ledger.bills:
        for share in bill.shares:
            if share.person_id != bill.payer_id:
                _add(owes, share.person_id, bill.payer_id, share.cents)
    for settlement in ledger.settlements:
        _add(owes, settlement.from_id, settlement.to_id, -settlement.amount_cents)
    rank = rank_by(ledger.member_order)
    transfers = [
        Transfer(a, b, amount) if amount > 0 else Transfer(b, a, -amount)
        for (a, b), amount in owes.items()
        if amount != 0
    ]
    return tuple(sorted(transfers, key=lambda t: (rank(t.from_id), rank(t.to_id))))


def _add(owes: dict[tuple[str, str], int], debtor: str, creditor: str, cents: int) -> None:
    """Keep one signed entry per unordered pair, keyed (smaller id, larger id)."""
    if debtor < creditor:
        owes[(debtor, creditor)] = owes.get((debtor, creditor), 0) + cents
    else:
        owes[(creditor, debtor)] = owes.get((creditor, debtor), 0) - cents


def rank_by(order: Sequence[str]) -> Callable[[str], tuple[int, str]]:
    """Sort key: position in `order`, people not in it after everyone else, then by id."""
    position = {person: n for n, person in enumerate(order)}
    return lambda person: (position.get(person, len(position)), person)


def _ordered(people: dict[str, int], order: Sequence[str]) -> list[str]:
    known = [p for p in order if p in people]
    return known + sorted(p for p in people if p not in set(order))
