"""Persistence port: one transaction per unit of work, one store per aggregate (CONTRACTS 4).

Stores return frozen domain records; a change is written back with `update`/`put`.
Queries return tuples in a stable order (stated per method).
"""

from collections.abc import Collection
from contextlib import AbstractContextManager
from datetime import date, datetime
from typing import Protocol

from smartsplit.domain.enums import DraftState, PromptStatus
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
    Receipt,
    Rule,
    Settlement,
)
from smartsplit.domain.prompts import Notification, ProcessedMessage, Prompt
from smartsplit.domain.values import Context, ConversationKey, LocalScope, RuleScope


class ConstraintViolationError(Exception):
    """A write broke a storage rule; both the fake and Postgres raise these subclasses."""


class DuplicateKeyError(ConstraintViolationError):
    """A record with this key (id, phone, chat, current membership, ...) already exists."""


class MissingReferenceError(ConstraintViolationError):
    """The record points at a person or group that doesn't exist."""


class InvalidRecordError(ConstraintViolationError):
    """The record breaks a check, e.g. a conversation with both a group and a person."""


class StaleDraftError(Exception):
    """The draft's state changed since it was read (e.g. expired by `tick` meanwhile)."""


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
        """Raises DuplicateKeyError if the chat already has an active draft."""
        ...

    def update(self, draft: BillDraft, expected_state: DraftState) -> None:
        """Write the draft only if it is still in `expected_state` (SPEC section 12.2).

        Raises StaleDraftError if its state changed meanwhile, KeyError if it doesn't exist.
        """
        ...

    def for_conversation(
        self, key: ConversationKey, states: Collection[DraftState]
    ) -> tuple[BillDraft, ...]:
        """Drafts of this chat in one of `states`, oldest first."""
        ...

    def due_for_reminder_or_expiry(self, idle_since: datetime) -> tuple[BillDraft, ...]:
        """Awaiting-people or reviewing drafts with no activity since `idle_since`, oldest first.

        The caller decides between reminder and expiry from the draft's times.
        """
        ...


ACTIVE_DRAFT_STATES = frozenset(
    {DraftState.AWAITING_PEOPLE, DraftState.PARSING, DraftState.REVIEWING}
)
"""At most one draft per conversation is in one of these states (SPEC section 4.5)."""

IDLE_DRAFT_STATES = frozenset({DraftState.AWAITING_PEOPLE, DraftState.REVIEWING})
"""Drafts that wait on people and can be reminded about or expire (SPEC section 10.4)."""


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
    def for_context(self, context: Context) -> tuple[Settlement, ...]:
        """Oldest first."""
        ...

    def for_payment(self, payment_id: str) -> tuple[Settlement, ...]: ...


class NotificationStore(Protocol):
    def add(self, notification: Notification) -> None: ...
    def claim_due(
        self, now: datetime, limit: int, per_person_daily_cap: int, day_start: datetime
    ) -> tuple[Notification, ...]:
        """Claim unsent notifications, oldest first, mark them sent at `now`, and return them.

        Held (left unsent): a recipient who hasn't used the bot or has notifications off, and
        anything beyond `per_person_daily_cap` sent since `day_start`, except `requested_reply`,
        which is never held and doesn't count. Concurrent claims never exceed the cap.
        """
        ...


class ProcessedStore(Protocol):
    def get(self, key: ConversationKey, message_id: str) -> ProcessedMessage | None: ...
    def add(self, processed: ProcessedMessage) -> None: ...


class LlmUsageStore(Protocol):
    def get(self, person_id: str, day: date) -> LlmUsage | None: ...
    def increment(self, person_id: str, day: date) -> int:
        """Count one more model call and return the day's new total."""
        ...


class UnitOfWork(Protocol):
    """One transaction's view of every store (read-only members, so implementations may narrow)."""

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
    def notifications(self) -> NotificationStore: ...

    @property
    def processed(self) -> ProcessedStore: ...

    @property
    def llm_usage(self) -> LlmUsageStore: ...


class Repository(Protocol):
    def unit_of_work(
        self, lock: ConversationKey | None = None
    ) -> AbstractContextManager[UnitOfWork]:
        """One transaction: commits on success, rolls back on exception.

        With `lock`, messages for that conversation are serialized for the whole transaction.
        """
        ...
