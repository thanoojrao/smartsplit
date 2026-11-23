"""Postgres Repository: one transaction per unit of work, optional per-conversation lock."""

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, Engine, create_engine, func, select

from smartsplit.adapters.db import draft_stores, ledger_stores, people_stores, rule_stores
from smartsplit.domain.values import ConversationKey


class SqlUnitOfWork:
    """The stores, all bound to one connection inside one transaction."""

    def __init__(self, connection: Connection) -> None:
        self.people = people_stores.PeopleStore(connection)
        self.identities = people_stores.IdentityStore(connection)
        self.nicknames = people_stores.NicknameStore(connection)
        self.groups = people_stores.GroupStore(connection)
        self.memberships = people_stores.MembershipStore(connection)
        self.conversations = people_stores.ConversationStore(connection)
        self.items = rule_stores.ItemStore(connection)
        self.aliases = rule_stores.AliasStore(connection)
        self.rules = rule_stores.RuleStore(connection)
        self.observations = rule_stores.ObservationStore(connection)
        self.llm_usage = rule_stores.LlmUsageStore(connection)
        self.receipts = draft_stores.ReceiptStore(connection)
        self.drafts = draft_stores.DraftStore(connection)
        self.prompts = draft_stores.PromptStore(connection)
        self.processed = draft_stores.ProcessedStore(connection)
        self.bills = ledger_stores.BillStore(connection)
        self.settlements = ledger_stores.SettlementStore(connection)
        self.notifications = ledger_stores.NotificationStore(connection)


def lock_id(key: ConversationKey) -> int:
    """A stable signed 64-bit advisory-lock id for one conversation."""
    digest = hashlib.blake2b(f"{key.channel}\0{key.ref}".encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


class SqlRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @classmethod
    def from_url(cls, database_url: str) -> "SqlRepository":
        return cls(create_engine(database_url, pool_pre_ping=True))

    @contextmanager
    def unit_of_work(self, lock: ConversationKey | None = None) -> Iterator[SqlUnitOfWork]:
        """Commit on success, roll back on exception; the lock lasts until the transaction ends."""
        with self._engine.begin() as connection:
            if lock is not None:
                connection.execute(select(func.pg_advisory_xact_lock(lock_id(lock))))
            yield SqlUnitOfWork(connection)
