"""Transactions, the conversation lock and the migration (SPEC section 12.2)."""

import threading
import time
from dataclasses import replace
from datetime import date, timedelta

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, create_engine, inspect, select, text
from sqlalchemy.exc import SQLAlchemyError

from smartsplit.adapters.db.migrate import alembic_config
from smartsplit.adapters.db.repository import SqlRepository, connect, lock_id
from smartsplit.adapters.db.tables import metadata
from smartsplit.adapters.fakes.repository import InMemoryRepository
from smartsplit.domain.enums import ConversationKind
from smartsplit.domain.model import Conversation
from smartsplit.domain.values import ConversationKey
from smartsplit.ports.errors import ChatBusyError, InvalidRecordError, StorageUnavailableError
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
        assert worker.is_alive()  # blocked on the lock, not merely slow
        order.append("first")
    worker.join()

    assert order == ["first", "second"]


@pytest.mark.db
def test_migrations_downgrade_and_upgrade_cleanly(pg_url: str, clean_pg: Engine) -> None:
    config = alembic_config(pg_url)
    command.downgrade(config, "base")
    with clean_pg.connect() as connection:
        assert "people" not in inspect(connection).get_table_names()
    command.upgrade(config, "head")
    with clean_pg.connect() as connection:
        assert "people" in inspect(connection).get_table_names()


@pytest.mark.db
def test_the_partial_unique_indexes_exist(clean_pg: Engine) -> None:
    with clean_pg.connect() as connection:
        rows = connection.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = 'public'")
        )
        defs: dict[str, str] = {row.indexname: row.indexdef for row in rows}
    assert "UNIQUE" in defs["one_current_membership"]
    assert "WHERE (left_at IS NULL)" in defs["one_current_membership"]
    active = defs["one_active_draft_per_adder"]
    assert "UNIQUE" in active and "added_by" in active
    for state in ("awaiting_people", "reviewing"):
        assert state in active
    assert "queued" not in active and "parsing" not in active
    assert "WHERE (sent_at IS NULL)" in defs["notifications_unsent"]


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


@pytest.mark.parametrize(("group_id", "person_id"), [("g1", "sam"), (None, None)])
def test_a_conversation_belongs_to_a_group_or_a_person(
    repo: Repository, group_id: str | None, person_id: str | None
) -> None:
    chat = Conversation(CHAT, ConversationKind.GROUP, "Flat 4B", group_id, person_id)
    with pytest.raises(InvalidRecordError), repo.unit_of_work() as uow:
        uow.conversations.add(chat)


def test_the_fake_refuses_nested_units_of_work() -> None:
    repo = InMemoryRepository()
    with pytest.raises(RuntimeError), repo.unit_of_work(), repo.unit_of_work():
        pass


@pytest.mark.db
def test_a_busy_chat_is_refused_after_the_lock_wait_or_at_once(clean_pg: Engine) -> None:
    # SPEC 12.2: a bounded wait (then 503), and tick's try-lock never waits
    repo = SqlRepository(clean_pg)
    with repo.unit_of_work(lock=CHAT):
        started = time.monotonic()
        with pytest.raises(ChatBusyError), repo.unit_of_work(lock=CHAT, lock_wait_seconds=0.2):
            pass
        assert 0.15 < time.monotonic() - started < 2
        with pytest.raises(ChatBusyError), repo.unit_of_work(lock=CHAT, try_lock=True):
            pass
        with repo.unit_of_work(lock=ConversationKey("cli", "elsewhere"), try_lock=True) as uow:
            uow.people.add(person("sam"))
    with repo.unit_of_work(lock=CHAT, lock_wait_seconds=0.2) as uow:
        assert uow.people.get("sam") is not None


@pytest.mark.db
def test_ready_when_the_database_answers_and_is_migrated(pg_url: str, clean_pg: Engine) -> None:
    # SPEC 11: /readyz
    assert SqlRepository(clean_pg).ready()
    command.downgrade(alembic_config(pg_url), "-1")
    assert not SqlRepository(clean_pg).ready()
    command.upgrade(alembic_config(pg_url), "head")
    gone = create_engine("postgresql+psycopg://nobody@127.0.0.1:1/none")
    assert not SqlRepository(gone).ready()
    gone.dispose()


@pytest.mark.db
def test_turns_holding_every_pooled_connection_can_still_count_usage(
    pg_url: str, clean_pg: Engine
) -> None:
    # SPEC 12.2, 12.5: each turn holds a connection and counts its model calls on another
    repo = connect(pg_url)
    turns = 15  # the main pool's size plus its overflow
    everyone_in = threading.Barrier(turns, timeout=10)
    counted: list[int] = []

    def turn(number: int) -> None:
        with repo.unit_of_work(lock=ConversationKey("cli", f"chat-{number}")):
            everyone_in.wait()
            counted.append(repo.count_usage("install", date(2026, 11, 24)))

    workers = [threading.Thread(target=turn, args=(n,)) for n in range(turns)]
    started = time.monotonic()
    try:
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
    finally:
        repo.dispose()
    assert sorted(counted) == list(range(1, turns + 1))
    assert time.monotonic() - started < 10


@pytest.mark.db
def test_a_failed_statement_doesnt_carry_its_parameters(pg_url: str, clean_pg: Engine) -> None:
    # SPEC 12.4: errors get logged, and parameters hold message text and phone numbers
    repo = connect(pg_url)
    try:
        with pytest.raises(SQLAlchemyError) as raised, repo.unit_of_work() as uow:
            uow.people.add(replace(person("sam"), display_name="Sam\0 +919876500002"))
    finally:
        repo.dispose()
    assert "+919876500002" not in str(raised.value)


@pytest.mark.db
def test_no_free_connection_is_a_port_error(pg_url: str, clean_pg: Engine) -> None:
    # SPEC 12.2: the orchestrator answers "try again" instead of failing the request
    engine = create_engine(pg_url, pool_size=1, max_overflow=0, pool_timeout=0.1)
    repo = SqlRepository(engine)
    try:
        with repo.unit_of_work(), pytest.raises(StorageUnavailableError):
            repo.count_usage("install", date(2026, 11, 24))
    finally:
        engine.dispose()
