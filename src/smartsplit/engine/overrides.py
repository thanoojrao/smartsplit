"""Linked discount lines follow the line they reduce (SPEC section 6.4)."""

from collections.abc import Sequence

from smartsplit.domain.model import LineItem
from smartsplit.domain.values import Override


def propagate_discount_overrides(
    lines: Sequence[LineItem], overrides: Sequence[tuple[str, Override]]
) -> tuple[tuple[str, Override], ...]:
    """Give each linked discount line its parent's override, unless it has its own.

    So "Raj had none of the milk" also keeps Raj out of "MILK 20% OFF". Existing overrides come
    first, unchanged; inherited ones follow in line order.
    """
    by_line = dict(overrides)
    inherited = [
        (line.id, by_line[line.discount_for])
        for line in lines
        if line.discount_for is not None and line.id not in by_line and line.discount_for in by_line
    ]
    return (*overrides, *inherited)
