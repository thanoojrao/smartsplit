"""Payments, reversals and square-up between two people (SPEC 9, 10.6).

Every one of them moves money, so each is computed exactly, restated as a pending action and
applied on a later "yes" (SPEC 8.4). The effect is pinned to a ledger version: if a bill or
payment between the two arrives first, it is computed and asked again.
"""

from collections.abc import Callable, Sequence
from dataclasses import replace

from smartsplit.domain.enums import NotificationKind, SettlementKind
from smartsplit.domain.model import Settlement
from smartsplit.domain.prompts import ChatRef, NotificationArgs, PaymentEffect
from smartsplit.domain.tools import NotReceived, RecordPayment, SquareUp, UndoPayment
from smartsplit.domain.values import Context, GroupContext
from smartsplit.ledger import allocate_payment, square_up
from smartsplit.ports.repository import UnitOfWork
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.ledgers import between_text, context_name, group_balances_text, ledgers_for
from smartsplit.services.money_args import parse_money
from smartsplit.services.notifications import notify
from smartsplit.services.pending_types import Proposal
from smartsplit.services.text import money, name_for
from smartsplit.services.turn import Turn


def ledger_version(uow: UnitOfWork, people: Sequence[str]) -> int:
    """Grows with every bill or settlement that can move what these people owe each other:
    everything in each group either is in, and their own personal splits."""
    return sum(
        len(ledger.bills) + len(ledger.settlements)
        for person in people
        for ledger in ledgers_for(uow, person)
    )


def propose_payment(turn: Turn, args: RecordPayment) -> Proposal:
    """ "paid Sam 500" or "Raj paid me 500" (ids in `args`), allocated per SPEC 9."""
    me = turn.speaker.id
    payer, payee = args.from_person, args.to_person
    if me not in (payer, payee):
        raise NotAllowedError("You can record payments you made or received.")
    if payer == payee:
        raise NotAllowedError("Who was the payment to?")
    amount = parse_money(args.amount, turn.settings.max_amount_cents)
    named = _named_context(turn, args.group)
    allocations, overpaid = allocate_payment(
        payer, payee, amount, ledgers_for(turn.uow, payer), named
    )
    payment_id = turn.ids.new_id()
    rows = tuple(
        _row(
            turn,
            payment_id,
            context=a.context,
            from_id=payer,
            to_id=payee,
            cents=a.amount_cents,
            kind=SettlementKind.PAYMENT,
        )
        for a in allocations
    )
    currency = turn.settings.currency
    parts = ", ".join(
        f"{context_name(turn.uow, a.context)} {money(a.amount_cents, currency)}"
        for a in allocations
    )
    text = (
        f"Record: {_name(turn, payer)} paid {_name(turn, payee)} {money(amount, currency)} "
        f"({parts})?"
    )
    if overpaid:
        text += f" That's {money(overpaid, currency)} more than was owed; it stays as credit."
    version = ledger_version(turn.uow, (payer, payee))
    return Proposal(PaymentEffect(rows, overpaid), version, text)


def propose_square_up(turn: Turn, args: SquareUp) -> Proposal:
    """Every group between the two is cleared; the overall moves to personal splits."""
    me, other = turn.speaker.id, args.with_person
    if other == me:
        raise NotAllowedError("Square up with whom?")
    moves = square_up(me, other, ledgers_for(turn.uow, me))
    if not moves:
        raise NotAllowedError(f"There's nothing to square up with {_name(turn, other)}.")
    payment_id = turn.ids.new_id()
    rows = tuple(
        _row(
            turn,
            payment_id,
            context=context,
            from_id=t.from_id,
            to_id=t.to_id,
            cents=t.amount_cents,
            kind=SettlementKind.SQUARE_UP,
        )
        for context, t in moves
    )
    groups = [context_name(turn.uow, c) for c, _ in moves if isinstance(c, GroupContext)]
    where = "every group between you" if turn.in_group or not groups else ", ".join(groups)
    text = (
        f"Square up with {_name(turn, other)}: {where} cleared, and what's left moves to your "
        "personal splits. No money changes hands."
    )
    return Proposal(PaymentEffect(rows, 0), ledger_version(turn.uow, (me, other)), text)


