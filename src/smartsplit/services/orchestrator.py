"""One message, end to end (SPEC 8.1, 10.2, 12.2; CONTRACTS section 5).

Read-only checks come first: a repeat, whether the bot reacts, and the daily limits. Then the
photo is read outside the lock and stored on its own. Then the whole turn runs in one locked
transaction: the agent loop, the replies, the transcript and the processed-message record.
If a model call fails or the deadline passes, everything the turn did rolls back and the
person is asked to try again; the photo read and the usage counts survive. A chat that stays
busy longer than the lock wait is answered "busy" (HTTP 503), and the gateway retries.
"""

import hashlib
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from typing import Literal

from smartsplit.domain.enums import ConversationKind, PhotoOutcome
from smartsplit.domain.messages import ImageAttachment, InboundMessage, OutboundMessage
from smartsplit.domain.model import PhotoRead
from smartsplit.domain.prompts import ProcessedMessage, TickBatch
from smartsplit.ports.agent import AgentModel, ModelUsage
from smartsplit.ports.errors import ChatBusyError, StaleDraftError
from smartsplit.ports.images import ImageStore
from smartsplit.ports.llm import Canonicalizer, LlmUnavailableError, ReceiptParser
from smartsplit.ports.repository import Repository, UnitOfWork
from smartsplit.ports.system import Clock, IdGenerator
from smartsplit.services.agent_loop import LoopResult, run_loop
from smartsplit.services.gating import addressed, always_reacts, quoted_message, waiting_on
from smartsplit.services.limits import Allowance, allowance, first_notice_today
from smartsplit.services.membership import member_left
from smartsplit.services.photos import PhotoReader
from smartsplit.services.replies import opening, record
from smartsplit.services.reply_text import clean_reply
from smartsplit.services.speaker import arrive, current_member_ids, find_speaker, mentioned
from smartsplit.services.text import NEEDS_NUMBER, OVER_LIMIT, TRY_AGAIN
from smartsplit.services.ticking import Ticker
from smartsplit.services.turn import OrchestratorSettings, Turn, local_date
from smartsplit.services.turn_input import build_turn_input
from smartsplit.services.usage import Meter, MeteredCanonicalizer

UNACKED_AFTER = timedelta(minutes=2)
"""A tick batch not acknowledged this long is returned again (SPEC 10.8)."""
BATCHES_KEPT = timedelta(days=1)
"""How long delivered tick batches are kept (an ack may come late)."""

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


@dataclass(frozen=True, slots=True)
class _Checked:
    """What the read-only checks found, before any lock."""

    speaker_id: str | None
    member: bool
    waited_on: bool
    limits: Allowance


