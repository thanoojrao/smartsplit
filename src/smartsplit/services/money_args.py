"""Money arguments from the model: decimal strings in major units, parsed by code into cents
(SPEC 8.3). A float, a stray symbol, or more than two decimals is refused, never rounded."""

import re

from smartsplit.domain.values import Cents
from smartsplit.services.errors import NotAllowedError

_MONEY = re.compile(r"(-?)(\d+)(?:\.(\d{1,2}))?")


def parse_money(text: object, max_cents: int, *, allow_negative: bool = False) -> Cents:
    """ "800" → 80000, "12.5" → 1250; within ±`max_cents`, never 0."""
    if not isinstance(text, str):
        raise NotAllowedError('Amounts must be written as text, like "12.50".')
    match = _MONEY.fullmatch(text.strip())
    if match is None:
        raise NotAllowedError(f'"{text}" isn\'t an amount like "800" or "12.50".')
    sign, units, decimals = match.groups()
    cents = int(units) * 100 + int((decimals or "0").ljust(2, "0"))
    if sign:
        cents = -cents
    if cents == 0 or (cents < 0 and not allow_negative):
        raise NotAllowedError("The amount has to be more than 0.")
    if abs(cents) >= max_cents:
        raise NotAllowedError("That amount is too large.")
    return cents
