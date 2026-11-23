"""fold_item_tax (SPEC section 5.1)."""

from hypothesis import given
from hypothesis import strategies as st

from smartsplit.engine import ItemInput, TaxedLine, fold_item_tax, split_receipt


def line(item_id: str, cents: int, taxed: bool | None) -> TaxedLine:
    return TaxedLine(ItemInput(id=item_id, name=item_id, amount_cents=cents), taxed)


def amounts(items: list[ItemInput]) -> list[int]:
    return [i.amount_cents for i in items]


def test_tax_goes_only_on_taxed_lines_in_proportion() -> None:
    items, left = fold_item_tax(
        [line("wine", 3000, True), line("bread", 500, False), line("beer", 1000, True)], 400
    )

    assert amounts(items) == [3300, 500, 1100]
    assert left == 0


def test_no_taxed_lines_leaves_all_tax_over() -> None:
    lines = [line("a", 1000, None), line("b", 500, False)]

    items, left = fold_item_tax(lines, 250)

    assert items == [ln.item for ln in lines]
    assert left == 250


def test_negative_taxed_lines_count_as_zero() -> None:
    items, left = fold_item_tax([line("a", 1000, True), line("disc", -999, True)], 100)

    assert amounts(items) == [1100, -999]
    assert left == 0


def test_only_negative_taxed_lines_leave_tax_over() -> None:
    items, left = fold_item_tax([line("disc", -300, True), line("b", 500, None)], 50)

    assert amounts(items) == [-300, 500]
    assert left == 50


def test_rounding_ties_go_by_line_order() -> None:
    items, _ = fold_item_tax(
        [line("a", 100, True), line("b", 100, True), line("c", 100, True)], 100
    )

    assert amounts(items) == [134, 133, 133]


def test_keeps_ids_names_and_canonical() -> None:
    original = ItemInput(id="i1", name="2% MLK", amount_cents=100, canonical="milk")

    items, _ = fold_item_tax([TaxedLine(original, True)], 18)

    assert items == [ItemInput(id="i1", name="2% MLK", amount_cents=118, canonical="milk")]


def test_folded_tax_stays_on_the_people_who_had_taxed_lines() -> None:
    # E13: Raj only had untaxed bread, so none of the wine tax reaches him.
    items, left = fold_item_tax([line("wine", 3000, True), line("bread", 600, False)], 300)

    result = split_receipt(
        items, ["sam", "raj"], adjustments_cents=left, overrides={"wine": ["sam"]}
    )

    assert result.shares == {"sam": 3600, "raj": 300}


@given(
    cents=st.lists(st.integers(min_value=-1000, max_value=10**8), max_size=10),
    taxed=st.lists(st.sampled_from([True, False, None]), min_size=10, max_size=10),
    tax=st.integers(min_value=-1000, max_value=10**6),
)
def test_tax_is_never_lost(cents: list[int], taxed: list[bool | None], tax: int) -> None:
    lines = [line(f"i{n}", c, t) for n, (c, t) in enumerate(zip(cents, taxed, strict=False))]

    items, left = fold_item_tax(lines, tax)

    assert sum(amounts(items)) + left == sum(cents) + tax
    assert [i.id for i in items] == [ln.item.id for ln in lines]
