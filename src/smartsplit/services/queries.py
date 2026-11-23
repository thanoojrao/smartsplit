"""Balances and draft details, answered where privacy allows (SPEC 10.7).

A group chat only ever hears about that group. Anything wider goes to the asker's own chat.
"""

from smartsplit.domain.commands import ShowBalances
from smartsplit.domain.values import GroupContext
from smartsplit.ledger import pair_debts
from smartsplit.ledger.overall import owed_to
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.ledgers import (
    between_text,
    group_balances_text,
    group_ledger,
    has_balances_elsewhere,
    overall_text,
)
from smartsplit.services.names import Directory
from smartsplit.services.text import money, name_for
from smartsplit.services.turn import Turn


def show_balances(turn: Turn, command: ShowBalances, directory: Directory) -> None:
    uow, me, currency = turn.uow, turn.speaker.id, turn.settings.currency
    other = (
        directory.resolve(command.with_person, turn.settings.default_region)
        if command.with_person
        else None
    )
    group_id = turn.conversation.group_id
    named_group = group_named(turn, command.group_name) if command.group_name else None
    if group_id is not None and named_group in (None, group_id):
        if other is None:
            turn.reply(group_balances_text(uow, group_id, currency))
        else:
            turn.reply(_pair_here(turn, group_id, other))
        if has_balances_elsewhere(uow, me, GroupContext(group_id)):
            wider = (
                between_text(uow, me, other, currency) if other else overall_text(uow, me, currency)
            )
            send_privately(turn, wider)
        return
    if named_group is not None:
        text = group_balances_text(uow, named_group, currency)
        if group_id is None:
            turn.reply(text)
        else:
            send_privately(turn, text)
        return
    turn.reply(between_text(uow, me, other, currency) if other else overall_text(uow, me, currency))


def _pair_here(turn: Turn, group_id: str, other: str) -> str:
    me, currency = turn.speaker.id, turn.settings.currency
    cents = owed_to(me, pair_debts(group_ledger(turn.uow, group_id))).get(other, 0)
    name = name_for(turn.uow, None, other)
    if cents > 0:
        return f"Here, {name} owes you {money(cents, currency)}."
    if cents < 0:
        return f"Here, you owe {name} {money(-cents, currency)}."
    return f"You and {name} are settled up here."


def send_privately(turn: Turn, text: str) -> None:
    """Wider answers go to the asker's personal chat, never to the group (10.7)."""
    if turn.direct(turn.speaker.id, text):
        turn.reply("I sent you the rest in a DM.")
    else:
        turn.reply("Message me 1:1 and I'll send you the rest there.")


def group_named(turn: Turn, name: str) -> str:
    """One of the speaker's groups, current or past, by name."""
    wanted = name.strip().casefold()
    for membership in turn.uow.memberships.for_person(turn.speaker.id):
        group = turn.uow.groups.get(membership.group_id)
        if group is not None and group.name.casefold() == wanted:
            return group.id
    raise NotAllowedError(f"You're not in a group called {name}.")
