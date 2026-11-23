"""Transactions, the conversation lock and the migration (SPEC section 12.2)."""

import threading
from datetime import timedelta

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.exc import IntegrityError

from smartsplit.adapters.db.repository import SqlRepository, lock_id
from smartsplit.adapters.db.tables import metadata
from smartsplit.adapters.fakes.repository import InMemoryRepository
from smartsplit.domain.enums import ConversationKind
from smartsplit.domain.model import Conversation
from smartsplit.domain.values import ConversationKey
from smartsplit.ports.repository import Repository
from tests.repository.builders import CHAT, person


def test_committed_work_is_visible_to_the_next_unit_of_work(repo: Repository) -> None:
    with repo.unit_of_work() as uow:
        uow.people.add(person("sam"))

    with repo.unit_of_work() as uow:
        assert uow.people.get("sam") == person("sam")


def test_a_failed_unit_of_work_changes_nothing(repo: Repository) -> None:
    with pytest.raises(RuntimeError), repo.unit_of_work() as uow:
        uow.people.add(person("sam"))
        uow.items.ensure("milk")
        raise RuntimeError("boom")

    with repo.unit_of_work() as uow:
        assert uow.people.get("sam") is None
        assert uow.items.keys() == frozenset()


def test_a_locked_unit_of_work_still_commits(repo: Repository) -> None:
    with repo.unit_of_work(lock=CHAT) as uow:
        uow.people.add(person("sam"))

    with repo.unit_of_work() as uow:
        assert uow.people.get("sam") is not None


def test_lock_ids_are_stable_and_distinct() -> None:
    assert lock_id(CHAT) == lock_id(ConversationKey("cli", "flat-4b"))
    assert lock_id(CHAT) != lock_id(ConversationKey("cli", "goa"))
    assert lock_id(ConversationKey("a", "b\0c")) != lock_id(ConversationKey("a\0b", "c"))


@pytest.mark.db
def test_the_conversation_lock_is_held_until_commit(clean_pg: Engine) -> None:
    repo = SqlRepository(clean_pg)

    def try_lock(key: ConversationKey) -> bool:
        with clean_pg.connect() as other:
            got = other.execute(select(text(f"pg_try_advisory_xact_lock({lock_id(key)})")))
            return bool(got.scalar())

    with repo.unit_of_work(lock=CHAT):
        assert not try_lock(CHAT)
        assert try_lock(ConversationKey("cli", "elsewhere"))
    assert try_lock(CHAT)


@pytest.mark.db
def test_a_second_message_waits_for_the_lock(clean_pg: Engine) -> None:
    repo = SqlRepository(clean_pg)
    order: list[str] = []
    first_has_lock = threading.Event()

    def second() -> None:
        first_has_lock.wait()
        with repo.unit_of_work(lock=CHAT):
            order.append("second")

    worker = threading.Thread(target=second)
    worker.start()
    with repo.unit_of_work(lock=CHAT):
        first_has_lock.set()
        worker.join(timeout=0.3)
        order.append("first")
    worker.join()

    assert order == ["first", "second"]


@pytest.mark.db
def test_migrations_match_the_table_definitions(clean_pg: Engine) -> None:
    with clean_pg.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, metadata) == []


@pytest.mark.db
def test_times_come_back_in_utc_whatever_the_server_timezone(pg_url: str, clean_pg: Engine) -> None:
    kolkata = create_engine(pg_url, connect_args={"options": "-c timezone=Asia/Kolkata"})
    repo = SqlRepository(kolkata)
    with repo.unit_of_work() as uow:
        uow.people.add(person("sam"))

    with repo.unit_of_work() as uow:
        found = uow.people.get("sam")
    kolkata.dispose()
    assert found is not None
    assert found.created_at.utcoffset() == timedelta(0)


@pytest.mark.db
def test_a_conversation_belongs_to_a_group_or_a_person_not_both(clean_pg: Engine) -> None:
    both = Conversation(CHAT, ConversationKind.GROUP, "Flat 4B", "g1", "sam", ())
    with pytest.raises(IntegrityError), SqlRepository(clean_pg).unit_of_work() as uow:
        uow.conversations.add(both)


def test_the_fake_refuses_nested_units_of_work() -> None:
    repo = InMemoryRepository()
    with pytest.raises(RuntimeError), repo.unit_of_work(), repo.unit_of_work():
        pass
