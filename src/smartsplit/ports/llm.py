"""Model-backed ports: receipt parsing and command interpretation (SPEC sections 7-8)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from smartsplit.domain.commands import Command
from smartsplit.domain.enums import ConversationKind
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


class ReceiptParser(Protocol):
    def parse(self, image: bytes, mime_type: str, currency: str) -> ParsedReceipt:
        """Read a receipt; raises ReceiptUnreadableError or LlmUnavailableError."""
        ...


@dataclass(frozen=True, slots=True)
class NameablePerson:
    """Someone the speaker can name: their nicknames plus the display name."""

    person_id: str
    names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InterpretContext:
    """What the interpreter may know about the chat; all text in it is untrusted data."""

    conversation_kind: ConversationKind
    conversation_name: str | None
    today: date
    speaker_id: str
    nameable: tuple[NameablePerson, ...]
    group_member_names: tuple[str, ...]
    group_names: tuple[str, ...]
    open_prompts: tuple[str, ...]
    draft_lines: tuple[str, ...]


class CommandInterpreter(Protocol):
    def interpret(self, text: str, context: InterpretContext) -> Command:
        """Turn chat text into exactly one command; raises LlmUnavailableError."""
        ...

    def canonicalize(self, name: str, known_keys: Sequence[str]) -> str:
        """Map a messy receipt name to an item key (a known one, or a new normalized key)."""
        ...
