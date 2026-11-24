"""One message, end to end (SPEC 8.1, 10.2, 12.2; CONTRACTS section 5).

Read-only checks come first: a repeat, whether the bot reacts, and the daily limits. Then the
photo is read outside the lock and stored on its own. Then the whole turn runs in one locked
transaction: the agent loop, the replies, the transcript and the processed-message record.
If a model call fails, the deadline passes or the database fails the transaction (a deadlock,
a clash with the same person's message in another chat), everything the turn did rolls back
and the person is asked to try again; the photo read and the usage counts survive. A chat that stays
busy longer than the lock wait is answered "busy" (HTTP 503), and the gateway retries.
"""

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

from smartsplit.domain.enums import ConversationKind, PhotoOutcome
from smartsplit.domain.messages import ImageAttachment, InboundMessage, OutboundMessage
from smartsplit.domain.model import PhotoRead
from smartsplit.domain.prompts import ProcessedMessage, TickBatch
from smartsplit.ports.agent import AgentModel
from smartsplit.ports.errors import (
    ChatBusyError,
    ConstraintViolationError,
    StaleDraftError,
    StorageUnavailableError,
)
from smartsplit.ports.images import ImageStore
from smartsplit.ports.llm import Canonicalizer, LlmUnavailableError, ReceiptParser
from smartsplit.ports.repository import Repository, UnitOfWork
from smartsplit.ports.system import Clock, IdGenerator
from smartsplit.services.agent_loop import LoopResult, run_loop
from smartsplit.services.gating import addressed, always_reacts, quoted_message, waiting_on
from smartsplit.services.limits import Allowance, allowance, first_notice_today
from smartsplit.services.membership import chat_event
from smartsplit.services.outcomes import (
    HandleOutcome,
    Outcome,
    TurnReport,
    chat_hash,
    cleaned,
    try_again,
)
from smartsplit.services.photos import PhotoReader
from smartsplit.services.replies import opening, record
from smartsplit.services.reply_text import clean_reply
from smartsplit.services.speaker import arrive, current_member_ids, find_speaker, mentioned
from smartsplit.services.text import NEEDS_NUMBER, OVER_LIMIT
from smartsplit.services.ticking import Ticker
from smartsplit.services.transcript import append
from smartsplit.services.turn import OrchestratorSettings, Turn, local_date
from smartsplit.services.turn_input import build_turn_input
from smartsplit.services.usage import Meter, MeteredCanonicalizer

UNACKED_AFTER = timedelta(minutes=2)
"""A tick batch not acknowledged this long is returned again (SPEC 10.8)."""
BATCHES_KEPT = timedelta(days=1)
"""How long delivered tick batches are kept (an ack may come late)."""


