"""Inbound and outbound chat messages (CONTRACTS section 1.6)."""

from dataclasses import dataclass
from typing import Literal

from smartsplit.domain.enums import ConversationKind
from smartsplit.domain.values import ConversationKey


@dataclass(frozen=True, slots=True)
class ImageAttachment:
    mime_type: str
    data: bytes


@dataclass(frozen=True, slots=True)
class ContactAttachment:
    """A shared contact card: the way to add someone the bot doesn't know."""

    name: str
    phone: str


@dataclass(frozen=True, slots=True)
class ChatEvent:
    kind: Literal["participant_left"]
    subject_ref: str


@dataclass(frozen=True, slots=True)
class InboundMessage:
    """One message from a chat channel; `message_id` makes handling idempotent."""

    message_id: str
    conversation: ConversationKey
    conversation_kind: ConversationKind
    conversation_name: str | None
    sender_ref: str
    sender_alt_ref: str | None
    """A second identity for the same sender, e.g. a WhatsApp number and a hidden id."""
    sender_phone: str | None
    sender_name: str
    addressed_to_bot: bool
    reply_to_bot: bool
    text: str | None = None
    image: ImageAttachment | None = None
    contact: ContactAttachment | None = None
    event: ChatEvent | None = None


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    """Plain chat text; `recipient_id` is set for personal-chat messages."""

    conversation: ConversationKey
    recipient_id: str | None
    text: str
