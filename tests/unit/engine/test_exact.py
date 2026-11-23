"""amounts_to_weights (SPEC section 5.2)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from smartsplit.domain import Weight
from smartsplit.engine import (
    ItemInput,
    TaxedLine,
    amounts_to_weights,
    fold_item_tax,
    split_receipt,
)


def shares_for(line_cents: int, weights: tuple[Weight, ...], members: list[str]) -> dict[str, int]:
    override = {w.person_id: w.weight for w in weights}
    item = ItemInput(id="l1", name="line", amount_cents=line_cents)
    return split_receipt([item], members, overrides={"l1": override}).shares


def test_fixed_part_and_equal_rest() -> None:
    # E8: "Sam's part was 100" on a 250 line shared with Raj and Priya.
    weights = amounts_to_weights(250, [("sam", 100)], ["raj", "priya"])

    assert weights == (Weight("sam", 4), Weight("raj", 3), Weight("priya", 3))
    assert shares_for(250, weights, ["sam", "raj", "priya"]) == {
        "sam": 100,
        "raj": 75,
        "priya": 75,
    }


def test_everyone_fixed_must_add_up() -> None:
    # E9: "rent 30000: Sam 12000, me 9000, Raj 9000".
    weights = amounts_to_weights(30000, [("sam", 12000), ("me", 9000), ("raj", 9000)], [])

    assert weights == (Weight("sam", 4), Weight("me", 3), Weight("raj", 3))
    assert shares_for(30000, weights, ["me", "sam", "raj"]) == {
        "me": 9000,
        "sam": 12000,
        "raj": 9000,
    }


def test_fixed_using_the_whole_line_leaves_others_out() -> None:
    weights = amounts_to_weights(250, [("sam", 250)], ["raj"])

    assert weights == (Weight("sam", 1),)


def test_uneven_remainder_is_still_exact_for_the_fixed_person() -> None:
    weights = amounts_to_weights(1001, [("sam", 333)], ["raj", "priya", "a"])

    shares = shares_for(1001, weights, ["sam", "raj", "priya", "a"])
    assert shares["sam"] == 333
    assert sum(shares.values()) == 1001


@pytest.mark.parametrize(
    ("line_cents", "fixed", "others"),
    [
        (250, [("sam", 300)], ["raj"]),
        (250, [("sam", 100)], []),
        (250, [("sam", 0)], ["raj"]),
        (250, [("sam", -10)], ["raj"]),
        (250, [], ["raj"]),
        (250, [("sam", 100), ("sam", 50)], ["raj"]),
        (250, [("sam", 100)], ["sam"]),
        (250, [("sam", 100)], ["raj", "raj"]),
        (-100, [("sam", 100)], ["raj"]),
    ],
)
def test_amounts_that_cannot_be_honoured_raise(
    line_cents: int, fixed: list[tuple[str, int]], others: list[str]
) -> None:
    with pytest.raises(ValueError):
        amounts_to_weights(line_cents, fixed, others)


@given(
    fixed_cents=st.lists(st.integers(min_value=1, max_value=10**6), min_size=1, max_size=4),
    extra=st.integers(min_value=0, max_value=10**6),
    other_count=st.integers(min_value=1, max_value=5),
)
def test_fixed_people_always_get_exactly_their_amount(
    fixed_cents: list[int], extra: int, other_count: int
) -> None:
    fixed = [(f"f{n}", cents) for n, cents in enumerate(fixed_cents)]
    others = [f"o{n}" for n in range(other_count)]
    line_cents = sum(fixed_cents) + extra

    weights = amounts_to_weights(line_cents, fixed, others)

    shares = shares_for(line_cents, weights, [p for p, _ in fixed] + others)
    for person, cents in fixed:
        assert shares[person] == cents
    assert sum(shares.values()) == line_cents
    assert all(w.weight > 0 for w in weights)


def test_exact_amounts_are_before_tax_and_tip() -> None:
    # Checkpoint A decision: "Sam's part was 50" of a taxed 200 line, 10% tax and a 40 tip:
    # Sam pays 50 + 5 tax + 10 tip; asymmetric, so losing the override would show.
    weights = amounts_to_weights(200, [("sam", 50)], ["raj"])
    items, left = fold_item_tax([TaxedLine(ItemInput("l1", "Wine", 200), True)], 20)
    override = {w.person_id: w.weight for w in weights}

    result = split_receipt(
        items, ["sam", "raj"], adjustments_cents=left + 40, overrides={"l1": override}
    )

    assert result.shares == {"sam": 65, "raj": 195}


def test_leftover_cents_go_by_member_order_not_by_the_order_of_others() -> None:
    weights = amounts_to_weights(102, [("sam", 1)], ["raj", "priya"])

    shares = shares_for(102, weights, ["priya", "sam", "raj"])
    assert shares == {"priya": 51, "sam": 1, "raj": 50}
