"""Per-item tax folding (SPEC section 5.1)."""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from fractions import Fraction

from smartsplit.domain import Cents
from smartsplit.engine.rounding import round_preserving_total
from smartsplit.engine.split import ItemInput


@dataclass(frozen=True, slots=True)
class TaxedLine:
    """A receipt line plus whether the receipt says it is taxed (`None`: it doesn't say)."""

    item: ItemInput
    taxed: bool | None


def fold_item_tax(lines: Sequence[TaxedLine], tax_cents: Cents) -> tuple[list[ItemInput], Cents]:
    """Add the tax into the taxed lines' amounts, so untaxed lines carry none of it.

    Weights are the taxed lines' amounts clamped at 0, so a taxed discount can't blow up the
    spread. Returns the items and the tax left over: 0 when it was folded in, otherwise all of
    it (no taxed line with a positive amount), to be split like any other adjustment.
    """
    weights = [max(line.item.amount_cents, 0) if line.taxed else 0 for line in lines]
    weight_total = sum(weights)
    if weight_total == 0:
        return [line.item for line in lines], tax_cents
    exact = [Fraction(tax_cents * weight, weight_total) for weight in weights]
    folded = [
        replace(line.item, amount_cents=line.item.amount_cents + tax)
        for line, tax in zip(lines, round_preserving_total(exact), strict=True)
    ]
    return folded, 0
