"""Postgres Repository: one transaction per unit of work, optional per-conversation lock."""

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

from sqlalchemy import Connection, Engine, create_engine, func, select, text
from sqlalchemy.exc import IntegrityError

from smartsplit.adapters.db import draft_stores, ledger_stores, people_stores, rule_stores
from smartsplit.adapters.db.base import port_error
from smartsplit.domain.values import ConversationKey


class SqlUnitOfWork:
    """The stores, all bound to one connection inside one transaction."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection
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
        self.photos = draft_stores.PhotoStore(connection)
        self.chat = draft_stores.ChatStore(connection)
        self.receipts = draft_stores.ReceiptStore(connection)
        self.drafts = draft_stores.DraftStore(connection)
        self.prompts = draft_stores.PromptStore(connection)
        self.processed = draft_stores.ProcessedStore(connection)
        self.bills = ledger_stores.BillStore(connection)
        self.settlements = ledger_stores.SettlementStore(connection)
        self.notifications = ledger_stores.NotificationStore(connection)

    @contextmanager
    def savepoint(self) -> Iterator[None]:
        """A Postgres SAVEPOINT, released on success and rolled back if the block raises."""
        with self._connection.begin_nested():
            yield


def lock_id(key: ConversationKey) -> int:
    """A stable signed 64-bit advisory-lock id for one conversation."""
    unambiguous = f"{len(key.channel)}:{key.channel}{key.ref}"  # no two keys share a string
    digest = hashlib.blake2b(unambiguous.encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


class SqlRepository:
    """The Repository port on Postgres; every unit of work is one transaction."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @contextmanager
    def unit_of_work(self, lock: ConversationKey | None = None) -> Iterator[SqlUnitOfWork]:
        """Commit on success, roll back on exception; the lock lasts until the transaction ends."""
        try:
            with self._engine.begin() as connection:
                connection.execute(text("SET LOCAL TIME ZONE 'UTC'"))  # times come back in UTC
                if lock is not None:
                    connection.execute(select(func.pg_advisory_xact_lock(lock_id(lock))))
                yield SqlUnitOfWork(connection)
        except IntegrityError as error:  # raised at commit; store calls translate their own
            translated = port_error(error)
            if translated is None:
                raise
            raise translated from error

    def count_usage(self, counter: str, day: date) -> int:
        """Its own connection and transaction, committed at once (SPEC 12.5)."""
        with self._engine.begin() as connection:
            return rule_stores.LlmUsageStore(connection).increment(counter, day)


def connect(database_url: str) -> SqlRepository:
    """A repository on a pooled engine; stale pooled connections are replaced transparently."""
    return SqlRepository(create_engine(database_url, pool_pre_ping=True))
