"""Exact amounts for people on one line, as a weighted override (SPEC section 5.2)."""

from collections.abc import Sequence
from math import gcd

from smartsplit.domain import Cents, Weight


def amounts_to_weights(
    line_cents: Cents, fixed: Sequence[tuple[str, Cents]], others: Sequence[str]
) -> tuple[Weight, ...]:
    """Turn "Sam's part was 100" into weights that give fixed people exactly their amount.

    The rest of the line is split equally among `others`. With k others, a fixed amount `a`
    gets weight `a * k` and each other person gets the remainder, so the split engine's
    proportional split reproduces the amounts exactly; weights are then reduced by their gcd.
    If the fixed amounts use up the whole line, `others` get nothing and are left out (a weight
    must be positive). Raises ValueError when the amounts can't be honoured, so the caller asks,
    and when no fixed amounts are given (an equal split is a plain list override instead).
    The weights come fixed people first, then others; `split_receipt` puts them in member order,
    and when the rest doesn't divide evenly the leftover cents go by member order, not by the
    order of `others`. Amounts are before tax and tip: fold the tax into the line afterwards.
    """
    if not fixed:
        raise ValueError("no fixed amounts given")
    fixed_ids = [person for person, _ in fixed]
    if len(set(fixed_ids) | set(others)) != len(fixed_ids) + len(others):
        raise ValueError("each person may appear only once")
    if any(cents <= 0 for _, cents in fixed):
        raise ValueError("fixed amounts must be positive")
    remainder = line_cents - sum(cents for _, cents in fixed)
    if remainder < 0:
        raise ValueError("fixed amounts add up to more than the line")
    if remainder > 0 and not others:
        raise ValueError("fixed amounts don't add up to the line and nobody shares the rest")

    share_count = len(others) if remainder > 0 else 1
    raw = [(person, cents * share_count) for person, cents in fixed]
    if remainder > 0:
        raw += [(person, remainder) for person in others]
    divisor = gcd(*(weight for _, weight in raw))
    return tuple(Weight(person, weight // divisor) for person, weight in raw)
