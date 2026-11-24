"""Balances, answered where privacy allows (SPEC 10.7).

A group chat only ever hears about that group; anything wider goes to the asker's own chat,
and the model is only told that it was sent privately.
"""

from smartsplit.ledger import pair_debts
from smartsplit.ledger.overall import owed_to
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.ledgers import (
    between_text,
    group_balances_text,
    group_ledger,
    overall_text,
)
from smartsplit.services.text import money, name_for
from smartsplit.services.turn import Turn


def get_balances(turn: Turn, other: str | None, group_id: str | None, overall: bool) -> bool:
    """Show balances; True if (part of) the answer went to the asker's personal chat."""
    uow, me, currency = turn.uow, turn.speaker.id, turn.settings.currency
    here = turn.conversation.group_id
    if here is not None:
        if group_id is not None and group_id != here:
            wider = (
                between_text(uow, me, other, currency)
                if other
                else group_balances_text(uow, group_id, currency)
            )
            return send_privately(turn, wider)
        if not overall or group_id == here:
            turn.show(
                _pair_here(turn, here, other) if other else group_balances_text(uow, here, currency)
            )
        if overall:
            wider = (
                between_text(uow, me, other, currency) if other else overall_text(uow, me, currency)
            )
            return send_privately(turn, wider)
        return False
    if group_id is not None:
        turn.show(group_balances_text(uow, group_id, currency))
    elif other is not None:
        turn.show(between_text(uow, me, other, currency))
    else:
        turn.show(overall_text(uow, me, currency))
    return False


def _pair_here(turn: Turn, group_id: str, other: str) -> str:
    me, currency = turn.speaker.id, turn.settings.currency
    cents = owed_to(me, pair_debts(group_ledger(turn.uow, group_id))).get(other, 0)
    name = name_for(turn.uow, None, other)
    if cents > 0:
        return f"Here, {name} owes you {money(cents, currency)}."
    if cents < 0:
        return f"Here, you owe {name} {money(-cents, currency)}."
    return f"You and {name} are settled up here."


def send_privately(turn: Turn, text: str) -> bool:
    """Wider answers go to the asker's personal chat, never to the group (10.7)."""
    if turn.direct(turn.speaker.id, text):
        turn.show("I sent you that in a DM.")
        return True
    raise NotAllowedError("Message me 1:1 first, and I'll send you that there.")
