"""FROZEN acceptance tests for the split engine (SPEC section 5).

Do not modify this file. If a test here looks wrong, stop and ask the user.
"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from smartsplit.domain import QuestionReason, RuleKind
from smartsplit.engine import ItemInput, Question, RuleInput, split_receipt


def item(item_id: str, name: str, cents: int, canonical: str | None = None) -> ItemInput:
    return ItemInput(id=item_id, name=name, amount_cents=cents, canonical=canonical)


def test_shared_item_rounds_with_largest_remainder_ties_by_member_order() -> None:
    result = split_receipt([item("i1", "Paper towels", 1000)], ["a", "b", "c"])

    assert result.shares == {"a": 334, "b": 333, "c": 333}
    assert result.assignments[0].member_ids == ("a", "b", "c")
    assert result.questions == ()


def test_exclude_rule_removes_member_from_that_item_only() -> None:
    result = split_receipt(
        [item("i1", "Milk", 600), item("i2", "Bread", 300)],
        ["a", "b", "raj"],
        rules=[RuleInput("raj", "milk", RuleKind.EXCLUDE)],
    )

    assert result.shares == {"a": 400, "b": 400, "raj": 100}
    assert result.assignments[0].member_ids == ("a", "b")
    assert result.assignments[1].member_ids == ("a", "b", "raj")
    assert result.questions == ()


def test_rules_match_canonical_key_when_present() -> None:
    result = split_receipt(
        [item("i1", "2% MLK GAL", 600, canonical="milk")],
        ["a", "raj"],
        rules=[RuleInput("raj", "milk", RuleKind.EXCLUDE)],
    )

    assert result.shares == {"a": 600, "raj": 0}


def test_rules_match_normalized_name_when_no_canonical() -> None:
    result = split_receipt(
        [item("i1", "  Protein   POWDER ", 4500)],
        ["a", "b"],
        rules=[RuleInput("a", "protein powder", RuleKind.ONLY)],
    )

    assert result.shares == {"a": 4500, "b": 0}
    assert result.assignments[0].member_ids == ("a",)


def test_soft_exclude_keeps_member_and_asks() -> None:
    result = split_receipt(
        [item("i1", "Chips", 300)],
        ["a", "b", "c"],
        rules=[RuleInput("b", "chips", RuleKind.SOFT_EXCLUDE)],
    )

    assert result.shares == {"a": 100, "b": 100, "c": 100}
    assert result.questions == (Question("i1", "b", QuestionReason.SOFT_RULE),)


def test_only_rules_from_several_members_share_the_item() -> None:
    result = split_receipt(
        [item("i1", "Oat milk", 500)],
        ["a", "b", "c"],
        rules=[
            RuleInput("c", "oat milk", RuleKind.ONLY),
            RuleInput("a", "oat milk", RuleKind.ONLY),
        ],
    )

    assert result.assignments[0].member_ids == ("a", "c")
    assert result.shares == {"a": 250, "b": 0, "c": 250}


def test_adjustments_are_allocated_in_proportion_to_item_subtotals() -> None:
    result = split_receipt(
        [item("i1", "Steak", 1000), item("i2", "Wine", 3000)],
        ["a", "b"],
        rules=[RuleInput("a", "steak", RuleKind.ONLY), RuleInput("b", "wine", RuleKind.ONLY)],
        adjustments_cents=400,
    )

    assert result.shares == {"a": 1100, "b": 3300}


def test_adjustments_split_equally_when_subtotals_sum_to_zero() -> None:
    result = split_receipt([], ["a", "b", "c"], adjustments_cents=100)

    assert result.shares == {"a": 34, "b": 33, "c": 33}


def test_override_beats_rules_and_suppresses_questions() -> None:
    result = split_receipt(
        [item("i1", "Chips", 300)],
        ["a", "b", "c"],
        rules=[RuleInput("b", "chips", RuleKind.SOFT_EXCLUDE)],
        overrides={"i1": ["c", "a"]},
    )

    assert result.assignments[0].member_ids == ("a", "c")
    assert result.shares == {"a": 150, "b": 0, "c": 150}
    assert result.questions == ()


def test_everyone_excluded_falls_back_to_all_and_asks() -> None:
    result = split_receipt(
        [item("i1", "Mystery item", 200)],
        ["a", "b"],
        rules=[
            RuleInput("a", "mystery item", RuleKind.EXCLUDE),
            RuleInput("b", "mystery item", RuleKind.EXCLUDE),
        ],
    )

    assert result.assignments[0].member_ids == ("a", "b")
    assert result.shares == {"a": 100, "b": 100}
    assert result.questions == (Question("i1", None, QuestionReason.NO_ELIGIBLE_MEMBERS),)


def test_discount_line_reduces_shares() -> None:
    result = split_receipt(
        [item("i1", "Rice", 1000), item("i2", "Coupon", -200)],
        ["a", "b"],
    )

    assert result.shares == {"a": 400, "b": 400}


@pytest.mark.parametrize(
    ("members", "overrides"),
    [([], None), (["a", "a"], None), (["a", "b"], {"i1": ["zed"]})],
)
def test_invalid_input_raises(members: list[str], overrides: dict[str, list[str]] | None) -> None:
    with pytest.raises(ValueError):
        split_receipt([item("i1", "X", 100)], members, overrides=overrides)


member_names = st.lists(
    st.text(alphabet="abcdefgh", min_size=1, max_size=3), min_size=1, max_size=6, unique=True
)


@given(
    members=member_names,
    amounts=st.lists(st.integers(min_value=-500, max_value=100_000), max_size=12),
    adjustments=st.integers(min_value=-1_000, max_value=10_000),
    data=st.data(),
)
def test_shares_always_sum_exactly_and_cover_every_member(
    members: list[str], amounts: list[int], adjustments: int, data: st.DataObject
) -> None:
    items = [item(f"i{n}", f"thing {n % 4}", cents) for n, cents in enumerate(amounts)]
    rules = data.draw(
        st.lists(
            st.builds(
                RuleInput,
                member_id=st.sampled_from(members),
                item_key=st.sampled_from(["thing 0", "thing 1", "thing 2", "thing 3"]),
                kind=st.sampled_from(list(RuleKind)),
            ),
            max_size=8,
        )
    )

    result = split_receipt(items, members, rules=rules, adjustments_cents=adjustments)

    assert set(result.shares) == set(members)
    assert sum(result.shares.values()) == sum(amounts) + adjustments
    assert [a.item_id for a in result.assignments] == [i.id for i in items]
    for assignment in result.assignments:
        assert assignment.member_ids
        assert list(assignment.member_ids) == [m for m in members if m in assignment.member_ids]
