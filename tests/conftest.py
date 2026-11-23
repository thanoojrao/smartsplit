"""Shared pytest setup.

Hypothesis profiles: `dev` (default) for the local loop, `ci` for slow or shared runners,
where timing deadlines would make property tests flaky. Select with HYPOTHESIS_PROFILE=ci.

Postgres fixtures: tests use TEST_DATABASE_URL (never DATABASE_URL), refuse databases whose name
doesn't end in `_test`, and fail, never skip, when Postgres can't be reached. The schema is built
from the migrations once per session and every table is emptied before each test (`clean_pg`).
"""

import os
from collections.abc import Iterator

import pytest
from hypothesis import settings
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.exc import OperationalError

from smartsplit.adapters.db.migrate import upgrade_to_head
from smartsplit.adapters.db.tables import metadata

settings.register_profile("dev", max_examples=100)
settings.register_profile("ci", max_examples=200, deadline=None, derandomize=True, print_blob=True)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))


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


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """`live` tests call the real Anthropic API, so they run only when asked (SPEC section 7)."""
    if os.environ.get("SMARTSPLIT_LIVE_LLM") == "1":
        return
    skip = pytest.mark.skip(reason="live model test; set SMARTSPLIT_LIVE_LLM=1 to run")
    for item in items:
        if item.get_closest_marker("live"):
            item.add_marker(skip)
