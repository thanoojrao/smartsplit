"""Persistence port: one transaction per unit of work, one store per aggregate (CONTRACTS 4).

Stores return frozen domain records; a change is written back with `update`/`put`.
Queries return tuples in a stable order (stated per method).
"""

from collections.abc import Collection
from contextlib import AbstractContextManager
from datetime import date, datetime
from typing import Protocol

from smartsplit.domain.enums import DraftState, NotificationKind, PromptStatus
from smartsplit.domain.model import (
    AnswerObservation,
    Bill,
    BillDraft,
    ChatIdentity,
    Conversation,
    Group,
    ItemAlias,
    LlmUsage,
    Membership,
    Nickname,
    Person,
    PhotoRead,
    Receipt,
    Rule,
    Settlement,
)
from smartsplit.domain.prompts import (
    ChatMessage,
    Notification,
    ProcessedMessage,
    Prompt,
    TickBatch,
)
from smartsplit.domain.values import Context, ConversationKey, LocalScope, RuleScope


class PeopleStore(Protocol):
    def get(self, person_id: str) -> Person | None: ...
    def by_phone(self, phone: str) -> Person | None: ...
    def add(self, person: Person) -> None: ...
    def update(self, person: Person) -> None: ...


class IdentityStore(Protocol):
    def get(self, channel: str, external_ref: str) -> ChatIdentity | None: ...
    def add(self, identity: ChatIdentity) -> None: ...
    def for_person(self, person_id: str) -> tuple[ChatIdentity, ...]:
        """By channel, then external ref."""
        ...


class NicknameStore(Protocol):
    def put(self, nickname: Nickname) -> None:
        """Insert, or replace the owner's nickname with the same name."""
        ...

    def for_owner(self, owner_id: str) -> tuple[Nickname, ...]:
        """By name."""
        ...


class GroupStore(Protocol):
    def get(self, group_id: str) -> Group | None: ...
    def by_channel_ref(self, key: ConversationKey) -> Group | None: ...
    def add(self, group: Group) -> None: ...
    def update(self, group: Group) -> None: ...


class MembershipStore(Protocol):
    def add(self, membership: Membership) -> None: ...
    def end(self, group_id: str, person_id: str, left_at: datetime) -> None:
        """End the person's current membership of the group."""
        ...

    def for_group(self, group_id: str) -> tuple[Membership, ...]:
        """Every membership ever, by position (leavers keep their place)."""
        ...

    def for_person(self, person_id: str) -> tuple[Membership, ...]:
        """By joined_at."""
        ...


class ConversationStore(Protocol):
    def get(self, key: ConversationKey) -> Conversation | None: ...
    def personal_for(self, person_id: str) -> Conversation | None:
        """The person's own 1:1 chat with the bot, if they have one (the first by channel and
        ref if several, so both backends agree)."""
        ...

    def add(self, conversation: Conversation) -> None: ...
    def update(self, conversation: Conversation) -> None: ...


class ItemStore(Protocol):
    def ensure(self, key: str) -> None:
        """Add the item key if it is new."""
        ...

    def keys(self) -> frozenset[str]: ...


class AliasStore(Protocol):
    def put(self, alias: ItemAlias) -> None:
        """Insert, or replace the alias for the same (scope, raw_name)."""
        ...

    def delete(self, scope: LocalScope, raw_name: str) -> None: ...
    def for_scope(self, scope: LocalScope) -> tuple[ItemAlias, ...]:
        """By raw name."""
        ...


class RuleStore(Protocol):
    def get(self, rule_id: str) -> Rule | None: ...
    def find(self, scope: RuleScope, subject_id: str, item_key: str) -> Rule | None: ...
    def put(self, rule: Rule) -> None:
        """Insert, replacing any rule for the same (scope, subject, item key)."""
        ...

    def delete(self, rule_id: str) -> None: ...
    def for_subjects(self, subject_ids: Collection[str]) -> tuple[Rule, ...]:
        """By created_at, then id."""
        ...


class ObservationStore(Protocol):
    def add(self, observation: AnswerObservation) -> None: ...
    def for_subject_item(
        self, scope: LocalScope, subject_id: str, item_key: str
    ) -> tuple[AnswerObservation, ...]:
        """Oldest first (observed_at, then insertion order)."""
        ...


