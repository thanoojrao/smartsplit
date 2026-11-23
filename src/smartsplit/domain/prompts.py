"""What the bot is waiting for, the notification outbox and idempotency (CONTRACTS 1.5)."""

from dataclasses import dataclass
from datetime import datetime

from smartsplit.domain.commands import AnswerPrompt, Command
from smartsplit.domain.enums import NotificationKind, PromptKind, PromptStatus, QuestionReason
from smartsplit.domain.messages import OutboundMessage
from smartsplit.domain.model import Bill, Rule, Settlement
from smartsplit.domain.values import Cents, ConversationKey, PersonRef


@dataclass(frozen=True, slots=True)
class EngineQuestionPayload:
    line_id: str
    member_id: str | None
    reason: QuestionReason


@dataclass(frozen=True, slots=True)
class ListOption:
    n: int
    person_ids: tuple[str, ...]
    group_id: str | None
    label: str


@dataclass(frozen=True, slots=True)
class WhoWithPayload:
    options: tuple[ListOption, ...]


@dataclass(frozen=True, slots=True)
class WhichPersonPayload:
    said: PersonRef
    candidate_ids: tuple[str, ...]
    pending: Command
    """The command to resume once the person is chosen."""


@dataclass(frozen=True, slots=True)
class NeedContactPayload:
    said: PersonRef
    pending: Command


@dataclass(frozen=True, slots=True)
class ConfirmTotalPayload:
    difference_cents: Cents


@dataclass(frozen=True, slots=True)
class ConfirmLinePayload:
    line_id: str


@dataclass(frozen=True, slots=True)
class BillChangeEffect:
    reverse_bill_id: str | None
    new_bill: Bill | None


@dataclass(frozen=True, slots=True)
class PaymentEffect:
    settlements: tuple[Settlement, ...]
    overpaid_cents: Cents


@dataclass(frozen=True, slots=True)
class RuleChangeEffect:
    add: Rule | None
    delete_rule_id: str | None


type Effect = BillChangeEffect | PaymentEffect | RuleChangeEffect


@dataclass(frozen=True, slots=True)
class ConfirmActionPayload:
    """The exact effect that was restated; "yes" applies it only if still at that version."""

    command: Command
    effect: Effect
    based_on_version: int


@dataclass(frozen=True, slots=True)
class JoinGroupPayload:
    person_id: str


@dataclass(frozen=True, slots=True)
class DuplicateWarningPayload:
    other_bill_id: str | None
    other_draft_id: str | None


type PromptPayload = (
    EngineQuestionPayload
    | WhoWithPayload
    | WhichPersonPayload
    | NeedContactPayload
    | ConfirmTotalPayload
    | ConfirmLinePayload
    | ConfirmActionPayload
    | JoinGroupPayload
    | DuplicateWarningPayload
)


@dataclass(frozen=True, slots=True)
class PromptAnswer:
    person_id: str
    answer: AnswerPrompt
    at: datetime


@dataclass(frozen=True, slots=True)
class Prompt:
    """Anything the bot waits for a reply to, persisted so a restart resumes cleanly."""

    id: str
    conversation: ConversationKey
    draft_id: str | None
    kind: PromptKind
    payload: PromptPayload
    status: PromptStatus
    asked_of: str | None
    """Only this person may answer; None means anyone in the context."""
    created_by: str
    created_at: datetime
    answers: tuple[PromptAnswer, ...]


@dataclass(frozen=True, slots=True)
class NotificationArgs:
    """`body` is used only by `requested_reply`; other kinds render when sent."""

    reason: str | None = None
    amount_cents: Cents | None = None
    body: str | None = None


@dataclass(frozen=True, slots=True)
class Notification:
    """Outbox entry for a person's personal chat, rendered at send time with current balances."""

    id: str
    recipient_id: str
    actor_id: str
    kind: NotificationKind
    bill_ids: tuple[str, ...]
    payment_id: str | None
    text_args: NotificationArgs
    created_at: datetime
    sent_at: datetime | None


@dataclass(frozen=True, slots=True)
class ProcessedMessage:
    """A handled inbound message: a repeat of `message_id` returns `replies` unchanged."""

    key: ConversationKey
    message_id: str
    replies: tuple[OutboundMessage, ...]
    processed_at: datetime
