"""Deterministic clock and ids for tests and the demo."""

from datetime import datetime, timedelta


class FixedClock:
    """A clock that only moves when told to."""

    def __init__(self, now: datetime) -> None:
        if now.utcoffset() != timedelta(0):
            raise ValueError("FixedClock needs a timezone-aware UTC time")
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


class SequentialIds:
    """Ids `id0001`, `id0002`, ... so test output is readable and stable."""

    def __init__(self, prefix: str = "id") -> None:
        self._prefix = prefix
        self._count = 0

    def new_id(self) -> str:
        self._count += 1
        return f"{self._prefix}{self._count:04}"
