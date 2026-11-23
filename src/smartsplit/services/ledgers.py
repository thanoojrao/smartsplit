"""Reading ledgers from the repository and putting balances into words (SPEC 9, 10.7)."""

from smartsplit.domain.values import Context, GroupContext, PersonalContext
from smartsplit.ledger import (
    ContextLedger,
    OverallBalance,
    overall_between,
    overall_for,
    pair_debts,
)
from smartsplit.ports.repository import UnitOfWork
from smartsplit.services.text import money, name_for


def group_ledger(uow: UnitOfWork, group_id: str) -> ContextLedger:
    """Every membership ever, by position: leavers keep their place for rounding and order."""
    context = GroupContext(group_id)
    order = tuple(
        m.person_id for m in sorted(uow.memberships.for_group(group_id), key=lambda m: m.position)
    )
    return ContextLedger(
        context,
        tuple(dict.fromkeys(order)),
        uow.bills.for_context(context),
        uow.settlements.for_context(context),
    )


def personal_ledger(uow: UnitOfWork, person_id: str) -> ContextLedger:
    """The personal splits this person is in, and the personal settlements they are part of."""
    context = PersonalContext()
    bills = tuple(b for b in uow.bills.for_participant(person_id) if b.context == context)
    settlements = tuple(
        s for s in uow.settlements.for_context(context) if person_id in (s.from_id, s.to_id)
    )
    people = sorted({p for b in bills for p in b.participants} | {person_id})
    return ContextLedger(context, tuple(people), bills, settlements)


def ledgers_for(uow: UnitOfWork, person_id: str) -> tuple[ContextLedger, ...]:
    """Every group the person was ever in, then their personal splits."""
    group_ids = dict.fromkeys(m.group_id for m in uow.memberships.for_person(person_id))
    return (*(group_ledger(uow, g) for g in group_ids), personal_ledger(uow, person_id))


def group_balances_text(uow: UnitOfWork, group_id: str, currency: str) -> str:
    """The few payments that settle the group (the simplified plan), or "all settled"."""
    transfers = pair_debts(group_ledger(uow, group_id))
    if not transfers:
        return "Everyone is settled up here."
    lines = [
        f"{name_for(uow, None, t.from_id)} owes {name_for(uow, None, t.to_id)} "
        f"{money(t.amount_cents, currency)}"
        for t in transfers
    ]
    return "\n".join(lines)


def overall_text(uow: UnitOfWork, person_id: str, currency: str) -> str:
    """ "what do I owe?": one net line per person, from the asker's side, largest first."""
    totals = sorted(
        (b for b in overall_for(person_id, ledgers_for(uow, person_id)) if b.net_cents),
        key=lambda b: (-abs(b.net_cents), b.other_id),
    )
    if not totals:
        return "You're all settled up."
    return "\n".join(_net_line(uow, person_id, b, currency) for b in totals)


def between_text(uow: UnitOfWork, person_id: str, other_id: str, currency: str) -> str:
    """ "what do I owe Sam?": the net, then where it comes from."""
    balance = overall_between(person_id, other_id, ledgers_for(uow, person_id))
    if not balance.breakdown:
        return f"You and {name_for(uow, person_id, other_id)} are settled up."
    lines = [_net_line(uow, person_id, balance, currency)]
    lines += [
        f"  {context_name(uow, context)}: {_signed(cents, currency)}"
        for context, cents in balance.breakdown
    ]
    return "\n".join(lines)


def context_name(uow: UnitOfWork, context: Context) -> str:
    if isinstance(context, GroupContext):
        group = uow.groups.get(context.group_id)
        return group.name if group else "a group"
    return "personal splits"


def _net_line(uow: UnitOfWork, me: str, balance: OverallBalance, currency: str) -> str:
    name = name_for(uow, me, balance.other_id)
    if balance.net_cents > 0:
        return f"{name} owes you {money(balance.net_cents, currency)}"
    if balance.net_cents < 0:
        return f"You owe {name} {money(-balance.net_cents, currency)}"
    return f"You and {name} are even overall"


def _signed(cents: int, currency: str) -> str:
    return (
        f"owes you {money(cents, currency)}" if cents > 0 else f"you owe {money(-cents, currency)}"
    )


def has_balances_elsewhere(uow: UnitOfWork, person_id: str, here: Context) -> bool:
    """Whether anything is open for this person outside one context."""
    return any(
        cents
        for balance in overall_for(person_id, ledgers_for(uow, person_id))
        for context, cents in balance.breakdown
        if context != here
    )


def between_net(uow: UnitOfWork, person_id: str, other_id: str) -> int:
    """What `other_id` owes `person_id` overall (< 0: the other way round)."""
    return overall_between(person_id, other_id, ledgers_for(uow, person_id)).net_cents
