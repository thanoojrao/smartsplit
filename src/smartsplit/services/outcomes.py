"""What handling one message returns, and the small helpers around it (SPEC 12.2, 12.4)."""

import hashlib
from dataclasses import dataclass, field, replace
from typing import Literal

from smartsplit.domain.enums import ConversationKind
from smartsplit.domain.messages import InboundMessage, OutboundMessage
from smartsplit.ports.agent import ModelUsage
from smartsplit.services.text import TRY_AGAIN

type Outcome = Literal["replied", "silent", "failed", "deadline", "busy", "limit", "repeat"]


@dataclass(frozen=True, slots=True)
class TurnReport:
    """What the per-turn log line says, with no content in it (SPEC 12.4)."""

    chat: str
    """A hash of the chat, never its id."""
    outcome: Outcome
    steps: int = 0
    tools: tuple[tuple[str, bool], ...] = ()
    usage: ModelUsage = field(default_factory=ModelUsage)
    seconds: float = 0.0
    install_nearly_spent: bool = False
    """The install used 80% of its daily model calls: worth a warning."""


@dataclass(frozen=True, slots=True)
class HandleOutcome:
    replies: tuple[OutboundMessage, ...]
    report: TurnReport
    busy: bool = False
    """The chat stayed busy too long: the gateway retries (HTTP 503)."""


def chat_hash(message: InboundMessage) -> str:
    key = message.conversation
    return hashlib.blake2b(f"{key.channel}:{key.ref}".encode(), digest_size=6).hexdigest()


def try_again(message: InboundMessage, speaker_id: str | None, report: TurnReport) -> HandleOutcome:
    """Nothing was recorded, so a later retry of this message runs it again (SPEC 12.2)."""
    personal = message.conversation_kind is ConversationKind.PERSONAL
    recipient = speaker_id if personal else None
    return HandleOutcome((OutboundMessage(message.conversation, recipient, TRY_AGAIN),), report)


def cleaned(message: InboundMessage) -> InboundMessage:
    """Postgres can't store NUL, and no chat text needs it."""

    def strip(text: str | None) -> str | None:
        return text.replace("\x00", "") if text is not None else None

    contact = message.contact
    return replace(
        message,
        text=strip(message.text),
        quoted_text=strip(message.quoted_text),
        sender_name=strip(message.sender_name) or "",
        conversation_name=strip(message.conversation_name),
        mentions=tuple(
            replace(m, name=strip(m.name) or "", phone=strip(m.phone)) for m in message.mentions
        ),
        contact=replace(contact, name=strip(contact.name) or "", phone=strip(contact.phone) or "")
        if contact
        else None,
    )
