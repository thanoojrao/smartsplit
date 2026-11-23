"""Showing money in chat text. Amounts stay integer cents everywhere else (SPEC section 3)."""

from smartsplit.domain.values import Cents


def format_cents(cents: Cents) -> str:
    """12345 → "123.45", -5 → "-0.05", 120000000 → "1,200,000.00" (no floats involved)."""
    sign = "-" if cents < 0 else ""
    units, rest = divmod(abs(cents), 100)
    return f"{sign}{units:,}.{rest:02d}"
