"""Payments and square-up between two people (SPEC 9, 10.6).

Recording a payment or squaring up moves money in the ledger, so it is restated and needs a
"yes" (SPEC 12.3). The restatement is pinned to a ledger version: if a bill or payment between
the two arrives before the "yes", it is restated again rather than applied to stale balances.
Disputing ("not received") or undoing your own payment reverses it at once.
"""

from collections.abc import Callable, Sequence
from dataclasses import replace

from smartsplit.domain.commands import RecordPayment, SquareUp
from smartsplit.domain.enums import NotificationKind, PromptKind, SettlementKind
from smartsplit.domain.model import Settlement
from smartsplit.domain.prompts import ConfirmActionPayload, NotificationArgs, PaymentEffect
from smartsplit.domain.values import Context, GroupContext, PersonalContext
from smartsplit.ledger import allocate_payment, square_up
from smartsplit.ports.repository import UnitOfWork
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.ledgers import between_text, context_name, ledgers_for
from smartsplit.services.names import Directory
from smartsplit.services.notifications import notify
from smartsplit.services.prompting import open_prompt
from smartsplit.services.queries import group_named
from smartsplit.services.text import money, name_for
from smartsplit.services.turn import Turn

PERSONAL_WORDS = frozenset({"personal", "personal splits", "me", "us"})


def ledger_version(uow: UnitOfWork, people: Sequence[str]) -> int:
    """Grows with every bill or settlement any of these people is in."""
    return sum(
        len(uow.bills.for_participant(p)) + len(uow.settlements.for_person(p)) for p in people
    )


def propose_payment(turn: Turn, command: RecordPayment, directory: Directory) -> None:
    """ "paid Sam 500" or "Raj paid me 500": allocated per SPEC 9, restated, confirmed."""
    region = turn.settings.default_region
    me = turn.speaker.id
    payer = directory.resolve(command.payer, region) if command.payer else me
    payee = directory.resolve(command.payee, region) if command.payee else me
    if me not in (payer, payee):
        raise NotAllowedError("You can record payments you made or received.")
    if payer == payee:
        raise NotAllowedError("Who was the payment to?")
    named = _named_context(turn, command.context_name)
    ledgers = ledgers_for(turn.uow, payer)
    allocations, overpaid = allocate_payment(payer, payee, command.amount, ledgers, named)
    payment_id = turn.ids.new_id()
    rows = tuple(
        Settlement(
            turn.ids.new_id(),
            payment_id,
            a.context,
            payer,
            payee,
            a.amount_cents,
            SettlementKind.PAYMENT,
            me,
            None,
            turn.now,
        )
        for a in allocations
    )
    currency = turn.settings.currency
    parts = ", ".join(
        f"{context_name(turn.uow, a.context)} {money(a.amount_cents, currency)}"
        for a in allocations
    )
    text = (
        f"Record: {_name(turn, payer)} paid {_name(turn, payee)} "
        f"{money(command.amount, currency)} ({parts})?"
    )
    if overpaid:
        text += f" That's {money(overpaid, currency)} more than was owed; it stays as credit."
    _ask(turn, command, PaymentEffect(rows, overpaid), (payer, payee), text)


def propose_square_up(turn: Turn, command: SquareUp, directory: Directory) -> None:
    """Every group between the two is cleared; the overall moves to personal splits."""
    me = turn.speaker.id
    other = directory.resolve(command.with_person, turn.settings.default_region)
    if other == me:
        raise NotAllowedError("Square up with whom?")
    moves = square_up(me, other, ledgers_for(turn.uow, me))
    if not moves:
        raise NotAllowedError(f"There's nothing to square up with {_name(turn, other)}.")
    payment_id = turn.ids.new_id()
    rows = tuple(
        Settlement(
            turn.ids.new_id(),
            payment_id,
            context,
            t.from_id,
            t.to_id,
            t.amount_cents,
            SettlementKind.SQUARE_UP,
            me,
            None,
            turn.now,
        )
        for context, t in moves
    )
    groups = [context_name(turn.uow, c) for c, _ in moves if isinstance(c, GroupContext)]
    text = (
        f"Square up with {_name(turn, other)}: {', '.join(groups)} cleared, and what's left "
        "moves to your personal splits. No money changes hands."
    )
    _ask(turn, command, PaymentEffect(rows, 0), (me, other), text)


