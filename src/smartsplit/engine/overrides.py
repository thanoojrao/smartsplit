"""Linked discount lines follow the line they reduce (SPEC section 6.4)."""

from collections.abc import Sequence

from smartsplit.domain.model import LineItem
from smartsplit.domain.values import Override


def discount_links(lines: Sequence[LineItem]) -> dict[str, str]:
    """Linked discount line id → the line it reduces.

    Only a negative line whose `discount_for` points at another line on this receipt that is
    not itself a linked discount counts. Everything else, including refunds with no link
    ("PROTEIN POWDER REFUND"), is an ordinary line: matched by its own name and shaped by that
    item's rules. A generic coupon that matches no rules is then shared by everyone.
    """

    def is_candidate(line: LineItem) -> bool:
        return line.discount_for is not None and line.amount_cents < 0

    by_id = {line.id: line for line in lines}
    return {
        line.id: line.discount_for
        for line in lines
        if is_candidate(line)
        and line.discount_for in by_id
        and line.discount_for != line.id
        and not is_candidate(by_id[line.discount_for])
    }


def propagate_discount_overrides(
    lines: Sequence[LineItem], overrides: Sequence[tuple[str, Override]]
) -> tuple[tuple[str, Override], ...]:
    """Give each linked discount line its parent's override, unless it has its own.

    So "Raj had none of the milk" also keeps Raj out of "MILK 20% OFF". Without an override the
    discount already shares the parent's key, and so its rules. Existing overrides come first,
    unchanged; inherited ones follow in line order.
    """
    by_line = dict(overrides)
    inherited = [
        (line_id, by_line[parent_id])
        for line_id, parent_id in discount_links(lines).items()
        if line_id not in by_line and parent_id in by_line
    ]
    return (*overrides, *inherited)
