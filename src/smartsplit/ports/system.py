"""Time and ids come from ports, so the core stays deterministic (SPEC section 3)."""

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """The current time, timezone-aware UTC."""
        ...


class IdGenerator(Protocol):
    def new_id(self) -> str:
        """A new unique id (UUID4 hex in production)."""
        ...
