"""What code tracks for the conversation: prompts, the transcript, the outbox, idempotency
(CONTRACTS 1.5)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from smartsplit.domain.enums import NotificationKind, PromptKind, PromptStatus, QuestionReason
from smartsplit.domain.messages import OutboundMessage
from smartsplit.domain.model import Bill, Rule, Settlement
from smartsplit.domain.tools import PendingArgs
from smartsplit.domain.values import Cents, ConversationKey, Weight


@dataclass(frozen=True, slots=True)
class EngineQuestionPayload:
    line_id: str
    member_id: str | None
    reason: QuestionReason


@dataclass(frozen=True, slots=True)
class BillChangeEffect:
    reverse_bill_id: str
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
class PendingActionPayload:
    """The exact effect that was restated; a "yes" applies it only if still at that version."""

    tool: str
    arguments: PendingArgs
    """With ids in place of handles, so the effect can be recomputed when it went stale."""
    effect: Effect
    based_on_version: int
    proposed_in_message_id: str
    """A proposal is never confirmed in the turn that made it (SPEC 8.4)."""


@dataclass(frozen=True, slots=True)
class WhichPersonPayload:
    """ "Which Sam?" for a bill: the name as said and the people offered, in the order shown,
    so the answer's number means exactly who was listed (L5)."""

    name: str
    options: tuple[str, ...]


type PromptPayload = EngineQuestionPayload | PendingActionPayload | WhichPersonPayload


@dataclass(frozen=True, slots=True)
class PromptAnswer:
    """Who answered a line question, and the line's split their answer made."""

    person_id: str
    assignees: tuple[Weight, ...]
    at: datetime


@dataclass(frozen=True, slots=True)
class Prompt:
    """Something the bot waits on that code must track, persisted so a restart resumes."""

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
    expires_at: datetime | None
    answers: tuple[PromptAnswer, ...]


type RefKind = Literal["person", "bill", "draft", "line", "question", "action", "group", "payment"]


@dataclass(frozen=True, slots=True)
class ChatRef:
    """Something a bot message showed, so later turns can refer to exactly it (SPEC 8.6)."""

    kind: RefKind
    id: str
    version: int | None = None
    """For drafts: the version shown."""
    shares: str | None = None
    """For drafts shown with their split: a fingerprint of the shares, so a split that changed
    without a new version (a rule made meanwhile) isn't saved unseen (SPEC 8.4)."""


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """One line of a chat's transcript; `sender_id` None is the bot."""

    conversation: ConversationKey
    seq: int
    sender_id: str | None
    text: str
    refs: tuple[ChatRef, ...]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class NotificationArgs:
    reason: str | None = None
    amount_cents: Cents | None = None


@dataclass(frozen=True, slots=True)
class Notification:
    """Outbox entry for a person's personal chat, rendered at send time with current balances."""

    id: str
    recipient_id: str
    actor_id: str
    kind: NotificationKind
    bill_ids: tuple[str, ...]
    payment_id: str | None
    args: NotificationArgs
    created_at: datetime
    sent_at: datetime | None


@dataclass(frozen=True, slots=True)
class TickBatch:
    """What one `tick` returned, kept until the gateway acknowledges delivery (SPEC 10.8)."""

    id: str
    messages: tuple[OutboundMessage, ...]
    created_at: datetime
    acked_at: datetime | None


@dataclass(frozen=True, slots=True)
class ProcessedMessage:
    """A handled inbound message: a repeat of `message_id` returns `replies` unchanged."""

    key: ConversationKey
    message_id: str
    replies: tuple[OutboundMessage, ...]
    processed_at: datetime
