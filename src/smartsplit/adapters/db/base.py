"""Helpers shared by the Postgres stores."""

from typing import Any

from sqlalchemy import Connection, CursorResult, Executable
from sqlalchemy.exc import IntegrityError

from smartsplit.ports.errors import (
    ConstraintViolationError,
    DuplicateKeyError,
    InvalidRecordError,
    MissingReferenceError,
)

_BY_SQLSTATE: dict[str, type[ConstraintViolationError]] = {
    "23505": DuplicateKeyError,
    "23503": MissingReferenceError,
    "23514": InvalidRecordError,
}


def port_error(error: IntegrityError) -> ConstraintViolationError | None:
    """The port's constraint error for a Postgres integrity error, by SQLSTATE."""
    kind = _BY_SQLSTATE.get(getattr(error.orig, "sqlstate", None) or "")
    return kind(str(error.orig)) if kind else None


class Store:
    """A store works inside the unit of work's connection (one transaction)."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def _execute(self, statement: Executable) -> CursorResult[Any]:
        """Run one statement, raising the port's constraint errors at the call, like the fake."""
        try:
            return self._connection.execute(statement)
        except IntegrityError as error:
            translated = port_error(error)
            if translated is None:
                raise
            raise translated from error


def require_one(rowcount: int) -> None:
    """An update of a missing record is a caller bug."""
    if rowcount != 1:
        raise KeyError("record not found")
