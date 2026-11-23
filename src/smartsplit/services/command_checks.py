"""Checks on interpreted commands before anything acts on them (SPEC sections 8 and 12.3)."""

import dataclasses

from smartsplit.domain.commands import Command
from smartsplit.domain.money import format_cents

_MONEY_FIELDS = frozenset({"amount", "cents"})
_COUNT_FIELDS = frozenset({"choice", "last_n", "n"})
MAX_COUNT = 1000
"""Far above any real list number, weight or "last N bills"."""


class InvalidAmountError(ValueError):
    """An amount, weight or count in a command is out of range."""


def check_amounts(command: Command, max_amount_cents: int) -> Command:
    """Every amount in the command (also inside edits and exact amounts) must be > 0 and below
    `SMARTSPLIT_MAX_AMOUNT_CENTS`; weights, list numbers and counts must be 1 to MAX_COUNT.
    Model output is only a proposal (SPEC 12.3)."""
    for value in _values(command, _MONEY_FIELDS):
        if not 0 < value < max_amount_cents:
            raise InvalidAmountError(
                f"Amounts must be more than 0 and less than {format_cents(max_amount_cents)}."
            )
    counts = _values(command, _COUNT_FIELDS) + _weights(command)
    if any(not 1 <= value <= MAX_COUNT for value in counts):
        raise InvalidAmountError(f"Numbers and shares must be between 1 and {MAX_COUNT}.")
    return command


def _values(value: object, names: frozenset[str]) -> list[int]:
    """Every int in a field with one of `names`, anywhere inside the command."""
    found: list[int] = []
    if isinstance(value, tuple):
        for item in value:
            found += _values(item, names)
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        for field in dataclasses.fields(value):
            inner = getattr(value, field.name)
            if field.name in names and isinstance(inner, int):
                found.append(inner)
            else:
                found += _values(inner, names)
    return found


def _weights(command: Command) -> list[int]:
    """The weights of "2 for Sam, 1 for Raj" (an Edit's AssignLine)."""
    op = getattr(command, "op", None)
    return [weight for _, weight in getattr(op, "weights", ())]
