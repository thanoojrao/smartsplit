"""The chat transcript: what was said, with what each bot message showed (SPEC 8.6).

Every message the bot sends is stored in the chat it goes to, whatever produced it. Shown
blocks are stored compactly (their first lines plus their references), each chat keeps at
most `chat_history_keep` messages, and `tick` deletes messages older than the age limit.
"""

from collections.abc import Sequence
from datetime import datetime

from smartsplit.domain.prompts import ChatMessage, ChatRef
from smartsplit.domain.values import ConversationKey
from smartsplit.ports.repository import UnitOfWork

COMPACT_LINES = 3
"""A long block (a 45-line details list) is stored as its first lines and its references."""


def compact(text: str) -> str:
    lines = text.splitlines()
    if len(lines) <= COMPACT_LINES:
        return text
    return "\n".join([*lines[:COMPACT_LINES], f"… ({len(lines) - COMPACT_LINES} more lines)"])


def append(
    uow: UnitOfWork,
    key: ConversationKey,
    *,
    sender_id: str | None,
    text: str,
    refs: Sequence[ChatRef],
    now: datetime,
) -> None:
    uow.chat.append(ChatMessage(key, 0, sender_id, compact(text), tuple(refs), now))


def last_shown_version(
    uow: UnitOfWork, key: ConversationKey, draft_id: str, keep: int
) -> int | None:
    """The draft version in the bot's latest message about it in this chat (SPEC 8.4)."""
    for message in reversed(uow.chat.recent(key, keep)):
        if message.sender_id is not None:
            continue
        for ref in message.refs:
            if ref.kind == "draft" and ref.id == draft_id:
                return ref.version
    return None
