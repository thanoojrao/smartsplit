"""Every repository test runs against the in-memory fake and against real Postgres."""

import pytest

from smartsplit.adapters.db.repository import SqlRepository
from smartsplit.adapters.fakes.repository import InMemoryRepository
from smartsplit.ports.repository import Repository


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.db)])
def repo(request: pytest.FixtureRequest) -> Repository:
    if request.param == "memory":
        return InMemoryRepository()
    return SqlRepository(request.getfixturevalue("clean_pg"))
