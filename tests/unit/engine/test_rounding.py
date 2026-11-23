"""round_preserving_total (SPEC section 5 rounding rule)."""

from fractions import Fraction

import pytest

from smartsplit.engine.rounding import round_preserving_total


def test_leftover_goes_to_largest_remainders_then_position() -> None:
    exact = [Fraction(10, 3), Fraction(10, 3), Fraction(10, 3)]

    assert round_preserving_total(exact) == [4, 3, 3]


def test_whole_amounts_are_unchanged() -> None:
    assert round_preserving_total([Fraction(5), Fraction(-2), Fraction(0)]) == [5, -2, 0]


def test_empty() -> None:
    assert round_preserving_total([]) == []


def test_non_integer_total_raises() -> None:
    with pytest.raises(ValueError):
        round_preserving_total([Fraction(1, 2)])
