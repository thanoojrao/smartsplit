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
from smartsplit.services.ledgers import between_net
from smartsplit.services.text import money, name_for
from smartsplit.services.turn import Turn

REPLY_HINT = 'Reply "ok", "details", "not mine", or tell me what to fix.'


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
    """One message for everything claimed for one person, and the bills it lists in order."""
    added = [n for n in batch if n.kind is NotificationKind.BILL_ADDED]
    others = [n for n in batch if n.kind is not NotificationKind.BILL_ADDED]
    parts: list[str] = []
    listed: list[str] = []
    if added:
        text, ids = _bills_added(uow, recipient_id, added, currency)
        parts.append(text)
        listed += ids
    for notification in others:
        parts.append(_one(uow, recipient_id, notification, currency))
        listed += notification.bill_ids
    return "\n\n".join(parts), tuple(listed)


def _bills_added(
    uow: UnitOfWork, me: str, added: Sequence[Notification], currency: str
) -> tuple[str, list[str]]:
    bills = [b for n in added for b in [uow.bills.get(n.bill_ids[0])] if b is not None]
    actors = list(dict.fromkeys(b.added_by for b in bills))
    if len(bills) == 1:
        bill = bills[0]
        who = name_for(uow, me, bill.added_by)
        lines = [
            f"{who} added {bill.description} ({_day(bill)}): your share is "
            f"{money(_share(bill, me), currency)}.",
        ]
    else:
        who = ", ".join(name_for(uow, me, a) for a in actors)
        lines = [f"{who} added {len(bills)} bills:"]
        lines += [
            f"{n}. {b.description} ({_day(b)}): your share {money(_share(b, me), currency)}"
            for n, b in enumerate(bills, 1)
        ]
    lines += [_overall(uow, me, actor, currency) for actor in actors]
    lines.append(REPLY_HINT if len(bills) == 1 else 'Reply "details 2", "not mine 2", or "ok".')
    return "\n".join(lines), [b.id for b in bills]


def _one(uow: UnitOfWork, me: str, notification: Notification, currency: str) -> str:
    actor = name_for(uow, me, notification.actor_id)
    args = notification.text_args
    amount = money(args.amount_cents or 0, currency)
    because = f" ({args.reason})" if args.reason else ""
    overall = _overall(uow, me, notification.actor_id, currency)
    match notification.kind:
        case NotificationKind.BILL_CHANGED:
            bill = uow.bills.get(notification.bill_ids[0]) if notification.bill_ids else None
            if bill is None or bill.reverses_id is not None:
                what = "a bill you were in" if bill is None else bill.description
                text = f"{actor} deleted {what}{because}."
            else:
                share = money(_share(bill, me), currency)
                text = f"{actor} changed {bill.description}{because}: your share is now {share}."
            return f"{text}\n{overall}"
        case NotificationKind.PAYMENT_RECORDED:
            rows = uow.settlements.for_payment(notification.payment_id or "")
            if rows and rows[0].from_id == me:
                what = f"{actor} recorded that you paid them {amount}."
            else:
                what = f"{actor} says they paid you {amount}."
            return f'{what}\n{overall}\nReply "not received" if it didn\'t happen.'
        case NotificationKind.PAYMENT_REVERSED:
            return f"{actor} undid the {amount} payment between you two{because}."
        case NotificationKind.SQUARE_UP:
            return f"{actor} squared up with you.\n{overall}"
        case NotificationKind.REMINDER:
            return f"A friendly nudge from {actor}: {overall}"
        case NotificationKind.BILL_ADDED | NotificationKind.REQUESTED_REPLY:
            return args.body or ""


def _overall(uow: UnitOfWork, me: str, other: str, currency: str) -> str:
    net = between_net(uow, me, other)
    name = name_for(uow, me, other)
    if net > 0:
        return f"Overall {name} owes you {money(net, currency)}."
    if net < 0:
        return f"Overall you owe {name} {money(-net, currency)}."
    return f"You and {name} are settled up."


def _share(bill: Bill, person_id: str) -> int:
    return sum(s.cents for s in bill.shares if s.person_id == person_id)


def _day(bill: Bill) -> str:
    return f"{bill.purchased_at.day} {bill.purchased_at:%b}"


def remember_listed(uow: UnitOfWork, chat: Conversation, bill_ids: Sequence[str]) -> None:
    """So "details 2" and "not mine 2" mean the bills just listed in that chat."""
    if bill_ids:
        uow.conversations.update(replace(chat, last_listed_bill_ids=tuple(bill_ids)))
