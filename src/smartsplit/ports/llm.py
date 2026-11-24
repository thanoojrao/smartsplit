"""Model-backed ports: receipt parsing and item names (SPEC sections 6.4 and 7)."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from smartsplit.domain.values import Cents


class ReceiptUnreadableError(Exception):
    """Bad image, or invalid model output even after the retry."""


class LlmUnavailableError(Exception):
    """Timeout or API error after the retry; nothing should change."""


@dataclass(frozen=True, slots=True)
class ParsedLine:
    name: str
    quantity: int
    amount_cents: Cents
    taxed: bool | None
    confidence: float
    discount_for_index: int | None
    """Index of the line this discount reduces, if the parser could link it."""


@dataclass(frozen=True, slots=True)
class ParsedReceipt:
    merchant: str | None
    purchased_at: date | None
    lines: tuple[ParsedLine, ...]
    tax_cents: Cents
    other_adjustments_cents: Cents
    total_cents: Cents
    currency: str | None
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NotAReceipt:
    """The photo isn't a receipt (a meme, a selfie)."""


type CountCall = Callable[[], None]
"""Called just before each request to the model, a retry included, so every call counts
against the daily limits (SPEC 12.5)."""


class ReceiptParser(Protocol):
    def parse(
        self,
        image: bytes,
        mime_type: str,
        currency: str,
        timeout_seconds: float,
        count_call: CountCall,
    ) -> ParsedReceipt | NotAReceipt:
        """Read a receipt within `timeout_seconds` in all (a retry gets what is left);
        raises ReceiptUnreadableError or LlmUnavailableError."""
        ...


class Canonicalizer(Protocol):
    def canonicalize(
        self, name: str, known_keys: Sequence[str], timeout_seconds: float, count_call: CountCall
    ) -> str:
        """Map a messy receipt name to an item key: a known one, or a new key for a new item,
        within `timeout_seconds` in all.

        Raises LlmUnavailableError.
        """
        ...