def apply_payment(turn: Turn, payload: ConfirmActionPayload, effect: PaymentEffect) -> None:
    """Write the restated rows if nothing between the two changed since; tell the other one."""
    first = effect.settlements[0]
    people = (first.from_id, first.to_id)
    if ledger_version(turn.uow, people) != payload.based_on_version:
        turn.reply("Balances changed meanwhile, so I didn't record it. Say it again?")
        return
    for row in effect.settlements:
        turn.uow.settlements.add(replace(row, created_at=turn.now))
    other = first.to_id if first.from_id == turn.speaker.id else first.from_id
    if first.kind is SettlementKind.SQUARE_UP:
        kind, done = NotificationKind.SQUARE_UP, "Squared up."
    else:
        kind, done = NotificationKind.PAYMENT_RECORDED, "Recorded."
    total = sum(r.amount_cents for r in effect.settlements if r.from_id == first.from_id)
    notify(
        turn,
        other,
        kind,
        payment_id=first.payment_id,
        args=NotificationArgs(amount_cents=total),
    )
    turn.reply(f"{done}\n{between_text(turn.uow, turn.speaker.id, other, turn.settings.currency)}")


def not_received(turn: Turn) -> None:
    """The other side of the latest payment someone else recorded with you disputes it."""
    me = turn.speaker.id
    rows = _latest(turn, lambda s: me in (s.from_id, s.to_id) and s.recorded_by != me)
    if not rows:
        raise NotAllowedError("There's no payment from someone else to dispute.")
    _reverse(turn, rows, "not received")


def undo_payment(turn: Turn) -> None:
    """Only whoever recorded it can undo it (SPEC 10.6)."""
    rows = _latest(turn, lambda s: s.recorded_by == turn.speaker.id)
    if not rows:
        raise NotAllowedError("You haven't recorded a payment to undo.")
    _reverse(turn, rows, "undone")


def _latest(turn: Turn, mine: Callable[[Settlement], bool]) -> tuple[Settlement, ...]:
    """The rows of the newest live payment (not a square-up) matching `mine`."""
    rows = turn.uow.settlements.for_person(turn.speaker.id)
    reversed_ids = {s.reverses_id for s in rows if s.reverses_id}
    live = [
        s
        for s in rows
        if s.kind is SettlementKind.PAYMENT
        and s.reverses_id is None
        and s.id not in reversed_ids
        and mine(s)
    ]
    if not live:
        return ()
    payment_id = live[-1].payment_id
    return tuple(s for s in live if s.payment_id == payment_id)


def _reverse(turn: Turn, rows: tuple[Settlement, ...], why: str) -> None:
    payment_id = turn.ids.new_id()
    for row in rows:
        turn.uow.settlements.add(
            replace(
                row,
                id=turn.ids.new_id(),
                payment_id=payment_id,
                amount_cents=-row.amount_cents,
                recorded_by=turn.speaker.id,
                reverses_id=row.id,
                created_at=turn.now,
            )
        )
    first = rows[0]
    other = first.to_id if first.from_id == turn.speaker.id else first.from_id
    total = sum(r.amount_cents for r in rows)
    notify(
        turn,
        other,
        NotificationKind.PAYMENT_REVERSED,
        payment_id=payment_id,
        args=NotificationArgs(reason=why, amount_cents=total),
    )
    currency = turn.settings.currency
    turn.reply(
        f"Undid the {money(total, currency)} payment between you and {_name(turn, other)}.\n"
        f"{between_text(turn.uow, turn.speaker.id, other, currency)}"
    )


def _named_context(turn: Turn, said: str | None) -> Context | None:
    """The group chat it was said in, or the context named ("for the trip")."""
    if turn.conversation.group_id is not None:
        return GroupContext(turn.conversation.group_id)
    if said is None:
        return None
    if said.strip().casefold() in PERSONAL_WORDS:
        return PersonalContext()
    return GroupContext(group_named(turn, said))


def _ask(
    turn: Turn,
    command: RecordPayment | SquareUp,
    effect: PaymentEffect,
    people: tuple[str, str],
    text: str,
) -> None:
    payload = ConfirmActionPayload(command, effect, ledger_version(turn.uow, people))
    open_prompt(turn, None, PromptKind.CONFIRM_ACTION, payload, turn.speaker.id)
    turn.reply(f'{text} Say "yes" to confirm.')


def _name(turn: Turn, person_id: str) -> str:
    if person_id == turn.speaker.id:
        return "you"
    return name_for(turn.uow, None if turn.in_group else turn.speaker.id, person_id)
