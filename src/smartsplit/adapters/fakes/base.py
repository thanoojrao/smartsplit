"""Helpers shared by the in-memory stores."""


def insert[K, V](records: dict[K, V], key: K, value: V) -> None:
    """Adding a duplicate key is a caller bug, as it is in Postgres."""
    if key in records:
        raise ValueError(f"duplicate key {key!r}")
    records[key] = value


def replace_existing[K, V](records: dict[K, V], key: K, value: V) -> None:
    """Updating a missing record is a caller bug."""
    if key not in records:
        raise KeyError(key)
    records[key] = value