class ReceiptStore(Protocol):
    def get(self, receipt_id: str) -> Receipt | None: ...
    def add(self, receipt: Receipt) -> None: ...


class DraftStore(Protocol):
    def get(self, draft_id: str) -> BillDraft | None: ...
    def add(self, draft: BillDraft) -> None:
        """Raises DuplicateKeyError if the adder already has an active draft in that chat."""
        ...

    def update(self, draft: BillDraft, expected_version: int) -> None:
        """Write the draft only if the stored one is still at `expected_version` (SPEC 12.2).

        Raises StaleDraftError if it changed meanwhile, KeyError if it doesn't exist.
        """
        ...

    def for_conversation(
        self, key: ConversationKey, states: Collection[DraftState]
    ) -> tuple[BillDraft, ...]:
        """Drafts of this chat in one of `states`, oldest first."""
        ...

    def open_in_context(self, context: Context) -> tuple[BillDraft, ...]:
        """Active and queued drafts of one group, or all personal ones, in any chat, oldest
        first: a group draft can be under review in someone's personal chat (SPEC 10.4)."""
        ...

    def due_for_reminder_or_expiry(self, idle_since: datetime) -> tuple[BillDraft, ...]:
        """Awaiting-people or reviewing drafts with no activity since `idle_since`, oldest first.

        The caller decides between reminder and expiry from the draft's times.
        """
        ...


ACTIVE_DRAFT_STATES = frozenset({DraftState.AWAITING_PEOPLE, DraftState.REVIEWING})
"""At most one draft per (conversation, adder) is in one of these states (SPEC section 4.5)."""

OPEN_DRAFT_STATES = ACTIVE_DRAFT_STATES | {DraftState.QUEUED}
"""Not finished yet: active, or waiting behind the active one."""

IDLE_DRAFT_STATES = ACTIVE_DRAFT_STATES
"""Drafts that wait on people and can be reminded about or expire (SPEC section 10.4)."""


class PhotoStore(Protocol):
    def get(self, key: ConversationKey, message_id: str) -> PhotoRead | None: ...
    def add(self, photo: PhotoRead) -> None:
        """Raises DuplicateKeyError if that message's photo was already stored."""
        ...

    def update(self, photo: PhotoRead) -> None: ...
    def latest_unused(
        self, key: ConversationKey, sender_id: str, since: datetime
    ) -> PhotoRead | None:
        """The sender's newest receipt photo in this chat since then, not yet in a draft."""
        ...


class ChatStore(Protocol):
    def append(self, message: ChatMessage) -> ChatMessage:
        """Store a transcript line; its `seq` comes from one sequence for every chat."""
        ...

    def recent(self, key: ConversationKey, limit: int) -> tuple[ChatMessage, ...]:
        """The last `limit` messages of the chat, oldest first."""
        ...

    def prune(self, key: ConversationKey, keep: int) -> None:
        """Keep only the newest `keep` messages of the chat."""
        ...

    def delete_older_than(self, before: datetime) -> int:
        """Delete every chat's messages created before then; returns how many."""
        ...


class PromptStore(Protocol):
    def get(self, prompt_id: str) -> Prompt | None: ...
    def add(self, prompt: Prompt) -> None: ...
    def update(self, prompt: Prompt) -> None: ...
    def for_conversation(
        self, key: ConversationKey, statuses: Collection[PromptStatus]
    ) -> tuple[Prompt, ...]:
        """Oldest first."""
        ...

    def for_draft(self, draft_id: str) -> tuple[Prompt, ...]:
        """Oldest first."""
        ...


class BillStore(Protocol):
    def get(self, bill_id: str) -> Bill | None: ...
    def add(self, bill: Bill) -> None: ...
    def for_context(self, context: Context) -> tuple[Bill, ...]:
        """Oldest first."""
        ...

    def for_participant(self, person_id: str) -> tuple[Bill, ...]:
        """Every bill the person is a participant in, oldest first."""
        ...


class SettlementStore(Protocol):
    def add(self, settlement: Settlement) -> None: ...
    def for_person(self, person_id: str) -> tuple[Settlement, ...]:
        """Every settlement row the person sends or receives, in any context, oldest first."""
        ...

    def for_context(self, context: Context) -> tuple[Settlement, ...]:
        """Oldest first."""
        ...

    def for_payment(self, payment_id: str) -> tuple[Settlement, ...]: ...