@dataclass(frozen=True, slots=True)
class _Checked:
    """What the read-only checks found, before any lock."""

    speaker_id: str | None
    member: bool
    waited_on: bool
    new_group: bool
    """A group chat the bot doesn't know yet."""
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
        batch_id = self._ids.new_id()
        with self._repository.unit_of_work() as uow:
            uow.tick_batches.add(TickBatch(batch_id, (), now, None))
        self._ticker.tick(batch_id)
        with self._repository.unit_of_work() as uow:
            batch = uow.tick_batches.get(batch_id)
            if batch is None:
                raise KeyError(batch_id)
            if not batch.messages:
                uow.tick_batches.ack(batch_id, now)
                batch = replace(batch, acked_at=now)
            uow.tick_batches.delete_acked_before(now - BATCHES_KEPT)
        return batch

    def ack(self, batch_id: str) -> bool:
        """The gateway sent the batch; False if there is no such batch."""
        with self._repository.unit_of_work() as uow:
            return uow.tick_batches.ack(batch_id, self._clock.now())

    def handle(self, message: InboundMessage) -> HandleOutcome:
        """Replies for this message (and any chat it affects); a repeat returns the same."""
        message = cleaned(message)
        now = self._clock.now()
        chat = chat_hash(message)
        day = local_date(now, self._settings.timezone)
        checked = self._screen(message, now, day, chat)
        if isinstance(checked, HandleOutcome):
            return checked
        deadline = now + timedelta(seconds=self._settings.message_seconds)
        meter = Meter(self._repository, day, checked.speaker_id if addressed(message) else None)
        photo = self._photo(message, checked, now, meter, deadline)
        if isinstance(photo, HandleOutcome):
            return photo
        over = checked.limits.over and message.event is None
        try:
            replies, result = self._turn(_Incoming(message, now, deadline, meter, photo, over))
        except ChatBusyError:
            return HandleOutcome((), TurnReport(chat, "busy", seconds=self._since(now)), busy=True)
        except (
            LlmUnavailableError,
            StaleDraftError,
            ConstraintViolationError,
            StorageUnavailableError,
        ):
            # rolled back; nothing recorded, so a retry of this message runs it again
            outcome: Outcome = "deadline" if self._clock.now() >= deadline else "failed"
            report = TurnReport(chat, outcome, seconds=self._since(now))
            return try_again(message, checked.speaker_id, report)
        report = TurnReport(
            chat,
            "limit" if over else "replied" if replies else "silent",
            result.steps,
            tuple(result.tools),
            result.usage,
            self._since(now),
            checked.limits.install_nearly_spent,
        )
        return HandleOutcome(replies, report)

    def _since(self, start: datetime) -> float:
        return (self._clock.now() - start).total_seconds()

    def _photo(
        self,
        message: InboundMessage,
        checked: _Checked,
        now: datetime,
        meter: Meter,
        deadline: datetime,
    ) -> PhotoRead | HandleOutcome | None:
        """The photo read, or how the message ends here: a group photo nobody addressed goes
        on only if it is a receipt, and says nothing if the read failed."""
        chat = chat_hash(message)
        photo = None
        if checked.speaker_id is not None and self._may_read(message.image, checked):
            try:
                photo = self._read(message, checked.speaker_id, now, meter, deadline)
            except LlmUnavailableError:
                if _unaddressed_group_photo(message):
                    return HandleOutcome((), TurnReport(chat, "failed", seconds=self._since(now)))
                report = TurnReport(chat, "failed", seconds=self._since(now))
                return try_again(message, checked.speaker_id, report)
        if _unaddressed_group_photo(message) and (
            photo is None or photo.outcome is not PhotoOutcome.RECEIPT
        ):
            return HandleOutcome((), TurnReport(chat, "silent"))
        return photo

    def _screen(
        self, message: InboundMessage, now: datetime, day: date, chat: str
    ) -> HandleOutcome | _Checked:
        """The read-only checks: a repeat, whether the bot reacts, the daily limits."""
        with self._repository.unit_of_work() as uow:
            done = uow.processed.get(message.conversation, message.message_id)
            if done is not None:
                return HandleOutcome(done.replies, TurnReport(chat, "repeat"))
            checked = self._check(uow, message, now, day)
        reacts = always_reacts(message) or checked.waited_on
        if checked.new_group and not (addressed(message) or _bot_added(message)):
            reacts = False  # a group is created only when someone talks to the bot (SPEC 10.3)
        if not reacts:
            return HandleOutcome((), TurnReport(chat, "silent"))
        limits = checked.limits
        noticeable = addressed(message) and checked.speaker_id is not None
        if limits.over and message.event is None and not noticeable:
            report = TurnReport(chat, "limit", install_nearly_spent=limits.install_nearly_spent)
            return HandleOutcome((), report)
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
            and waiting_on(
                uow,
                message.conversation,
                group_id,
                speaker_id,
                now=now,
                keep=self._settings.chat_history_keep,
            )
        )
        new_group = conversation is None and message.conversation_kind is ConversationKind.GROUP
        limits = allowance(uow, speaker_id, day, self._settings)
        return _Checked(speaker_id, member, waited, new_group, limits)

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
                replies = self._needs_number(uow, message, now)
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
                    canonicalizer=MeteredCanonicalizer(
                        self._canonicalizer,
                        incoming.meter,
                        self._clock,
                        incoming.deadline,
                        settings.llm_timeout_seconds,
                    ),
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

    def _needs_number(
        self, uow: UnitOfWork, message: InboundMessage, now: datetime
    ) -> tuple[OutboundMessage, ...]:
        """Someone known only by a hidden id: "message me 1:1 first", kept in the transcript
        like every bot message; never posted in a group for a message not meant for the bot."""
        if not addressed(message):
            return ()
        text = NEEDS_NUMBER.format(link=self._settings.bot_link)
        key = message.conversation
        append(uow, key, sender_id=None, text=text, refs=(), now=now)
        uow.chat.prune(key, self._settings.chat_history_keep)
        return (OutboundMessage(key, None, text),)

    def _respond(self, turn: Turn, incoming: _Incoming, *, welcomed: bool) -> LoopResult:
        """The model's words and what it did; events and the daily limit need no model."""
        message = incoming.message
        if message.event is not None:
            chat_event(turn, message.event)
            return LoopResult()
        if incoming.over_limit:
            day = local_date(turn.now, turn.settings.timezone)
            first = first_notice_today(self._repository, turn.speaker.id, day)
            return LoopResult(OVER_LIMIT if first else "")
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
        turn.quoted = quoted.refs if quoted else ()
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


def _unaddressed_group_photo(message: InboundMessage) -> bool:
    return (
        message.image is not None
        and message.conversation_kind is ConversationKind.GROUP
        and not addressed(message)
    )


def _bot_added(message: InboundMessage) -> bool:
    return message.event is not None and message.event.kind == "bot_added"
