"""Assembling one turn's replies and writing them, with the inbound message, to the
transcripts (SPEC 8.1, 8.5, 8.6)."""

from smartsplit.domain.enums import ConversationKind
from smartsplit.domain.messages import InboundMessage, OutboundMessage
from smartsplit.services import transcript
from smartsplit.services.sending import send
from smartsplit.services.text import WELCOME
from smartsplit.services.turn import Said, Turn


def opening(turn: Turn, *, welcomed: bool, new_group: bool) -> list[Said]:
    """Fixed first words: the welcome on someone's first personal message, and a new group
    chat's intro, which people join by replying to (SPEC 10.3)."""
    said: list[Said] = []
    if welcomed:
        said.append(Said(turn.conversation, WELCOME.format(name=turn.speaker.display_name)))
    if new_group:
        said.append(Said(turn.conversation, intro(turn)))
    return said


def intro(turn: Turn) -> str:
    return (
        f"Hi {turn.conversation.name}! I split bills: send a receipt photo or tell me what you "
        f"paid. {turn.speaker.display_name} is in. Everyone else: reply to this message with "
        '"join" to split bills here.'
    )


def record(
    turn: Turn, message: InboundMessage, text: str, first: list[Said]
) -> tuple[OutboundMessage, ...]:
    """The replies: the fixed first words, then the model's words with the shown blocks, then
    messages to other chats. In a group chat, a message the bot neither answered nor acted
    on isn't stored (SPEC 10.2)."""
    keep = turn.settings.chat_history_keep
    said = list(first)
    shown = latest_per_draft(turn.shown)
    blocks = [s.text for s in shown]
    main = "\n\n".join(part for part in (text, *blocks) if part)
    if main:
        refs = tuple(ref for s in shown for ref in s.refs)
        kept = "\n\n".join(p for p in (text, *map(transcript.compact, blocks)) if p)
        said.append(Said(turn.conversation, main, refs, kept))
    said += turn.elsewhere
    personal = turn.conversation.kind is ConversationKind.PERSONAL
    if personal or said or turn.acted:
        transcript.append(
            turn.uow,
            turn.conversation.key,
            sender_id=turn.speaker.id,
            text=inbound_text(message),
            refs=(),
            now=turn.now,
        )
        turn.uow.chat.prune(turn.conversation.key, keep)
    return tuple(send(turn.uow, said, turn.now, keep))


def latest_per_draft(shown: list[Said]) -> list[Said]:
    """A draft changed twice in one turn is shown once, as it ended up: an earlier summary of
    it would only show a state that no longer exists."""
    later: set[str] = set()
    kept: list[Said] = []
    for block in reversed(shown):
        drafts = {ref.id for ref in block.refs if ref.kind == "draft"}
        if drafts and drafts <= later:
            continue
        later |= drafts
        kept.append(block)
    return kept[::-1]


def inbound_text(message: InboundMessage) -> str:
    """What the person sent, mentions as names, as the transcript keeps it."""
    parts = [with_names(message)]
    if message.image is not None:
        parts.append("[photo]")
    if message.contact is not None:
        parts.append(f"[contact card: {message.contact.name}]")
    return " ".join(p for p in parts if p)


def with_names(message: InboundMessage) -> str:
    """The text with each "@<ref>" mention shown as "@Name" (SPEC 10.1)."""
    text = message.text or ""
    for mention in message.mentions:
        text = text.replace(f"@{mention.ref}", f"@{mention.name}")
    return text