class NotificationStore(Protocol):
    def add(self, notification: Notification) -> None: ...
    def exists_since(
        self, actor_id: str, recipient_id: str, kind: NotificationKind, since: datetime
    ) -> bool:
        """Whether `actor_id` caused one of these for `recipient_id` since then, sent or not
        (e.g. "remind Raj" at most once a day)."""
        ...

    def claim_due(
        self, now: datetime, limit: int, per_person_daily_cap: int, day_start: datetime
    ) -> tuple[Notification, ...]:
        """Claim unsent notifications, oldest first, mark them sent at `now`, and return them.

        Held (left unsent): a recipient who hasn't used the bot or has notifications off, and
        anything beyond `per_person_daily_cap` sent since `day_start`. Concurrent claims never
        exceed the cap.
        """
        ...


class TickBatchStore(Protocol):
    def add(self, batch: TickBatch) -> None: ...
    def unacked_before(self, when: datetime) -> tuple[TickBatch, ...]:
        """Batches not acknowledged that were created before `when`, oldest first."""
        ...

    def ack(self, batch_id: str, at: datetime) -> bool:
        """Mark it delivered; False if there is no such batch."""
        ...

    def delete_acked_before(self, when: datetime) -> None:
        """Forget delivered batches created before `when`."""
        ...


class ProcessedStore(Protocol):
    def get(self, key: ConversationKey, message_id: str) -> ProcessedMessage | None: ...
    def add(self, processed: ProcessedMessage) -> None: ...


class LlmUsageStore(Protocol):
    def get(self, counter: str, day: date) -> LlmUsage | None: ...
    def increment(self, counter: str, day: date) -> int:
        """Count one more model call and return the day's new total (CONTRACTS: `add`)."""
        ...


class UnitOfWork(Protocol):
    """One transaction's view of every store (read-only members, so implementations may narrow)."""

    def savepoint(self) -> AbstractContextManager[None]:
        """Undo just the writes inside the block if it raises; the transaction goes on (one
        refused tool call leaves nothing half done, SPEC 8.3)."""
        ...

    @property
    def people(self) -> PeopleStore: ...

    @property
    def identities(self) -> IdentityStore: ...

    @property
    def nicknames(self) -> NicknameStore: ...

    @property
    def groups(self) -> GroupStore: ...

    @property
    def memberships(self) -> MembershipStore: ...

    @property
    def conversations(self) -> ConversationStore: ...

    @property
    def items(self) -> ItemStore: ...

    @property
    def aliases(self) -> AliasStore: ...

    @property
    def rules(self) -> RuleStore: ...

    @property
    def observations(self) -> ObservationStore: ...

    @property
    def photos(self) -> PhotoStore: ...

    @property
    def receipts(self) -> ReceiptStore: ...

    @property
    def drafts(self) -> DraftStore: ...

    @property
    def prompts(self) -> PromptStore: ...

    @property
    def bills(self) -> BillStore: ...

    @property
    def settlements(self) -> SettlementStore: ...

    @property
    def chat(self) -> ChatStore: ...

    @property
    def notifications(self) -> NotificationStore: ...

    @property
    def tick_batches(self) -> TickBatchStore: ...

    @property
    def processed(self) -> ProcessedStore: ...

    @property
    def llm_usage(self) -> LlmUsageStore: ...


class Repository(Protocol):
    def unit_of_work(
        self,
        lock: ConversationKey | None = None,
        *,
        lock_wait_seconds: float | None = None,
        try_lock: bool = False,
    ) -> AbstractContextManager[UnitOfWork]:
        """One transaction: commits on success, rolls back on exception.

        With `lock`, messages for that conversation are serialized for the whole transaction.
        A lock not taken within `lock_wait_seconds` raises ChatBusyError; with `try_lock` it
        raises at once (SPEC 12.2).
        """
        ...

    def count_usage(self, counter: str, day: date) -> int:
        """Count one model call in its own short transaction, committed at once, so it stays
        counted even if the turn that made the call rolls back (SPEC 12.5); returns the day's
        new total. Safe to call while a unit of work is open."""
        ...
