"""Entities: people, places, items, rules, receipts, drafts, bills, payments (CONTRACTS 1.3-1.4).

Records are frozen; a change is a new value written back through the repository.
"""

from dataclasses import dataclass
from datetime import date, datetime

from smartsplit.domain.enums import (
    AnswerOutcome,
    ConversationKind,
    DraftState,
    MatchHow,
    PhotoOutcome,
    RuleKind,
    RuleSource,
    SettlementKind,
)
from smartsplit.domain.values import (
    Cents,
    Context,
    ConversationKey,
    LocalScope,
    Override,
    RuleScope,
    Share,
    Weight,
)


@dataclass(frozen=True, slots=True)
class Person:
    """A person is their phone number (E.164); the id is internal and never changes."""

    id: str
    display_name: str
    phone: str
    phone_added_by: str | None
    notifications_enabled: bool
    has_used_bot: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ChatIdentity:
    """How a person appears in one channel; a number and a hidden id are two identities."""

    channel: str
    external_ref: str
    person_id: str


@dataclass(frozen=True, slots=True)
class Nickname:
    """What `owner_id` calls `subject_id`; `name` is stored normalized."""

    owner_id: str
    subject_id: str
    name: str


@dataclass(frozen=True, slots=True)
class Group:
    id: str
    name: str
    channel_ref: ConversationKey | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Membership:
    """Current while `left_at` is None; rejoining creates a new membership."""

    group_id: str
    person_id: str
    position: int
    joined_at: datetime
    left_at: datetime | None


@dataclass(frozen=True, slots=True)
class Conversation:
    """One chat the bot is in: exactly one of `group_id` and `person_id` is set."""

    key: ConversationKey
    kind: ConversationKind
    name: str | None
    group_id: str | None
    person_id: str | None


@dataclass(frozen=True, slots=True)
class Item:
    """An install-wide item key, so rules about "milk" apply everywhere."""

    key: str


@dataclass(frozen=True, slots=True)
class ItemAlias:
    """A remembered match from a normalized receipt name to an item key, in one place."""

    scope: LocalScope
    raw_name: str
    item_key: str


@dataclass(frozen=True, slots=True)
class Rule:
    """At most one rule per (scope, subject, item key)."""

    id: str
    subject_id: str
    item_key: str
    kind: RuleKind
    scope: RuleScope
    author_id: str
    source: RuleSource
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AnswerObservation:
    """What one saved bill's answers showed about one person and item: input to learning."""

    scope: LocalScope
    subject_id: str
    item_key: str
    outcome: AnswerOutcome
    bill_id: str
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class LlmUsage:
    """Model calls per day (in the install timezone), per person or for the whole install."""

    counter: str
    """A person id, or `INSTALL_COUNTER`."""
    day: date
    calls: int


INSTALL_COUNTER = "install"
"""The usage counter for every model call the install makes (SPEC 12.5)."""


@dataclass(frozen=True, slots=True)
class LineItem:
    """One receipt line. `amount_cents` is the line total, negative for a discount."""

    id: str
    position: int
    name: str
    quantity: int
    amount_cents: Cents
    taxed: bool | None
    confidence: float
    canonical: str | None
    discount_for: str | None
    match_how: MatchHow
    match_is_new: bool


@dataclass(frozen=True, slots=True)
class Receipt:
    """The immutable parse record; review edits happen on the draft's working copy."""

    id: str
    image_ref: str
    mime_type: str
    merchant: str | None
    purchased_at: date | None
    line_items: tuple[LineItem, ...]
    tax_cents: Cents
    other_adjustments_cents: Cents
    total_cents: Cents
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PhotoRead:
    """One inbound photo, read once on arrival (SPEC 7); unique per (conversation, message)."""

    conversation: ConversationKey
    message_id: str
    sender_id: str
    outcome: PhotoOutcome
    receipt_id: str | None
    used_by_draft_id: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DuplicateRef:
    """A saved bill or another open draft that looks like the same receipt: one is set."""

    bill_id: str | None
    draft_id: str | None


@dataclass(frozen=True, slots=True)
class BillDraft:
    """A bill under review, with a working copy of the receipt that review edits change.

    `LineItem.position` is the number people see; it never shifts within a draft.
    """

    id: str
    conversation: ConversationKey
    context: Context
    added_by: str
    payer_id: str
    receipt_id: str | None
    description: str
    purchased_at: date | None
    lines: tuple[LineItem, ...]
    tax_cents: Cents
    other_adjustments_cents: Cents
    total_cents: Cents
    participants: tuple[str, ...]
    overrides: tuple[tuple[str, Override], ...]
    owes_all_id: str | None
    possible_duplicate_of: DuplicateRef | None
    waiting_for: tuple[str, ...]
    """Names said for this bill that aren't known people yet (`awaiting_people`)."""
    state: DraftState
    version: int
    """Goes up on every change, so a confirm can check the adder saw this split (SPEC 8.4)."""
    created_at: datetime
    last_activity_at: datetime
    reminded_at: datetime | None


@dataclass(frozen=True, slots=True)
class BillLine:
    """One saved line and who shared it, so details and edits rebuild without re-running rules."""

    id: str
    position: int
    name: str
    item_key: str
    quantity: int
    amount_cents: Cents
    """Before tax folding, as on the receipt or as edited."""
    taxed: bool | None
    discount_for: str | None
    assignees: tuple[Weight, ...]


@dataclass(frozen=True, slots=True)
class Bill:
    """Append-only. Shares sum exactly to `total_cents`.

    An edit is a reversing bill (`reverses_id`, every amount and share negated, same
    `purchased_at`) plus a new bill (`replaces_id`, `edit_reason`); a delete is only the reversal.
    """

    id: str
    context: Context
    origin: ConversationKey
    receipt_id: str | None
    payer_id: str
    added_by: str
    description: str
    purchased_at: date
    participants: tuple[str, ...]
    lines: tuple[BillLine, ...]
    tax_cents: Cents
    other_adjustments_cents: Cents
    """Includes any accepted difference."""
    total_cents: Cents
    shares: tuple[Share, ...]
    reverses_id: str | None
    replaces_id: str | None
    edit_reason: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Settlement:
    """One context's part of a payment; rows of one real payment share `payment_id`."""

    id: str
    payment_id: str
    context: Context
    from_id: str
    to_id: str
    amount_cents: Cents
    kind: SettlementKind
    recorded_by: str
    reverses_id: str | None
    created_at: datetime
