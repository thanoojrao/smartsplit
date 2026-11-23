"""Money in chat text."""

import pytest

from smartsplit.domain.money import format_cents


@pytest.mark.parametrize(
    ("cents", "text"),
    [(0, "0.00"), (5, "0.05"), (12345, "123.45"), (-5, "-0.05"), (120_000_000, "1,200,000.00")],
)
def test_format_cents(cents: int, text: str) -> None:
    assert format_cents(cents) == text
