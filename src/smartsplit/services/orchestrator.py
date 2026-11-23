"""The conversation state machine's entry point (SPEC section 10, CONTRACTS section 5).

One inbound message: read what's needed and call the model with no lock held, then handle it
in one locked transaction that also records the message as processed, then read any receipt
that this started, again outside the lock (SPEC 12.2).
"""

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from smartsplit.domain.commands import AddPerson, AnswerPrompt, Command, StartSplit, Unknown
from smartsplit.domain.enums import ConversationKind, DraftState, PromptKind, PromptStatus
from smartsplit.domain.messages import ChatEvent, InboundMessage, OutboundMessage
from smartsplit.domain.prompts import ProcessedMessage
from smartsplit.ports.images import ImageStore
from smartsplit.ports.llm import (
    CommandInterpreter,
    InterpretContext,
    LlmUnavailableError,
    ReceiptParser,
    ReceiptUnreadableError,
)
from smartsplit.ports.repository import Repository, UnitOfWork
from smartsplit.ports.system import Clock, IdGenerator
from smartsplit.services.answers import ask_who
from smartsplit.services.command_checks import InvalidAmountError, check_amounts
from smartsplit.services.context import interpret_context
from smartsplit.services.dispatch import Photo, dispatch
from smartsplit.services.drafting import lines_from_receipt
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.ledgers import overall_text
from smartsplit.services.matching import load_match_inputs, match_lines
from smartsplit.services.membership import member_left
from smartsplit.services.names import MIN_PHONE_DIGITS, NeedsClarificationError
from smartsplit.services.receipt_flow import finish_parse, parse_failed
from smartsplit.services.scopes import local_scope_for
from smartsplit.services.speaker import Arrival, addressed, arrive, find_speaker
from smartsplit.services.text import HELP
from smartsplit.services.turn import OrchestratorSettings, Turn

TRY_AGAIN = "Couldn't do that, try again in a minute."
NEEDS_NUMBER = "Message me 1:1 first, so I can link this chat to your number."

type Refusal = NotAllowedError | NeedsClarificationError | InvalidAmountError
type Intent = Command | ChatEvent


