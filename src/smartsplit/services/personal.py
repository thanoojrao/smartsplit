"""Things you ask for yourself: nudging someone, your bills and history, stop and start
(SPEC 10.7, 10.8)."""

from dataclasses import replace
from datetime import date, timedelta

from smartsplit.domain import normalize_item_name
from smartsplit.domain.enums import NotificationKind
from smartsplit.domain.model import Bill
from smartsplit.domain.prompts import ChatRef
from smartsplit.domain.tools import ListBills
from smartsplit.domain.values import GroupContext
from smartsplit.services.bill_status import is_live
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.ledgers import between_net, share_of
from smartsplit.services.notifications import notify
from smartsplit.services.text import day_label, money, name_for
from smartsplit.services.turn import Turn

HISTORY_DEFAULT = 5
HISTORY_MAX = 20


def remind(turn: Turn, other: str) -> None:
    """A friendly nudge with their balance: once a day per pair, and only to people who use
    the bot and haven't said "stop" (SPEC 10.8). Asked in a group, the outcome goes to the
    speaker's own chat either way: whether it can be sent depends on balances elsewhere,
    which the group mustn't learn (SPEC 12.3)."""
    if turn.uow.people.get(other) is None or other == turn.speaker.id:
        raise NotAllowedError("Remind whom?")
    if turn.in_group and turn.uow.conversations.personal_for(turn.speaker.id) is None:
        raise NotAllowedError("Message me 1:1 first, and I'll tell you there.")
    name = name_for(turn.uow, turn.speaker.id, other)
    try:
        _check_remindable(turn, other, name)
    except NotAllowedError as refused:
        if not turn.in_group:
            raise
        turn.direct(turn.speaker.id, str(refused))
        turn.acted = True
        return
    notify(turn, other, NotificationKind.REMINDER)
    if turn.in_group:
        turn.direct(turn.speaker.id, f"I'll remind {name}.")
    turn.acted = True


def _check_remindable(turn: Turn, other: str, name: str) -> None:
    person = turn.uow.people.get(other)
    if person is None or not person.has_used_bot or not person.notifications_enabled:
        raise NotAllowedError(f"{name} doesn't get messages from me, so I can't remind them.")
    if between_net(turn.uow, turn.speaker.id, other) <= 0:
        raise NotAllowedError("I can only remind people who owe you overall.")
    since = turn.now - turn.settings.remind_once_per
    if turn.uow.notifications.exists_since(
        turn.speaker.id, other, NotificationKind.REMINDER, since
    ):
        raise NotAllowedError(f"I already reminded {name} today.")


def set_notifications(turn: Turn, on: bool) -> None:
    """ "stop" holds every message and reminder for you; "start" lets them through again."""
    turn.uow.people.update(replace(turn.speaker, notifications_enabled=on))
    turn.speaker = replace(turn.speaker, notifications_enabled=on)
    turn.acted = True


def list_bills(turn: Turn, args: ListBills, person: str | None) -> None:
    """ "what did I spend this month?" sums your shares by purchase date; "last 5 bills",
    "the Toit bill" and "bills with Sam" list them, each a reference for "details on the
    second one". In a group chat the group's bills are listed there; your own history
    (a period) goes to your personal chat (SPEC 10.7)."""
    me = turn.speaker.id
    private = turn.in_group and args.period is not None
    bills = _visible(turn, private)
    if args.text:
        wanted = normalize_item_name(args.text)
        bills = [b for b in bills if wanted in normalize_item_name(b.description)]
    if person is not None:
        bills = [b for b in bills if person in b.participants]
    currency = turn.settings.currency
    if args.period is not None:
        start, end = _month(turn.today, args.period)
        chosen = [b for b in bills if start <= b.purchased_at < end]
        total = sum(share_of(b, me) for b in chosen)
        heading = f"You spent {money(total, currency)} {args.period.replace('_', ' ')}."
    else:
        count = min(args.last_n or HISTORY_DEFAULT, HISTORY_MAX)
        chosen = bills[-count:][::-1]
        heading = "No bills like that." if not chosen else f"{len(chosen)} bills, newest first:"
    rows = [
        f"{n}. {b.description} ({day_label(b.purchased_at)}): "
        f"{money(share_of(b, me) if me in b.participants else b.total_cents, currency)}"
        for n, b in enumerate(chosen, 1)
    ]
    text = "\n".join([heading, *rows])
    refs = tuple(ChatRef("bill", b.id) for b in chosen)
    if private:
        if turn.direct(me, text, refs):
            turn.show("I sent that to you privately.")
        else:
            turn.show("Message me 1:1 first, and I'll send it there.")
        return
    turn.show(text, refs)


def _visible(turn: Turn, private: bool) -> list[Bill]:
    """Live bills, oldest first: the group's own in a group chat, else the speaker's."""
    if turn.conversation.group_id is not None and not private:
        seen = turn.uow.bills.for_context(GroupContext(turn.conversation.group_id))
    else:
        seen = turn.uow.bills.for_participant(turn.speaker.id)
    return [b for b in seen if is_live(turn.uow, b)]


def _month(today: date, period: str) -> tuple[date, date]:
    """[start, end) of this or last calendar month."""
    first = today.replace(day=1)
    if period == "this_month":
        return first, (first + timedelta(days=32)).replace(day=1)
    return (first - timedelta(days=1)).replace(day=1), first
