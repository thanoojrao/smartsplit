"""When the bot reacts in a group chat, and what a quoted reply points at (SPEC 8.6, 10.2).

Personal chats: every message. Group chats: messages addressed to the bot (a mention, or a
reply to one of its messages), photos (read, then kept only if they are receipts or were
addressed), chat events, and, for 10 minutes after the bot posted there, messages from
members it is waiting on. Everything else, an unaddressed contact card included, never
reaches the model.
"""

from datetime import datetime, timedelta

from smartsplit.domain.enums import ConversationKind, PromptKind, PromptStatus
from smartsplit.domain.messages import InboundMessage
from smartsplit.domain.prompts import ChatMessage, EngineQuestionPayload
from smartsplit.domain.values import ConversationKey
from smartsplit.ports.repository import ACTIVE_DRAFT_STATES, UnitOfWork
from smartsplit.services.speaker import current_member_ids

WAITING_WINDOW = timedelta(minutes=10)
QUOTE_MATCH_CHARS = 40
"""How much of a quoted message's start is compared with the bot's messages."""


def addressed(message: InboundMessage) -> bool:
    """Personal messages, and group messages that mention or reply to the bot."""
    return (
        message.conversation_kind is ConversationKind.PERSONAL
        or message.addressed_to_bot
        or message.reply_to_bot
    )


def always_reacts(message: InboundMessage) -> bool:
    """Reacted to whoever sent them: addressed messages, photos, events."""
    return addressed(message) or message.image is not None or message.event is not None


def waiting_on(
    uow: UnitOfWork,
    key: ConversationKey,
    group_id: str,
    person_id: str,
    *,
    now: datetime,
    keep: int,
) -> bool:
    """The bot posted here in the last 10 minutes and waits on this member: the adder of an
    active draft here, someone an open question is about (the adder for "who is it for?"),
    whoever a pending action waits for, or the person it last replied to (SPEC 10.2)."""
    if person_id not in current_member_ids(uow, group_id):
        return False
    recent = uow.chat.recent(key, keep)
    bot_lines = [m for m in recent if m.sender_id is None]
    if not bot_lines or now - bot_lines[-1].created_at > WAITING_WINDOW:
        return False
    return person_id in _waited_on(uow, key, recent)


def _waited_on(uow: UnitOfWork, key: ConversationKey, recent: tuple[ChatMessage, ...]) -> set[str]:
    drafts = {d.id: d for d in uow.drafts.for_conversation(key, ACTIVE_DRAFT_STATES)}
    people = {d.added_by for d in drafts.values()}
    for prompt in uow.prompts.for_conversation(key, [PromptStatus.OPEN]):
        payload = prompt.payload
        if prompt.kind is PromptKind.PENDING_ACTION and prompt.asked_of:
            people.add(prompt.asked_of)
        elif isinstance(payload, EngineQuestionPayload):
            draft = drafts.get(prompt.draft_id or "")
            if payload.member_id is not None:
                people.add(payload.member_id)
            elif draft is not None:
                people.add(draft.added_by)
    last_reply = _last_replied_to(recent)
    if last_reply is not None:
        people.add(last_reply)
    return people


def _last_replied_to(recent: tuple[ChatMessage, ...]) -> str | None:
    """The sender of the last message the bot answered."""
    for earlier, later in zip(reversed(recent[:-1]), reversed(recent[1:]), strict=True):
        if later.sender_id is None and earlier.sender_id is not None:
            return earlier.sender_id
    return None


def quoted_message(
    uow: UnitOfWork, key: ConversationKey, quoted_text: str | None, keep: int
) -> ChatMessage | None:
    """The bot message a reply quotes, matched by its start (SPEC 10.1)."""
    if not quoted_text or not quoted_text.strip():
        return None
    wanted = _start(quoted_text)
    for message in reversed(uow.chat.recent(key, keep)):
        if message.sender_id is None and _start(message.text).startswith(
            wanted[:QUOTE_MATCH_CHARS]
        ):
            return message
    return None


def _start(text: str) -> str:
    return " ".join(text.split())
