"""Handing what a turn said to the gateway: every message also goes into the transcript of
the chat it is sent to, whatever produced it (SPEC 8.6)."""

from collections.abc import Sequence
from datetime import datetime

from smartsplit.domain.messages import OutboundMessage
from smartsplit.ports.repository import UnitOfWork
from smartsplit.services import transcript
from smartsplit.services.turn import Said


def send(uow: UnitOfWork, said: Sequence[Said], now: datetime, keep: int) -> list[OutboundMessage]:
    """The messages to deliver, each stored (compactly) in its chat's transcript."""
    out: list[OutboundMessage] = []
    for message in said:
        key = message.conversation.key
        stored = message.stored if message.stored is not None else transcript.compact(message.text)
        transcript.append(uow, key, sender_id=None, text=stored, refs=message.refs, now=now)
        uow.chat.prune(key, keep)
        out.append(OutboundMessage(key, message.conversation.person_id, message.text))
    return out
