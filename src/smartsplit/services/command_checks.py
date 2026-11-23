"""Checks on interpreted commands before anything acts on them (SPEC sections 8 and 12.3)."""

import dataclasses

from smartsplit.domain.commands import Command
from smartsplit.domain.money import format_cents

_MONEY_FIELDS = frozenset({"amount", "cents"})


class InvalidAmountError(ValueError):
    """An amount in a command isn't positive cents below the install's maximum."""


def check_amounts(command: Command, max_amount_cents: int) -> Command:
    """Every amount in the command (also inside edits and exact amounts) must be > 0 and below
    `SMARTSPLIT_MAX_AMOUNT_CENTS`; model output is only a proposal (SPEC 12.3)."""
    for value in _money_values(command):
        if not 0 < value < max_amount_cents:
            raise InvalidAmountError(
                f"Amounts must be more than 0 and less than {format_cents(max_amount_cents)}."
            )
    return command


def _money_values(value: object) -> list[int]:
    found: list[int] = []
    if isinstance(value, tuple):
        for item in value:
            found += _money_values(item)
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        for field in dataclasses.fields(value):
            inner = getattr(value, field.name)
            if field.name in _MONEY_FIELDS and isinstance(inner, int):
                found.append(inner)
            else:
                found += _money_values(inner)
    return found
