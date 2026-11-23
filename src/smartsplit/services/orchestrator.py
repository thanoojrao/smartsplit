"""One message, end to end (SPEC 8.1, CONTRACTS section 5).

Read-only checks first (a repeat, whether the bot reacts, the daily limit), then the photo is
read outside the lock and stored on its own, then the whole turn runs in one locked
transaction: the agent loop, the replies, the transcript, and the processed-message record.
If a model call fails or the deadline passes, everything the turn did rolls back and the
person is asked to try again; the photo read and the usage counts survive.
"""

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

from smartsplit.domain.enums import ConversationKind
from smartsplit.domain.messages import InboundMessage, OutboundMessage
from smartsplit.domain.model import PhotoRead
from smartsplit.domain.prompts import ProcessedMessage
from smartsplit.ports.agent import AgentModel
from smartsplit.ports.errors import StaleDraftError
from smartsplit.ports.images import ImageStore
from smartsplit.ports.llm import Canonicalizer, LlmUnavailableError, ReceiptParser
from smartsplit.ports.repository import Repository, UnitOfWork
from smartsplit.ports.system import Clock, IdGenerator
from smartsplit.services import transcript
from smartsplit.services.agent_loop import run_loop
from smartsplit.services.membership import member_left
from smartsplit.services.photos import PhotoReader
from smartsplit.services.reply_text import clean_reply
from smartsplit.services.sending import send
from smartsplit.services.speaker import arrive, find_speaker
from smartsplit.services.text import NEEDS_NUMBER, OVER_LIMIT, TRY_AGAIN, WELCOME
from smartsplit.services.ticking import Ticker
from smartsplit.services.turn import OrchestratorSettings, Said, Turn, local_date
from smartsplit.services.turn_input import build_turn_input
from smartsplit.services.usage import Meter, MeteredCanonicalizer


@dataclass(frozen=True, slots=True)
class _Incoming:
    """One message as the locked turn needs it, with what was settled before the lock."""

    message: InboundMessage
    now: datetime
    deadline: datetime
    meter: Meter
    photo: PhotoRead | None
    over_limit: bool


@dataclass(frozen=True, slots=True)
class HandleOutcome:
    replies: tuple[OutboundMessage, ...]
    busy: bool = False
    """The chat stayed busy too long: the gateway retries (HTTP 503)."""


class Orchestrator:
    """Channel-agnostic: messages in, messages out, for any chat (CONTRACTS section 5)."""

    def __init__(
        self,
        *,
        repository: Repository,
        images: ImageStore,
        parser: ReceiptParser,
        canonicalizer: Canonicalizer,
        agent: AgentModel,
        clock: Clock,
        ids: IdGenerator,
        settings: OrchestratorSettings,
    ) -> None:
        self._repository = repository
        self._canonicalizer = canonicalizer
        self._agent = agent
        self._clock = clock
        self._ids = ids
        self._settings = settings
        self._photos = PhotoReader(repository, images, parser, ids, settings.currency)
        self._ticker = Ticker(repository, clock, ids, settings)

    def tick(self) -> list[OutboundMessage]:
        """Deliver the outbox, nudge or expire idle drafts, prune old chat; call it every
        minute (SPEC 10.8)."""
        return self._ticker.tick()

    def handle(self, message: InboundMessage) -> HandleOutcome:
        """Replies for this message (and any chat it affects); a repeat returns the same."""
        message = _cleaned(message)
        now = self._clock.now()
        deadline = now + timedelta(seconds=self._settings.message_seconds)
        with self._repository.unit_of_work() as uow:
            done = uow.processed.get(message.conversation, message.message_id)
            if done is not None:
                return HandleOutcome(done.replies)
            speaker = find_speaker(uow, message)
            over_limit = speaker is not None and self._over_limit(uow, speaker.id, now)
        if not _reacts(message):
            return HandleOutcome(())
        charged = speaker.id if speaker and _addressed(message) else None
        meter = Meter(self._repository, self._day(now), charged)
        photo = None
        if message.image is not None and speaker is not None and not over_limit:
            try:
                photo = self._photos.read(
                    message.conversation,
                    message.message_id,
                    speaker.id,
                    message.image,
                    now=now,
                    meter=meter,
                    timeout_seconds=self._call_timeout(deadline),
                )
            except LlmUnavailableError:
                return _try_again(message, speaker.id)
        try:
            incoming = _Incoming(message, now, deadline, meter, photo, over_limit)
            return HandleOutcome(self._turn(incoming))
        except (LlmUnavailableError, StaleDraftError):
            return _try_again(message, speaker.id if speaker else None)

    def _turn(self, incoming: _Incoming) -> tuple[OutboundMessage, ...]:
        """The locked transaction: arrival, the loop, the transcript, the record."""
        settings, message, now = self._settings, incoming.message, incoming.now
        with self._repository.unit_of_work(lock=message.conversation) as uow:
            done = uow.processed.get(message.conversation, message.message_id)
            if done is not None:
                return done.replies
            arrival = arrive(uow, self._ids, message, settings.default_region, now)
            if arrival is None:
                replies: tuple[OutboundMessage, ...] = (
                    OutboundMessage(message.conversation, None, NEEDS_NUMBER),
                )
            else:
                turn = Turn(
                    uow,
                    self._ids,
                    now,
                    settings,
                    arrival.speaker,
                    arrival.conversation,
                    message_id=message.message_id,
                    contact=message.contact,
                    canonicalizer=MeteredCanonicalizer(self._canonicalizer, incoming.meter),
                )
                welcomed = arrival.first_personal_message
                text = self._respond(turn, incoming, welcomed=welcomed)
                opening = _opening(turn, welcomed=welcomed, new_group=arrival.new_group)
                replies = self._record(turn, message, text, opening)
            uow.processed.add(
                ProcessedMessage(message.conversation, message.message_id, replies, now)
            )
            return replies

    def _respond(self, turn: Turn, incoming: _Incoming, *, welcomed: bool) -> str:
        """The model's cleaned words; events and the daily limit need no model."""
        event = incoming.message.event
        if event is not None:
            identity = turn.uow.identities.get(turn.conversation.key.channel, event.subject_ref)
            if event.kind == "participant_left" and identity is not None and turn.in_group:
                member_left(turn, identity.person_id)
            return ""
        if incoming.over_limit:
            return OVER_LIMIT
        turn_input = build_turn_input(turn, incoming.message, incoming.photo, welcomed)
        result = run_loop(
            turn,
            self._agent,
            turn_input,
            clock=self._clock,
            deadline=incoming.deadline,
            count_call=incoming.meter.count,
        )
        return clean_reply(result.text, turn.handles)

    def _record(
        self, turn: Turn, message: InboundMessage, text: str, opening: list[Said]
    ) -> tuple[OutboundMessage, ...]:
        """The replies, with the inbound message and every outbound one in the transcripts.

        In a group chat, a message the bot neither answered nor acted on isn't stored."""
        said = list(opening)
        blocks = [s.text for s in turn.shown]
        main = "\n\n".join(part for part in (text, *blocks) if part)
        if main:
            refs = tuple(ref for s in turn.shown for ref in s.refs)
            kept = "\n\n".join(p for p in (text, *map(transcript.compact, blocks)) if p)
            said.append(Said(turn.conversation, main, refs, kept))
        said += turn.elsewhere
        personal = turn.conversation.kind is ConversationKind.PERSONAL
        if personal or said or turn.acted:
            transcript.append(
                turn.uow,
                turn.conversation.key,
                sender_id=turn.speaker.id,
                text=_inbound_text(message),
                refs=(),
                now=turn.now,
            )
            turn.uow.chat.prune(turn.conversation.key, self._settings.chat_history_keep)
        return tuple(send(turn.uow, said, turn.now, self._settings.chat_history_keep))

    def _over_limit(self, uow: UnitOfWork, person_id: str, now: datetime) -> bool:
        usage = uow.llm_usage.get(person_id, self._day(now))
        return usage is not None and usage.calls >= self._settings.llm_calls_per_person_per_day

    def _day(self, now: datetime) -> date:
        return local_date(now, self._settings.timezone)

    def _call_timeout(self, deadline: datetime) -> float:
        left = (deadline - self._clock.now()).total_seconds()
        return max(0.0, min(self._settings.llm_timeout_seconds, left))


