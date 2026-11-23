"""The conversation state machine's entry point (SPEC section 10, CONTRACTS section 5).

One inbound message: read what's needed and call the model with no lock held, then handle it
in one locked transaction that also records the message as processed, then read any receipt
that this started, again outside the lock (SPEC 12.2).
"""

from dataclasses import dataclass
from datetime import datetime

from smartsplit.domain.commands import StartSplit, Unknown
from smartsplit.domain.enums import ConversationKind, PromptKind, PromptStatus
from smartsplit.domain.messages import ChatEvent, InboundMessage, OutboundMessage
from smartsplit.domain.prompts import ProcessedMessage, StoredImage
from smartsplit.ports.images import ImageStore
from smartsplit.ports.llm import (
    CommandInterpreter,
    InterpretContext,
    LlmUnavailableError,
    ReceiptParser,
)
from smartsplit.ports.repository import Repository, UnitOfWork
from smartsplit.ports.system import Clock, IdGenerator
from smartsplit.services.answers import ask_who
from smartsplit.services.command_checks import InvalidAmountError, check_amounts
from smartsplit.services.context import interpret_context
from smartsplit.services.dispatch import dispatch
from smartsplit.services.errors import NeedsClarificationError, NotAllowedError
from smartsplit.services.intents import (
    Intent,
    cleaned,
    fit_command,
    is_aside,
    local_date,
    without_model,
)
from smartsplit.services.ledgers import overall_text
from smartsplit.services.membership import member_left
from smartsplit.services.prompting import still_asked
from smartsplit.services.receipt_reading import ReceiptReader, Source
from smartsplit.services.speaker import Arrival, arrive, find_speaker
from smartsplit.services.text import HELP, NEEDS_NUMBER, OVER_LIMIT, TRY_AGAIN
from smartsplit.services.ticking import Ticker
from smartsplit.services.turn import OrchestratorSettings, Turn

type Refusal = NotAllowedError | NeedsClarificationError | InvalidAmountError


@dataclass(frozen=True, slots=True)
class _Prepared:
    """What was read before the lock: enough to decide whether, and how, to call the model."""

    done: tuple[OutboundMessage, ...] | None
    react: bool = False
    over_limit: bool = False
    recipient: str | None = None
    intent: Intent | None = None
    """What the message means when no model is needed (`context` None)."""
    context: InterpretContext | None = None
    """Set when the model must interpret the text."""


class _RefusedError(Exception):
    """Carries a refusal out of the transaction, so its writes are rolled back."""

    def __init__(self, refusal: Refusal) -> None:
        super().__init__(str(refusal))
        self.refusal = refusal


