"""Counting model calls against the daily limits, in their own transactions (SPEC 12.5).

Every call counts against the install's daily total, and against the speaker's own limit when
they addressed the bot. Counts are written at once, so a turn that rolls back still counts.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from smartsplit.domain import normalize_item_name
from smartsplit.domain.model import INSTALL_COUNTER
from smartsplit.ports.llm import Canonicalizer, LlmUnavailableError
from smartsplit.ports.repository import Repository


@dataclass(frozen=True, slots=True)
class Meter:
    repository: Repository
    day: date
    person_id: str | None
    """None: nobody is charged personally (e.g. a message the bot only checked)."""

    def count(self) -> None:
        if self.person_id is not None:
            self.repository.count_usage(self.person_id, self.day)
        self.repository.count_usage(INSTALL_COUNTER, self.day)


@dataclass(frozen=True, slots=True)
class MeteredCanonicalizer:
    """Canonicalize inside a turn: counted, and never failing it; if the model can't answer,
    the line keeps its normalized name (SPEC 8.7)."""

    inner: Canonicalizer
    meter: Meter

    def canonicalize(self, name: str, known_keys: Sequence[str]) -> str:
        self.meter.count()
        try:
            return self.inner.canonicalize(name, known_keys)
        except LlmUnavailableError:
            return normalize_item_name(name)