def _opening(turn: Turn, *, welcomed: bool, new_group: bool) -> list[Said]:
    """Fixed first words: the welcome on someone's first personal message (SPEC 10.3), and a
    new group chat's intro (the first person is in, everyone else joins explicitly)."""
    opening: list[Said] = []
    if welcomed:
        opening.append(Said(turn.conversation, WELCOME.format(name=turn.speaker.display_name)))
    if new_group:
        intro = (
            f"Hi {turn.conversation.name}! {turn.speaker.display_name} is in. Everyone else "
            'who wants to split bills here, say "join".'
        )
        opening.append(Said(turn.conversation, intro))
    return opening


def _addressed(message: InboundMessage) -> bool:
    """Personal messages, and group messages that mention or reply to the bot: only these
    count against the speaker's own daily limit (SPEC 12.5)."""
    return (
        message.conversation_kind is ConversationKind.PERSONAL
        or message.addressed_to_bot
        or message.reply_to_bot
    )


def _reacts(message: InboundMessage) -> bool:
    """Personal chats: every message. Groups: messages addressed to the bot (a mention or a
    reply to it), photos, contact cards and chat events (SPEC 10.2)."""
    return (
        message.conversation_kind is ConversationKind.PERSONAL
        or message.addressed_to_bot
        or message.reply_to_bot
        or message.image is not None
        or message.contact is not None
        or message.event is not None
    )


def _try_again(message: InboundMessage, speaker_id: str | None) -> HandleOutcome:
    """Nothing was recorded, so a later retry of this message runs it again (SPEC 12.2)."""
    personal = message.conversation_kind is ConversationKind.PERSONAL
    return HandleOutcome(
        (OutboundMessage(message.conversation, speaker_id if personal else None, TRY_AGAIN),)
    )


def _inbound_text(message: InboundMessage) -> str:
    parts = [message.text or ""]
    if message.image is not None:
        parts.append("[photo]")
    if message.contact is not None:
        parts.append(f"[contact card: {message.contact.name}]")
    return " ".join(p for p in parts if p)


def _cleaned(message: InboundMessage) -> InboundMessage:
    """Postgres can't store NUL, and no chat text needs it."""

    def strip(text: str | None) -> str | None:
        return text.replace("\x00", "") if text is not None else None

    contact = message.contact
    return replace(
        message,
        text=strip(message.text),
        sender_name=strip(message.sender_name) or "",
        conversation_name=strip(message.conversation_name),
        contact=replace(contact, name=strip(contact.name) or "", phone=strip(contact.phone) or "")
        if contact
        else None,
    )