@dataclass(frozen=True, slots=True)
class _Incoming:
    """One message as the locked turn needs it, with what was settled before the lock."""

    message: InboundMessage
    now: datetime
    deadline: datetime
    meter: Meter
    photo: PhotoRead | None
    over_limit: bool


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

    def tick(self) -> TickBatch:
        """Deliver the outbox, nudge or expire idle drafts, prune old chat; call it every
        minute. A batch the gateway hasn't acknowledged comes back with the same id, so a
        lost response loses nothing (SPEC 10.8)."""
        now = self._clock.now()
        with self._repository.unit_of_work() as uow:
            unacked = uow.tick_batches.unacked_before(now - UNACKED_AFTER)
        if unacked:
            return unacked[0]
        messages = tuple(self._ticker.tick())
        batch = TickBatch(self._ids.new_id(), messages, now, None if messages else now)
        with self._repository.unit_of_work() as uow:
            uow.tick_batches.add(batch)
            uow.tick_batches.delete_acked_before(now - BATCHES_KEPT)
        return batch

    def ack(self, batch_id: str) -> bool:
        """The gateway sent the batch; False if there is no such batch."""
        with self._repository.unit_of_work() as uow:
            return uow.tick_batches.ack(batch_id, self._clock.now())

    def handle(self, message: InboundMessage) -> HandleOutcome:
        """Replies for this message (and any chat it affects); a repeat returns the same."""
        message = _cleaned(message)
        now = self._clock.now()
        chat = _chat_hash(message)
        day = local_date(now, self._settings.timezone)
        checked = self._screen(message, now, day, chat)
        if isinstance(checked, HandleOutcome):
            return checked
        deadline = now + timedelta(seconds=self._settings.message_seconds)
        meter = Meter(self._repository, day, checked.speaker_id if addressed(message) else None)
        photo = None
        if checked.speaker_id is not None and self._may_read(message.image, checked):
            try:
                photo = self._read(message, checked.speaker_id, now, meter, deadline)
            except LlmUnavailableError:
                return _try_again(message, checked.speaker_id, TurnReport(chat, "failed"))
        if _ignored_photo(message, photo):
            return HandleOutcome((), TurnReport(chat, "silent"))
        over = checked.limits.over
        try:
            replies, result = self._turn(_Incoming(message, now, deadline, meter, photo, over))
        except ChatBusyError:
            return HandleOutcome((), TurnReport(chat, "busy"), busy=True)
        except (LlmUnavailableError, StaleDraftError):
            outcome: Outcome = "deadline" if self._clock.now() >= deadline else "failed"
            return _try_again(message, checked.speaker_id, TurnReport(chat, outcome))
        report = TurnReport(
            chat,
            "limit" if over else "replied" if replies else "silent",
            result.steps,
            tuple(result.tools),
            result.usage,
            (self._clock.now() - now).total_seconds(),
            checked.limits.install_nearly_spent,
        )
        return HandleOutcome(replies, report)

    def _screen(
        self, message: InboundMessage, now: datetime, day: date, chat: str
    ) -> HandleOutcome | _Checked:
        """The read-only checks: a repeat, whether the bot reacts, the daily limits."""
        with self._repository.unit_of_work() as uow:
            done = uow.processed.get(message.conversation, message.message_id)
            if done is not None:
                return HandleOutcome(done.replies, TurnReport(chat, "repeat"))
            checked = self._check(uow, message, now, day)
        if not (always_reacts(message) or checked.waited_on):
            return HandleOutcome((), TurnReport(chat, "silent"))
        if checked.limits.over and not self._notice_due(message, checked.speaker_id, day):
            return HandleOutcome((), TurnReport(chat, "limit", install_nearly_spent=True))
        return checked

    def _check(
        self, uow: UnitOfWork, message: InboundMessage, now: datetime, day: date
    ) -> _Checked:
        speaker = find_speaker(uow, message)
        speaker_id = speaker.id if speaker else None
        conversation = uow.conversations.get(message.conversation)
        group_id = conversation.group_id if conversation else None
        member = group_id is None or speaker_id in current_member_ids(uow, group_id)
        waited = (
            speaker_id is not None
            and group_id is not None
            and waiting_on(uow, message.conversation, group_id, speaker_id, now)
        )
        return _Checked(speaker_id, member, waited, allowance(uow, speaker_id, day, self._settings))

    def _notice_due(self, message: InboundMessage, speaker_id: str | None, day: date) -> bool:
        """Over a limit, the bot says so once a day, to someone who addressed it (SPEC 12.5)."""
        return (
            addressed(message)
            and speaker_id is not None
            and first_notice_today(self._repository, speaker_id, day)
        )

    def _may_read(self, image: ImageAttachment | None, checked: _Checked) -> bool:
        """The cheap checks before a photo is read: a member (or a personal chat), under the
        daily limits, and not too big (SPEC 7)."""
        return (
            image is not None
            and checked.member
            and not checked.limits.over
            and len(image.data) <= self._settings.max_image_bytes
        )

    def _read(
        self,
        message: InboundMessage,
        speaker_id: str,
        now: datetime,
        meter: Meter,
        deadline: datetime,
    ) -> PhotoRead | None:
        if message.image is None:
            return None
        return self._photos.read(
            message.conversation,
            message.message_id,
            speaker_id,
            message.image,
            now=now,
            meter=meter,
            timeout_seconds=self._time_left(deadline, self._settings.llm_timeout_seconds),
        )

    def _time_left(self, deadline: datetime, at_most: float) -> float:
        left = (deadline - self._clock.now()).total_seconds()
        return max(0.0, min(at_most, left))

    def _turn(self, incoming: _Incoming) -> tuple[tuple[OutboundMessage, ...], LoopResult]:
        """The locked transaction: arrival, the loop, the transcript, the record."""
        settings, message, now = self._settings, incoming.message, incoming.now
        wait = self._time_left(incoming.deadline, settings.lock_wait_seconds)
        with self._repository.unit_of_work(
            lock=message.conversation, lock_wait_seconds=wait
        ) as uow:
            done = uow.processed.get(message.conversation, message.message_id)
            if done is not None:
                return done.replies, LoopResult()
            arrival = arrive(uow, self._ids, message, settings.default_region, now)
            result = LoopResult()
            if arrival is None:
                text = NEEDS_NUMBER.format(link=settings.bot_link)
                replies: tuple[OutboundMessage, ...] = (
                    OutboundMessage(message.conversation, None, text),
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
                result = self._respond(turn, incoming, welcomed=welcomed)
                new_group = arrival.new_group or _bot_added(message)
                first = opening(turn, welcomed=welcomed, new_group=new_group)
                replies = record(turn, message, clean_reply(result.text, turn.handles), first)
            uow.processed.add(
                ProcessedMessage(message.conversation, message.message_id, replies, now)
            )
            return replies, result

    def _respond(self, turn: Turn, incoming: _Incoming, *, welcomed: bool) -> LoopResult:
        """The model's words and what it did; events and the daily limit need no model."""
        message = incoming.message
        event = message.event
        if event is not None:
            if event.kind == "participant_left" and event.subject_ref and turn.in_group:
                identity = turn.uow.identities.get(turn.conversation.key.channel, event.subject_ref)
                if identity is not None:
                    member_left(turn, identity.person_id)
            return LoopResult()
        if incoming.over_limit:
            return LoopResult(OVER_LIMIT)
        settings = turn.settings
        people = mentioned(
            turn.uow,
            self._ids,
            message,
            region=settings.default_region,
            now=turn.now,
            by=turn.speaker.id,
        )
        quoted = quoted_message(
            turn.uow, turn.conversation.key, message.quoted_text, settings.chat_history_keep
        )
        turn_input = build_turn_input(
            turn, message, incoming.photo, welcomed=welcomed, mentions=people, quoted=quoted
        )
        return run_loop(
            turn,
            self._agent,
            turn_input,
            clock=self._clock,
            deadline=incoming.deadline,
            count_call=incoming.meter.count,
        )


def _ignored_photo(message: InboundMessage, photo: PhotoRead | None) -> bool:
    """In a group, a photo nobody addressed to the bot goes on only if it is a receipt
    (SPEC 10.2); one that wasn't read at all goes nowhere."""
    if message.image is None or message.conversation_kind is not ConversationKind.GROUP:
        return False
    if addressed(message):
        return False
    return photo is None or photo.outcome is not PhotoOutcome.RECEIPT


def _bot_added(message: InboundMessage) -> bool:
    return message.event is not None and message.event.kind == "bot_added"


def _chat_hash(message: InboundMessage) -> str:
    key = message.conversation
    return hashlib.blake2b(f"{key.channel}:{key.ref}".encode(), digest_size=6).hexdigest()


def _try_again(
    message: InboundMessage, speaker_id: str | None, report: TurnReport
) -> HandleOutcome:
    """Nothing was recorded, so a later retry of this message runs it again (SPEC 12.2)."""
    personal = message.conversation_kind is ConversationKind.PERSONAL
    recipient = speaker_id if personal else None
    return HandleOutcome((OutboundMessage(message.conversation, recipient, TRY_AGAIN),), report)


def _cleaned(message: InboundMessage) -> InboundMessage:
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
