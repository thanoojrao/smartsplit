"""Things you ask for yourself: nudging someone, your history, stop and start (10.7, 10.8)."""

from dataclasses import replace
from datetime import date, timedelta

from smartsplit.domain.commands import Remind, ShowHistory
from smartsplit.domain.enums import NotificationKind
from smartsplit.services.bill_changes import is_live
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.ledgers import between_net, share_of
from smartsplit.services.names import Directory
from smartsplit.services.notifications import notify, remember_listed
from smartsplit.services.queries import send_privately
from smartsplit.services.text import day_label, money, name_for
from smartsplit.services.turn import Turn

HISTORY_DEFAULT = 5


def remind(turn: Turn, command: Remind, directory: Directory) -> None:
    """A friendly nudge with their balance: once a day per pair, and only to people who use
    the bot and haven't said "stop" (SPEC 10.8)."""
    other = directory.resolve(command.person, turn.settings.default_region)
    person = turn.uow.people.get(other)
    name = name_for(turn.uow, None if turn.in_group else turn.speaker.id, other)
    if person is None or other == turn.speaker.id:
        raise NotAllowedError("Remind whom?")
    if not person.has_used_bot or not person.notifications_enabled:
        raise NotAllowedError(f"{name} doesn't get messages from me, so I can't remind them.")
    if between_net(turn.uow, turn.speaker.id, other) <= 0:
        # said in a group too, so it mustn't reveal balances from elsewhere
        raise NotAllowedError("I can only remind people who owe you overall.")
    since = turn.now - turn.settings.remind_once_per
    kind = NotificationKind.REMINDER
    if turn.uow.notifications.exists_since(turn.speaker.id, other, kind, since):
        raise NotAllowedError(f"I already reminded {name} today.")
    notify(turn, other, kind)
    turn.reply(f"OK, I'll remind {name}.")


def set_notifications(turn: Turn, on: bool) -> None:
    """ "stop" holds every message and reminder for you; "start" lets them through again."""
    turn.uow.people.update(replace(turn.speaker, notifications_enabled=on))
    if on:
        turn.reply("OK, you'll hear from me again.")
    else:
        turn.reply('OK, I won\'t message you. Say "start" to undo.')


def show_history(turn: Turn, command: ShowHistory) -> None:
    """ "what did I spend this month?" sums your shares by purchase date; "last 5 bills"
    lists them, numbered for "details 2". In a group it goes to your personal chat."""
    me, currency = turn.speaker.id, turn.settings.currency
    bills = [b for b in turn.uow.bills.for_participant(me) if b.reverses_id is None]
    if command.period is not None:
        start, end = _month(turn.today, command.period)
        chosen = [b for b in bills if start <= b.purchased_at < end and is_live(turn, b)]
        total = sum(share_of(b, me) for b in chosen)
        heading = f"You spent {money(total, currency)} {command.period.replace('_', ' ')}."
    else:
        live = [b for b in bills if is_live(turn, b)]
        chosen = live[-(command.last_n or HISTORY_DEFAULT) :][::-1]
        count = len(chosen)
        heading = (
            "No bills yet."
            if not chosen
            else "Your last bill:"
            if count == 1
            else f"Your last {count} bills:"
        )
    rows = [
        f"{n}. {b.description} ({day_label(b.purchased_at)}): {money(share_of(b, me), currency)}"
        for n, b in enumerate(chosen, 1)
    ]
    text = "\n".join([heading, *rows])
    if turn.in_group:
        send_privately(turn, text)
        chat = turn.uow.conversations.personal_for(me)
    else:
        turn.reply(text)
        chat = turn.uow.conversations.get(turn.conversation.key)
    if chat is not None:
        remember_listed(turn.uow, chat, [b.id for b in chosen])


def _month(today: date, period: str) -> tuple[date, date]:
    """[start, end) of this or last calendar month."""
    first = today.replace(day=1)
    if period == "this_month":
        return first, (first + timedelta(days=32)).replace(day=1)
    return (first - timedelta(days=1)).replace(day=1), first
