"""Discount lines follow the line they reduce, or are shared by everyone (SPEC section 6.4)."""

from collections.abc import Sequence

from smartsplit.domain.model import LineItem
from smartsplit.domain.values import EqualSplit, Override


def discount_links(lines: Sequence[LineItem]) -> dict[str, str | None]:
    """Discount line id → the plain line it reduces, or None if it has no usable link.

    A discount is a line with a negative amount or a `discount_for` link. A link counts only
    if it points at a plain line on this receipt (no chains), so "MILK 20% OFF" linked to the
    milk follows the milk, and anything else is shared by everyone.
    """
    by_id = {line.id: line for line in lines}
    links: dict[str, str | None] = {}
    for line in lines:
        if line.discount_for is None and line.amount_cents >= 0:
            continue
        parent = by_id.get(line.discount_for) if line.discount_for else None
        plain = parent is not None and parent.discount_for is None and parent.amount_cents >= 0
        links[line.id] = parent.id if parent and plain else None
    return links


def propagate_discount_overrides(
    lines: Sequence[LineItem],
    overrides: Sequence[tuple[str, Override]],
    participants: Sequence[str],
) -> tuple[tuple[str, Override], ...]:
    """Give each discount line without its own override the override it should follow.

    A linked discount follows its parent's override, so "Raj had none of the milk" also keeps
    Raj out of "MILK 20% OFF" (without one, it shares the parent's key and rules). An unlinked
    discount is split among all participants, so nobody's rules move it. Existing overrides
    come first, unchanged; added ones follow in line order.
    """
    by_line = dict(overrides)
    added: list[tuple[str, Override]] = []
    for line_id, parent_id in discount_links(lines).items():
        if line_id in by_line:
            continue
        if parent_id is None:
            added.append((line_id, EqualSplit(tuple(participants))))
        elif parent_id in by_line:
            added.append((line_id, by_line[parent_id]))
    return (*overrides, *added)
