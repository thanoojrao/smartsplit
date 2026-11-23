"""Helpers shared by the Postgres stores."""

from sqlalchemy import Connection


class Store:
    """A store works inside the unit of work's connection (one transaction)."""

    def __init__(self, connection: Connection) -> None:
        self._db = connection


def require_one(rowcount: int) -> None:
    """An update of a missing record is a caller bug."""
    if rowcount != 1:
        raise KeyError("record not found")