@dataclass(frozen=True, slots=True)
class _Prepared:
    """What was read before the lock: enough to decide whether, and how, to call the model."""

    done: tuple[OutboundMessage, ...] | None
    react: bool
    over_limit: bool
    speaker_id: str | None
    waiting_for_contact: bool
    context: InterpretContext | None


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
        self._parser = parser
        self._interpreter = interpreter
        self._clock = clock
        self._ids = ids
        self._settings = settings

    def handle(self, message: InboundMessage) -> list[OutboundMessage]:
        """Replies for this message (and any chat it affects); a repeat returns the same."""
        now = self._clock.now()
        prepared = self._prepare(message, now)
        if prepared.done is not None:
            return list(prepared.done)
        if not prepared.react:
            return []
        if prepared.over_limit and message.text:
            limit = NotAllowedError("That's all I can do for you today. Try again tomorrow.")
            replies, _ = self._commit(
                message, now=now, intent=Unknown(""), photo=None, calls=0, refusal=limit
            )
            return replies
        try:
            intent, calls = self._intent(message, prepared)
        except LlmUnavailableError:
            return [OutboundMessage(message.conversation, self._recipient(message), TRY_AGAIN)]
        if message.image is not None and isinstance(intent, StartSplit):
            photo = Photo(
                self._images.save(message.image.data, message.image.mime_type), message.image
            )
        else:
            photo = None
        replies, to_parse = self._commit(message, now=now, intent=intent, photo=photo, calls=calls)
        return replies + self._read_receipts(to_parse)

    def _prepare(self, message: InboundMessage, now: datetime) -> _Prepared:
        with self._repository.unit_of_work() as uow:
            done = uow.processed.get(message.conversation, message.message_id)
            if done is not None:
                return _Prepared(done.replies, False, False, None, False, None)
            speaker = find_speaker(uow, message)
            conversation = uow.conversations.get(message.conversation)
            open_prompts = (
                uow.prompts.for_conversation(conversation.key, [PromptStatus.OPEN])
                if conversation
                else ()
            )
            react = (
                message.conversation_kind is ConversationKind.PERSONAL
                or addressed(message)
                or bool(open_prompts)
            )
            over_limit = speaker is not None and self._calls_today(uow, speaker.id, now) >= (
                self._settings.llm_calls_per_person_per_day
            )
            waiting = speaker is not None and any(
                p.kind is PromptKind.NEED_CONTACT and p.asked_of == speaker.id for p in open_prompts
            )
            context = (
                interpret_context(
                    uow,
                    speaker_id=speaker.id if speaker else None,
                    conversation=conversation,
                    kind=message.conversation_kind,
                    today=local_date(now, self._settings.timezone),
                    currency=self._settings.currency,
                )
                if react and message.text
                else None
            )
            speaker_id = speaker.id if speaker else None
            return _Prepared(None, react, over_limit, speaker_id, waiting, context)

    def _calls_today(self, uow: UnitOfWork, person_id: str, now: datetime) -> int:
        usage = uow.llm_usage.get(person_id, local_date(now, self._settings.timezone))
        return usage.calls if usage else 0

    def _intent(self, message: InboundMessage, prepared: _Prepared) -> tuple[Intent, int]:
        """The command, and how many model calls it took. Events, contact cards and numbers
        sent for a "need contact" question need no model."""
        if message.event is not None:
            return message.event, 0
        contact = message.contact
        typed = (message.text or "").strip()
        if prepared.waiting_for_contact and (contact or _looks_like_phone(typed)):
            return AnswerPrompt(text=contact.phone if contact else typed), 0
        if not typed or prepared.context is None:
            if contact is not None:
                return AddPerson(contact.name, contact.phone), 0
            return (StartSplit() if message.image else Unknown("")), 0
        command = self._interpreter.interpret(typed, prepared.context)
        return _fit(command, message), 1

    def _recipient(self, message: InboundMessage) -> str | None:
        if message.conversation_kind is ConversationKind.GROUP:
            return None
        with self._repository.unit_of_work() as uow:
            speaker = find_speaker(uow, message)
            return speaker.id if speaker else None

    def _commit(
        self,
        message: InboundMessage,
        *,
        now: datetime,
        intent: Intent,
        photo: Photo | None,
        calls: int,
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
                if turn is not None:
                    for _ in range(calls):
                        uow.llm_usage.increment(turn.speaker.id, turn.today)
                    if refusal is None:
                        self._run(turn, intent, photo)
                    else:
                        _refuse(turn, refusal, intent)
                replies = (
                    turn.replies
                    if turn
                    else [OutboundMessage(message.conversation, None, NEEDS_NUMBER)]
                )
                uow.processed.add(
                    ProcessedMessage(message.conversation, message.message_id, tuple(replies), now)
                )
                return list(replies), list(turn.to_parse) if turn else []
        except _RefusedError as refused:
            return self._commit(
                message,
                now=now,
                intent=intent,
                photo=photo,
                calls=calls,
                refusal=refused.refusal,
            )

    def _turn(self, uow: UnitOfWork, message: InboundMessage, now: datetime) -> Turn | None:
        """The speaker and chat for this message (created if new), with any greeting."""
        arrival = arrive(uow, self._ids, message, self._settings.default_region, now)
        if arrival is None:
            return None
        turn = Turn(uow, self._ids, now, self._settings, arrival.speaker, arrival.conversation)
        _greet(turn, arrival)
        return turn

    def _run(self, turn: Turn, intent: Intent, photo: Photo | None) -> None:
        try:
            if isinstance(intent, ChatEvent):
                _participant_left(turn, intent)
                return
            check_amounts(intent, self._settings.max_amount_cents)
            dispatch(turn, intent, photo)
        except (NotAllowedError, NeedsClarificationError, InvalidAmountError) as refusal:
            raise _RefusedError(refusal) from refusal

    def _read_receipts(self, draft_ids: list[str]) -> list[OutboundMessage]:
        """Read each receipt that started this message, outside the lock; finishing or
        failing one can start the next queued draft, which is read in turn."""
        replies: list[OutboundMessage] = []
        pending = list(draft_ids)
        while pending:
            more_replies, more = self._read_receipt(pending.pop(0))
            replies += more_replies
            pending += more
        return replies

    def _read_receipt(self, draft_id: str) -> tuple[list[OutboundMessage], list[str]]:
        with self._repository.unit_of_work() as uow:
            draft = uow.drafts.get(draft_id)
            if draft is None or draft.state is not DraftState.PARSING or not draft.image_ref:
                return [], []
            inputs = load_match_inputs(uow, local_scope_for(draft.context, draft.added_by))
        readable = True
        try:
            image = self._images.load(draft.image_ref)
            parsed = self._parser.parse(image, draft.image_mime_type or "", self._settings.currency)
            lines = lines_from_receipt(self._ids, parsed)
            matched = match_lines(lines, inputs, self._interpreter, self._settings.fuzzy_threshold)
        except (KeyError, ReceiptUnreadableError):
            readable = False
        except LlmUnavailableError:
            return [OutboundMessage(draft.conversation, None, TRY_AGAIN)], []
        with self._repository.unit_of_work(lock=draft.conversation) as uow:
            current = uow.drafts.get(draft_id)
            conversation = uow.conversations.get(draft.conversation)
            adder = uow.people.get(draft.added_by)
            if (
                current is None
                or current.state is not DraftState.PARSING
                or not (conversation and adder)
            ):
                return [], []
            turn = Turn(uow, self._ids, self._clock.now(), self._settings, adder, conversation)
            if readable:
                for _ in range(1 + matched.model_calls):
                    uow.llm_usage.increment(adder.id, turn.today)
                finish_parse(turn, current, parsed, matched)
            else:
                parse_failed(turn, current)
            return turn.replies, turn.to_parse


def _fit(command: Command, message: InboundMessage) -> Command:
    """Make the command fit what came with it: a photo is always a receipt to split (its
    caption says with whom), a contact card fills in the number, and in a group a message
    that wasn't addressed to the bot only counts if it answers its question (SPEC 10.2)."""
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
    group_aside = message.conversation_kind is ConversationKind.GROUP and not addressed(message)
    if group_aside and not isinstance(command, AnswerPrompt):
        return Unknown(message.text or "")
    return command


def _looks_like_phone(text: str) -> bool:
    digits = sum(ch.isdigit() for ch in text)
    return digits >= MIN_PHONE_DIGITS and all(ch.isdigit() or ch in "+-() ." for ch in text)


def local_date(now: datetime, timezone: str) -> date:
    return now.astimezone(ZoneInfo(timezone)).date()


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


def _refuse(turn: Turn, refusal: Refusal, intent: Intent) -> None:
    if isinstance(refusal, NeedsClarificationError) and not isinstance(intent, ChatEvent):
        ask_who(turn, refusal, intent)
        return
    turn.reply(str(refusal))
