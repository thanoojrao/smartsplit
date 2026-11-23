"""In-memory Repository with real transaction semantics: a failed unit of work changes nothing."""

import copy
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date

from smartsplit.adapters.fakes import bill_stores as b
from smartsplit.adapters.fakes import people_stores as p
from smartsplit.adapters.fakes import rule_stores as r
from smartsplit.domain.values import ConversationKey


@dataclass
class InMemoryUnitOfWork:
    people: p.PeopleStore = field(default_factory=p.PeopleStore)
    identities: p.IdentityStore = field(init=False)
    nicknames: p.NicknameStore = field(init=False)
    groups: p.GroupStore = field(default_factory=p.GroupStore)
    memberships: p.MembershipStore = field(init=False)
    conversations: p.ConversationStore = field(default_factory=p.ConversationStore)
    items: r.ItemStore = field(default_factory=r.ItemStore)
    aliases: r.AliasStore = field(default_factory=r.AliasStore)
    rules: r.RuleStore = field(default_factory=r.RuleStore)
    observations: r.ObservationStore = field(default_factory=r.ObservationStore)
    photos: b.PhotoStore = field(default_factory=b.PhotoStore)
    receipts: b.ReceiptStore = field(default_factory=b.ReceiptStore)
    drafts: b.DraftStore = field(default_factory=b.DraftStore)
    prompts: b.PromptStore = field(default_factory=b.PromptStore)
    bills: b.BillStore = field(default_factory=b.BillStore)
    settlements: b.SettlementStore = field(default_factory=b.SettlementStore)
    chat: b.ChatStore = field(default_factory=b.ChatStore)
    notifications: b.NotificationStore = field(init=False)
    tick_batches: b.TickBatchStore = field(default_factory=b.TickBatchStore)
    processed: b.ProcessedStore = field(default_factory=b.ProcessedStore)
    llm_usage: r.LlmUsageStore = field(default_factory=r.LlmUsageStore)

    def __post_init__(self) -> None:
        """Stores that check references get the stores they point into."""
        self.identities = p.IdentityStore(self.people)
        self.nicknames = p.NicknameStore(self.people)
        self.memberships = p.MembershipStore(self.groups, self.people)
        self.notifications = b.NotificationStore(self.people)

    @contextmanager
    def savepoint(self) -> Iterator[None]:
        """Restore every store if the block raises."""
        saved = copy.deepcopy(self.__dict__)
        try:
            yield
        except BaseException:
            self.__dict__.update(saved)
            raise


class InMemoryRepository:
    """Each unit of work runs on a copy that replaces the committed state only on success.

    The fake is single-threaded, so the conversation lock needs no implementation.
    """

    def __init__(self) -> None:
        self._committed = InMemoryUnitOfWork()
        self._open = False
        self._working: InMemoryUnitOfWork | None = None

    @contextmanager
    def unit_of_work(
        self,
        lock: ConversationKey | None = None,
        *,
        lock_wait_seconds: float | None = None,
        try_lock: bool = False,
    ) -> Iterator[InMemoryUnitOfWork]:
        """Nested units of work would silently lose writes here, so they are refused. One
        thread at a time, so a lock is always free (the wait and try-lock never fail)."""
        if self._open:
            raise RuntimeError("a unit of work is already open")
        self._open = True
        try:
            working = copy.deepcopy(self._committed)
            self._working = working
            yield working
            self._committed = working
        finally:
            self._open = False
            self._working = None

    def count_usage(self, counter: str, day: date) -> int:
        """Written to the committed state and to any open unit of work, so a rollback of that
        unit of work keeps it, like a separate Postgres transaction."""
        calls = self._committed.llm_usage.increment(counter, day)
        if self._working is not None:
            self._working.llm_usage.increment(counter, day)
        return calls