class Orchestrator:
    """Channel-agnostic: messages in, messages out, for any chat (CONTRACTS section 5)."""

    def __init__(
        self,
        *,
        repository: Repository,
        images: ImageStore,
        parser: ReceiptParser,
        interpreter: CommandInterpreter,
        clock: Clock,
        ids: IdGenerator,
        settings: OrchestratorSettings,
    ) -> None:
        self._repository = repository
        self._images = images
        self._interpreter = interpreter
        self._clock = clock
        self._ids = ids
        self._settings = settings
        self._reader = ReceiptReader(repository, images, parser, interpreter, clock, ids, settings)
        self._ticker = Ticker(repository, self._reader, clock, ids, settings)

    def tick(self) -> list[OutboundMessage]:
        """Deliver the outbox, nudge or expire idle drafts, and retry unread receipts; call it
        every minute or so (SPEC 10.8)."""
        return self._ticker.tick()

    def handle(self, message: InboundMessage) -> list[OutboundMessage]:
        """Replies for this message (and any chat it affects); a repeat returns the same."""
        message = cleaned(message)
        now = self._clock.now()
        prepared = self._prepare(message, now)
        if prepared.done is not None:
            return list(prepared.done)
        if not prepared.react:
            return []
        uses_model = prepared.context is not None or message.image is not None
        if prepared.over_limit and uses_model:
            if is_aside(message):
                return []
            limit = NotAllowedError(OVER_LIMIT)
            return self._commit(message, now=now, intent=Unknown(""), refusal=limit)[0]
        intent, calls = prepared.intent or Unknown(""), 0
        if prepared.context is not None:
            try:
                command = self._interpreter.interpret(message.text or "", prepared.context)
            except LlmUnavailableError:
                return [OutboundMessage(message.conversation, prepared.recipient, TRY_AGAIN)]
            intent, calls = fit_command(command, message), 1
        photo = None
        if message.image is not None and isinstance(intent, StartSplit):
            image_ref = self._images.save(message.image.data, message.image.mime_type)
            photo = StoredImage(image_ref, message.image.mime_type)
        replies, to_parse = self._commit(message, now=now, intent=intent, photo=photo, calls=calls)
        source = Source(message.conversation, message.message_id)
        return replies + self._reader.read_all(source, to_parse)

    def _prepare(self, message: InboundMessage, now: datetime) -> _Prepared:
        """Read-only: a repeat, whether to react at all, the daily limit, and what the model
        may see. Group chatter is only read while a question this speaker may answer is open,
        and a chat event only counts in a chat the bot already knows (SPEC 10.2)."""
        with self._repository.unit_of_work() as uow:
            done = uow.processed.get(message.conversation, message.message_id)
            if done is not None:
                return _Prepared(done.replies)
            speaker = find_speaker(uow, message)
            speaker_id = speaker.id if speaker else None
            conversation = uow.conversations.get(message.conversation)
            open_prompts = [
                p
                for p in (
                    uow.prompts.for_conversation(conversation.key, [PromptStatus.OPEN])
                    if conversation
                    else ()
                )
                if p.asked_of in (None, speaker_id) and still_asked(p, now, self._settings)
            ]
            if message.event is not None:
                react = conversation is not None
            else:
                react = not is_aside(message) or bool(open_prompts)
            waiting = any(
                p.kind is PromptKind.NEED_CONTACT and p.asked_of == speaker_id for p in open_prompts
            )
            intent = without_model(message, waiting_for_contact=waiting)
            context = None
            if react and intent is None:
                context = interpret_context(
                    uow,
                    speaker_id=speaker_id,
                    conversation=conversation,
                    kind=message.conversation_kind,
                    today=local_date(now, self._settings.timezone),
                    currency=self._settings.currency,
                )
            over_limit = speaker_id is not None and self._calls_today(uow, speaker_id, now) >= (
                self._settings.llm_calls_per_person_per_day
            )
            personal = message.conversation_kind is ConversationKind.PERSONAL
            return _Prepared(
                None,
                react=react,
                over_limit=over_limit,
                recipient=speaker_id if personal else None,
                intent=intent,
                context=context,
            )

    def _calls_today(self, uow: UnitOfWork, person_id: str, now: datetime) -> int:
        usage = uow.llm_usage.get(person_id, local_date(now, self._settings.timezone))
        return usage.calls if usage else 0

    def _commit(
        self,
        message: InboundMessage,
        *,
        now: datetime,
        intent: Intent,
        photo: StoredImage | None = None,
        calls: int = 0,
        refusal: Refusal | None = None,
    ) -> tuple[list[OutboundMessage], list[str]]:
        """Handle the message in one transaction under the conversation lock. A refusal rolls
        the handler's writes back; the message is then recorded with only the refusal."""
        try:
            with self._repository.unit_of_work(lock=message.conversation) as uow:
                done = uow.processed.get(message.conversation, message.message_id)
                if done is not None:
                    return list(done.replies), []
                turn = self._turn(uow, message, now)
                if turn is None:
                    replies = [OutboundMessage(message.conversation, None, NEEDS_NUMBER)]
                    to_parse: list[str] = []
                else:
                    for _ in range(calls):
                        uow.llm_usage.increment(turn.speaker.id, turn.today)
                    if refusal is None:
                        self._run(turn, intent, photo)
                    else:
                        _refuse(turn, refusal, intent, photo)
                    replies, to_parse = turn.replies, turn.to_parse
                uow.processed.add(
                    ProcessedMessage(message.conversation, message.message_id, tuple(replies), now)
                )
                return list(replies), list(to_parse)
        except _RefusedError as refused:
            return self._commit(
                message, now=now, intent=intent, photo=photo, calls=calls, refusal=refused.refusal
            )

    def _turn(self, uow: UnitOfWork, message: InboundMessage, now: datetime) -> Turn | None:
        """The speaker and chat for this message (created if new), with any greeting."""
        arrival = arrive(uow, self._ids, message, self._settings.default_region, now)
        if arrival is None:
            return None
        turn = Turn(
            uow,
            self._ids,
            now,
            self._settings,
            arrival.speaker,
            arrival.conversation,
            addressed=not is_aside(message),
        )
        _greet(turn, arrival)
        return turn

    def _run(self, turn: Turn, intent: Intent, photo: StoredImage | None) -> None:
        try:
            if isinstance(intent, ChatEvent):
                _participant_left(turn, intent)
                return
            check_amounts(intent, self._settings.max_amount_cents)
            dispatch(turn, intent, photo)
        except (NotAllowedError, NeedsClarificationError, InvalidAmountError) as refusal:
            raise _RefusedError(refusal) from refusal


def _greet(turn: Turn, arrival: Arrival) -> None:
    """A first personal message gets a welcome, help and what's waiting (A1); a new group
    asks everyone else to join (A2)."""
    if arrival.first_personal_message:
        waiting = overall_text(turn.uow, turn.speaker.id, turn.settings.currency)
        settled = "You're all settled up."
        extra = "" if waiting == settled else f"\nWaiting for you:\n{waiting}"
        turn.reply(f"Hi {turn.speaker.display_name}! {HELP}{extra}")
    if arrival.new_group:
        turn.reply(
            f"Hi {turn.conversation.name}! {turn.speaker.display_name} is in. "
            'Everyone else who wants to split bills here, reply "join".'
        )


def _participant_left(turn: Turn, event: ChatEvent) -> None:
    identity = turn.uow.identities.get(turn.conversation.key.channel, event.subject_ref)
    if identity is not None and turn.in_group:
        member_left(turn, identity.person_id)


def _refuse(turn: Turn, refusal: Refusal, intent: Intent, photo: StoredImage | None) -> None:
    """A clarification becomes a prompt that keeps the command (and its photo); anything else
    is a short reply, except to group chatter, which gets none."""
    if isinstance(refusal, NeedsClarificationError) and not isinstance(intent, ChatEvent):
        ask_who(turn, refusal, intent, photo)
    elif turn.addressed:
        turn.reply(str(refusal))
