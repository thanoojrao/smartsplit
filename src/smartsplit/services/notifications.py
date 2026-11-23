"""The outbox: messages to people's own chats, written now and rendered when sent (10.5, 10.8).

Rendering at send time means the balance in a message is the balance when it arrives. Several
bills to one person in one delivery become one numbered message ("details 2").
"""

from collections.abc import Sequence
from dataclasses import replace

from smartsplit.domain.enums import NotificationKind
from smartsplit.domain.model import Bill, Conversation
from smartsplit.domain.prompts import Notification, NotificationArgs
from smartsplit.ports.repository import UnitOfWork
from smartsplit.services.ledgers import between_net, share_of
from smartsplit.services.text import day_label, money, name_for
from smartsplit.services.turn import Turn

REPLY_HINT = 'Reply "ok", "details", "not mine", or tell me what to fix.'
MANY_HINT = 'Reply "details 2", "not mine 2", or "ok".'


def notify(
    turn: Turn,
    recipient_id: str,
    kind: NotificationKind,
    *,
    bill_ids: Sequence[str] = (),
    payment_id: str | None = None,
    args: NotificationArgs | None = None,
) -> None:
    """Queue a message for someone's own chat; `tick` sends it (held while they haven't used
    the bot or have said "stop")."""
    turn.uow.notifications.add(
        Notification(
            turn.ids.new_id(),
            recipient_id,
            turn.speaker.id,
            kind,
            tuple(bill_ids),
            payment_id,
            args or NotificationArgs(),
            turn.now,
            None,
        )
    )


def tell_participants(
    turn: Turn,
    bill: Bill,
    kind: NotificationKind,
    reason: str | None,
    *,
    also: Sequence[str] = (),
) -> None:
    """Everyone in a personal split but the speaker hears about it (10.5); `also` adds the
    people an edit took out of the bill."""
    for person_id in dict.fromkeys([*bill.participants, *also]):
        if person_id != turn.speaker.id:
            notify(turn, person_id, kind, bill_ids=(bill.id,), args=NotificationArgs(reason))


def invites_for(turn: Turn, bill: Bill) -> list[str]:
    """People in this bill who have never used the bot, on the adder's first bill with them."""
    names = []
    for person_id in bill.participants:
        person = turn.uow.people.get(person_id)
        if person is None or person.has_used_bot or person_id == turn.speaker.id:
            continue
        earlier = [
            b
            for b in turn.uow.bills.for_participant(person_id)
            if b.id != bill.id and turn.speaker.id in b.participants
        ]
        if not earlier:
            names.append(name_for(turn.uow, turn.speaker.id, person_id))
    return names


def render(
    uow: UnitOfWork, recipient_id: str, batch: Sequence[Notification], currency: str
) -> tuple[str, tuple[str, ...]]:
    """One message for everything claimed for one person, and the bills it numbers, in
    order ("details 2"). Each person's overall balance is said once, at the end."""
    added = [n for n in batch if n.kind is NotificationKind.BILL_ADDED]
    others = [n for n in batch if n.kind is not NotificationKind.BILL_ADDED]
    parts: list[str] = []
    listed: list[str] = []
    if added:
        text, listed = _bills_added(uow, recipient_id, added, currency)
        parts.append(text)
    parts += [_one(uow, recipient_id, n, currency) for n in others]
    if not listed:
        listed = [i for n in others for i in n.bill_ids]
    actors = dict.fromkeys(n.actor_id for n in batch)
    parts += [_overall(uow, recipient_id, actor, currency) for actor in actors]
    if added:
        parts.append(REPLY_HINT if len(listed) == 1 else MANY_HINT)
    elif any(n.kind is NotificationKind.PAYMENT_RECORDED for n in others):
        parts.append('Reply "not received" if a payment didn\'t happen.')
    return "\n".join(parts), tuple(listed)


def _bills_added(
    uow: UnitOfWork, me: str, added: Sequence[Notification], currency: str
) -> tuple[str, list[str]]:
    bills = [b for n in added for b in [uow.bills.get(n.bill_ids[0])] if b is not None]
    if len(bills) == 1:
        bill = bills[0]
        who = name_for(uow, me, bill.added_by)
        share = money(share_of(bill, me), currency)
        day = day_label(bill.purchased_at)
        return f"{who} added {bill.description} ({day}): your share is {share}.", [bill.id]
    actors = dict.fromkeys(b.added_by for b in bills)
    lines = [f"{', '.join(name_for(uow, me, a) for a in actors)} added {len(bills)} bills:"]
    lines += [
        f"{n}. {b.description} ({day_label(b.purchased_at)}): your share "
        f"{money(share_of(b, me), currency)}"
        for n, b in enumerate(bills, 1)
    ]
    return "\n".join(lines), [b.id for b in bills]


def _one(uow: UnitOfWork, me: str, notification: Notification, currency: str) -> str:
    """One non-bill message; the overall balance is added once by `render`."""
    actor = name_for(uow, me, notification.actor_id)
    args = notification.text_args
    amount = money(args.amount_cents or 0, currency)
    because = f" ({args.reason})" if args.reason else ""
    match notification.kind:
        case NotificationKind.BILL_CHANGED:
            return _bill_changed(uow, me, notification, currency)
        case NotificationKind.PAYMENT_RECORDED:
            rows = uow.settlements.for_payment(notification.payment_id or "")
            if rows and rows[0].from_id == me:
                return f"{actor} recorded that you paid them {amount}."
            return f"{actor} says they paid you {amount}."
        case NotificationKind.PAYMENT_REVERSED:
            return f"{actor} undid the {amount} payment between you two{because}."
        case NotificationKind.SQUARE_UP | NotificationKind.REMINDER:
            return _SIMPLE[notification.kind].format(actor=actor)
        case NotificationKind.BILL_ADDED | NotificationKind.REQUESTED_REPLY:
            # bills added are rendered together by `render`; a requested reply carries text
            return args.body or ""


_SIMPLE = {
    NotificationKind.SQUARE_UP: "{actor} squared up with you.",
    NotificationKind.REMINDER: "A friendly nudge from {actor}.",
}


def _bill_changed(uow: UnitOfWork, me: str, notification: Notification, currency: str) -> str:
    actor = name_for(uow, me, notification.actor_id)
    reason = notification.text_args.reason
    because = f" ({reason})" if reason else ""
    bill = uow.bills.get(notification.bill_ids[0]) if notification.bill_ids else None
    if bill is None or bill.reverses_id is not None:
        what = "a bill you were in" if bill is None else bill.description
        return f"{actor} deleted {what}{because}."
    share = money(share_of(bill, me), currency)
    return f"{actor} changed {bill.description}{because}: your share is now {share}."


def _overall(uow: UnitOfWork, me: str, other: str, currency: str) -> str:
    net = between_net(uow, me, other)
    name = name_for(uow, me, other)
    if net > 0:
        return f"Overall {name} owes you {money(net, currency)}."
    if net < 0:
        return f"Overall you owe {name} {money(-net, currency)}."
    return f"You and {name} are settled up."


def remember_listed(uow: UnitOfWork, chat: Conversation, bill_ids: Sequence[str]) -> None:
    """So "details 2" and "not mine 2" mean the bills just listed in that chat."""
    if bill_ids:
        uow.conversations.update(replace(chat, last_listed_bill_ids=tuple(bill_ids)))
