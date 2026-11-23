"""In-memory Repository with real transaction semantics: a failed unit of work changes nothing."""

import copy
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from smartsplit.adapters.fakes import bill_stores as b
from smartsplit.adapters.fakes import people_stores as p
from smartsplit.adapters.fakes import rule_stores as r
from smartsplit.domain.values import ConversationKey


@dataclass
class InMemoryUnitOfWork:
    people: p.PeopleStore = field(default_factory=p.PeopleStore)
    identities: p.IdentityStore = field(default_factory=p.IdentityStore)
    nicknames: p.NicknameStore = field(default_factory=p.NicknameStore)
    groups: p.GroupStore = field(default_factory=p.GroupStore)
    memberships: p.MembershipStore = field(default_factory=p.MembershipStore)
    conversations: p.ConversationStore = field(default_factory=p.ConversationStore)
    items: r.ItemStore = field(default_factory=r.ItemStore)
    aliases: r.AliasStore = field(default_factory=r.AliasStore)
    rules: r.RuleStore = field(default_factory=r.RuleStore)
    observations: r.ObservationStore = field(default_factory=r.ObservationStore)
    receipts: b.ReceiptStore = field(default_factory=b.ReceiptStore)
    drafts: b.DraftStore = field(default_factory=b.DraftStore)
    prompts: b.PromptStore = field(default_factory=b.PromptStore)
    bills: b.BillStore = field(default_factory=b.BillStore)
    settlements: b.SettlementStore = field(default_factory=b.SettlementStore)
    notifications: b.NotificationStore = field(init=False)
    processed: b.ProcessedStore = field(default_factory=b.ProcessedStore)
    llm_usage: r.LlmUsageStore = field(default_factory=r.LlmUsageStore)

    def __post_init__(self) -> None:
        self.notifications = b.NotificationStore(self.people)


class InMemoryRepository:
    """Each unit of work runs on a copy that replaces the committed state only on success.

    The fake is single-threaded, so the conversation lock needs no implementation.
    """

    def __init__(self) -> None:
        self._committed = InMemoryUnitOfWork()

    @contextmanager
    def unit_of_work(self, lock: ConversationKey | None = None) -> Iterator[InMemoryUnitOfWork]:
        working = copy.deepcopy(self._committed)
        yield working
        self._committed = working