def propose_reversal(turn: Turn, args: NotReceived | UndoPayment) -> Proposal:
    """ "Not received" by the other side, or "undo" by whoever recorded it (SPEC 10.6)."""
    me = turn.speaker.id
    if isinstance(args, NotReceived):
        rows = _payment(turn, args.payment, lambda s: s.recorded_by != me)
        if not rows:
            raise NotAllowedError("There's no payment someone else recorded with you.")
        why = "not received"
    else:
        rows = _payment(turn, args.payment, lambda s: s.recorded_by == me)
        if not rows:
            raise NotAllowedError("You haven't recorded a payment to undo.")
        why = "undone"
    payment_id = turn.ids.new_id()
    reversal = tuple(
        replace(
            row,
            id=turn.ids.new_id(),
            payment_id=payment_id,
            amount_cents=-row.amount_cents,
            recorded_by=me,
            reverses_id=row.id,
        )
        for row in rows
    )
    first = rows[0]
    other = first.to_id if first.from_id == me else first.from_id
    total = money(sum(r.amount_cents for r in rows), turn.settings.currency)
    verb = "Mark as not received" if why == "not received" else "Undo"
    text = f"{verb}: the {total} payment between you and {_name(turn, other)}?"
    version = ledger_version(turn.uow, (first.from_id, first.to_id))
    return Proposal(PaymentEffect(reversal, 0), version, text)


def apply_payment(turn: Turn, tool: str, effect: PaymentEffect) -> None:
    """Write the restated rows and tell the other person."""
    for row in effect.settlements:
        turn.uow.settlements.add(replace(row, created_at=turn.now))
    first = effect.settlements[0]
    other = first.to_id if first.from_id == turn.speaker.id else first.from_id
    total = sum(r.amount_cents for r in effect.settlements if r.from_id == first.from_id)
    if tool == "square_up":
        kind, done = NotificationKind.SQUARE_UP, "Squared up."
        args = NotificationArgs()
    elif first.reverses_id is not None:
        reason = "not received" if tool == "not_received" else "undone"
        kind, done = NotificationKind.PAYMENT_REVERSED, "Done, that payment is reversed."
        args = NotificationArgs(reason=reason, amount_cents=-total)
    else:
        kind, done = NotificationKind.PAYMENT_RECORDED, "Recorded."
        args = NotificationArgs(amount_cents=total)
    notify(turn, other, kind, payment_id=first.payment_id, args=args)
    _balances_after(turn, other, done, first.payment_id)


def _payment(
    turn: Turn, payment_id: str | None, mine: Callable[[Settlement], bool]
) -> tuple[Settlement, ...]:
    """The rows of one live payment (not a square-up) involving the speaker: the one named,
    or the newest matching `mine`. In a group chat, only that group's rows (SPEC 12.3)."""
    rows = turn.uow.settlements.for_person(turn.speaker.id)
    group_id = turn.conversation.group_id
    if group_id is not None:
        rows = tuple(s for s in rows if s.context == GroupContext(group_id))
    reversed_ids = {s.reverses_id for s in rows if s.reverses_id}
    live = [
        s
        for s in rows
        if s.kind is SettlementKind.PAYMENT
        and s.reverses_id is None
        and s.id not in reversed_ids
        and mine(s)
        and (payment_id is None or s.payment_id == payment_id)
    ]
    if not live:
        return ()
    chosen = live[-1].payment_id
    return tuple(s for s in live if s.payment_id == chosen)


def _balances_after(turn: Turn, other: str, done: str, payment_id: str) -> None:
    """In a group chat only that group's balances are shown; the overall goes privately."""
    currency = turn.settings.currency
    wider = between_text(turn.uow, turn.speaker.id, other, currency)
    refs = (ChatRef("payment", payment_id),)
    if turn.conversation.group_id is None:
        turn.show(f"{done}\n{wider}", refs)
        return
    turn.show(
        f"{done}\n{group_balances_text(turn.uow, turn.conversation.group_id, currency)}", refs
    )
    turn.direct(turn.speaker.id, wider)


def _named_context(turn: Turn, group_id: str | None) -> Context | None:
    """Said in a group chat: that group. Elsewhere: the group named, else allocated."""
    if turn.conversation.group_id is not None:
        return GroupContext(turn.conversation.group_id)
    return GroupContext(group_id) if group_id else None


def _row(
    turn: Turn,
    payment_id: str,
    *,
    context: Context,
    from_id: str,
    to_id: str,
    cents: int,
    kind: SettlementKind,
) -> Settlement:
    return Settlement(
        turn.ids.new_id(),
        payment_id,
        context,
        from_id,
        to_id,
        cents,
        kind,
        turn.speaker.id,
        None,
        turn.now,
    )


def _name(turn: Turn, person_id: str) -> str:
    if person_id == turn.speaker.id:
        return "you"
    return name_for(turn.uow, turn.viewer, person_id)
