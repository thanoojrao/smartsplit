"""Turning an inbound message into what to do, before any transaction (SPEC 10.1-10.2)."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from smartsplit.domain.commands import AddPerson, AnswerPrompt, Command, StartSplit, Unknown
from smartsplit.domain.enums import ConversationKind
from smartsplit.domain.messages import ChatEvent, InboundMessage
from smartsplit.services.names import MIN_PHONE_DIGITS
from smartsplit.services.speaker import addressed

type Intent = Command | ChatEvent


def is_aside(message: InboundMessage) -> bool:
    """Group chatter not addressed to the bot: read only because a question is open there."""
    return message.conversation_kind is ConversationKind.GROUP and not addressed(message)


def without_model(message: InboundMessage, waiting_for_contact: bool) -> Intent | None:
    """Events, contact cards, photos without a caption, and a number sent for a "need
    contact" question are understood without the model; None means ask the model."""
    if message.event is not None:
        return message.event
    contact = message.contact
    typed = (message.text or "").strip()
    if waiting_for_contact and (contact or looks_like_phone(typed)):
        return AnswerPrompt(text=contact.phone if contact else typed)
    if typed:
        return None
    if contact is not None:
        return AddPerson(contact.name, contact.phone)
    return StartSplit() if message.image else Unknown("")


def fit_command(command: Command, message: InboundMessage) -> Command:
    """Make the command fit what came with it: a photo is always a receipt to split (its
    caption says with whom), a contact card fills in the number, and group chatter only
    counts if it answers a question (SPEC 10.2)."""
    if message.image is not None:
        match command:
            case StartSplit():
                return command
            case AnswerPrompt(people=people, excluding=excluding):
                return StartSplit(people=people, excluding=excluding)
            case _:
                return StartSplit()
    if message.contact is not None and isinstance(command, AddPerson) and command.phone is None:
        return AddPerson(command.name, message.contact.phone)
    if is_aside(message) and not isinstance(command, AnswerPrompt):
        return Unknown(message.text or "")
    return command


def looks_like_phone(text: str) -> bool:
    digits = sum(ch.isdigit() for ch in text)
    return digits >= MIN_PHONE_DIGITS and all(ch.isdigit() or ch in "+-() ." for ch in text)


def local_date(now: datetime, timezone: str) -> date:
    """The install's day: what model-call limits and "this month" count by."""
    return now.astimezone(ZoneInfo(timezone)).date()
