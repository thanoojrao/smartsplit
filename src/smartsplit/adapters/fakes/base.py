"""Helpers shared by the in-memory stores: the same constraint errors Postgres raises."""

from collections.abc import Container

from smartsplit.ports.errors import DuplicateKeyError, MissingReferenceError


def insert[K, V](records: dict[K, V], key: K, value: V) -> None:
    """Adding a duplicate key is a caller bug, as it is in Postgres."""
    if key in records:
        raise DuplicateKeyError(f"duplicate key {key!r}")
    records[key] = value


def replace_existing[K, V](records: dict[K, V], key: K, value: V) -> None:
    """Updating a missing record is a caller bug."""
    if key not in records:
        raise KeyError(key)
    records[key] = value


def require_reference(records: Container[str], key: str) -> None:
    """Foreign keys: the referenced person or group must exist."""
    if key not in records:
        raise MissingReferenceError(f"no record {key!r}")
