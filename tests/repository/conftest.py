"""Every repository test runs against the in-memory fake and against real Postgres.

Postgres tests use TEST_DATABASE_URL (never DATABASE_URL), refuse databases whose name doesn't
end in `_test`, and fail, never skip, when Postgres can't be reached. The schema is rebuilt from
the migrations once per session and every table is emptied before each test.
"""

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.exc import OperationalError

from smartsplit.adapters.db.migrate import upgrade_to_head
from smartsplit.adapters.db.repository import SqlRepository
from smartsplit.adapters.db.tables import metadata
from smartsplit.adapters.fakes.repository import InMemoryRepository
from smartsplit.ports.repository import Repository


@pytest.fixture(scope="session")
def pg_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail("TEST_DATABASE_URL is not set (see .env.example)")
    database = make_url(url).database or ""
    if not database.endswith("_test"):
        pytest.fail(f"refusing to run against {database!r}: the test database must end in _test")
    return url


@pytest.fixture(scope="session")
def pg_engine(pg_url: str) -> Iterator[Engine]:
    engine = create_engine(pg_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    except OperationalError as error:
        pytest.fail(f"Postgres at TEST_DATABASE_URL is unreachable: {error}")
    upgrade_to_head(pg_url)
    yield engine
    engine.dispose()


@pytest.fixture
def clean_pg(pg_engine: Engine) -> Engine:
    names = ", ".join(table.name for table in metadata.sorted_tables)
    with pg_engine.begin() as connection:
        connection.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    return pg_engine


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.db)])
def repo(request: pytest.FixtureRequest) -> Repository:
    if request.param == "memory":
        return InMemoryRepository()
    return SqlRepository(request.getfixturevalue("clean_pg"))
