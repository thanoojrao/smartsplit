"""Exact-to-cents rounding shared by the split engine and tax folding (SPEC section 5)."""

from collections.abc import Sequence
from fractions import Fraction
from math import floor


def round_preserving_total(exact: Sequence[Fraction]) -> list[int]:
    """Round exact amounts to whole cents so they still add up to their (integer) sum.

    Floors every amount, then hands the leftover cents one at a time to the largest fractional
    remainders, ties broken by position. One rule for positive and negative amounts keeps every
    split deterministic and exact.
    """
    total = sum(exact, Fraction(0))
    if total.denominator != 1:
        raise ValueError("exact amounts must add up to a whole number of cents")
    floors = [floor(amount) for amount in exact]
    leftover = int(total) - sum(floors)
    by_remainder = sorted(range(len(exact)), key=lambda i: (-(exact[i] - floors[i]), i))
    for i in by_remainder[:leftover]:
        floors[i] += 1
    return floors
