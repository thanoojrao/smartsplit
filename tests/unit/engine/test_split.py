"""Unit tests for split_receipt beyond the frozen acceptance tests (SPEC section 5)."""

from collections.abc import Mapping, Sequence
from typing import cast

import pytest
from hypothesis import given
from hypothesis import strategies as st

from smartsplit.domain import QuestionReason, RuleKind
from smartsplit.engine import ItemInput, Question, RuleInput, split_receipt


def item(item_id: str, name: str, cents: int, canonical: str | None = None) -> ItemInput:
    return ItemInput(id=item_id, name=name, amount_cents=cents, canonical=canonical)


class TestWeightedOverrides:
    def test_weights_split_the_item_in_proportion(self) -> None:
        result = split_receipt(
            [item("i1", "Yogurt", 300)], ["sam", "raj", "a"], overrides={"i1": {"sam": 2, "raj": 1}}
        )

        assert result.shares == {"sam": 200, "raj": 100, "a": 0}
        assert result.assignments[0].member_ids == ("sam", "raj")

    def test_seventy_thirty(self) -> None:
        result = split_receipt(
            [item("i1", "Cab", 1000)], ["a", "b"], overrides={"i1": {"b": 30, "a": 70}}
        )

        assert result.shares == {"a": 700, "b": 300}

    def test_weighted_assignment_is_in_member_order(self) -> None:
        result = split_receipt(
            [item("i1", "X", 90)], ["a", "b", "c"], overrides={"i1": {"c": 1, "a": 2}}
        )

        assert result.assignments[0].member_ids == ("a", "c")

    def test_weighted_override_suppresses_questions(self) -> None:
        result = split_receipt(
            [item("i1", "Chips", 300)],
            ["a", "b"],
            rules=[RuleInput("b", "chips", RuleKind.SOFT_EXCLUDE)],
            overrides={"i1": {"a": 1, "b": 2}},
        )

        assert result.questions == ()
        assert result.shares == {"a": 100, "b": 200}

    def test_list_override_member_listed_twice_counts_once(self) -> None:
        result = split_receipt(
            [item("i1", "X", 300)], ["a", "b"], overrides={"i1": ["a", "a", "b"]}
        )

        assert result.shares == {"a": 150, "b": 150}
        assert result.assignments[0].member_ids == ("a", "b")


class TestRules:
    def test_rules_for_non_members_are_ignored(self) -> None:
        result = split_receipt(
            [item("i1", "Milk", 600)],
            ["a", "b"],
            rules=[
                RuleInput("gone", "milk", RuleKind.ONLY),
                RuleInput("gone", "milk", RuleKind.SOFT_EXCLUDE),
            ],
        )

        assert result.shares == {"a": 300, "b": 300}
        assert result.questions == ()

    def test_only_beats_exclude_and_soft_exclude_without_questions(self) -> None:
        result = split_receipt(
            [item("i1", "Milk", 600)],
            ["a", "b", "c"],
            rules=[
                RuleInput("a", "milk", RuleKind.ONLY),
                RuleInput("a", "milk", RuleKind.EXCLUDE),
                RuleInput("b", "milk", RuleKind.SOFT_EXCLUDE),
            ],
        )

        assert result.assignments[0].member_ids == ("a",)
        assert result.questions == ()

    def test_exclude_and_soft_exclude_together_exclude_without_question(self) -> None:
        result = split_receipt(
            [item("i1", "Chips", 300)],
            ["a", "b"],
            rules=[
                RuleInput("b", "chips", RuleKind.SOFT_EXCLUDE),
                RuleInput("b", "chips", RuleKind.EXCLUDE),
            ],
        )

        assert result.assignments[0].member_ids == ("a",)
        assert result.questions == ()

    def test_repeated_soft_rules_give_one_question(self) -> None:
        result = split_receipt(
            [item("i1", "Chips", 300)],
            ["a", "b"],
            rules=[
                RuleInput("b", "chips", RuleKind.SOFT_EXCLUDE),
                RuleInput("b", "chips", RuleKind.SOFT_EXCLUDE),
            ],
        )

        assert result.questions == (Question("i1", "b", QuestionReason.SOFT_RULE),)

    def test_questions_are_in_item_order_then_member_order(self) -> None:
        result = split_receipt(
            [item("i1", "Chips", 300), item("i2", "Beer", 600), item("i3", "Cake", 200)],
            ["a", "b", "c"],
            rules=[
                RuleInput("c", "chips", RuleKind.SOFT_EXCLUDE),
                RuleInput("a", "chips", RuleKind.SOFT_EXCLUDE),
                RuleInput("a", "beer", RuleKind.EXCLUDE),
                RuleInput("b", "beer", RuleKind.EXCLUDE),
                RuleInput("c", "beer", RuleKind.EXCLUDE),
                RuleInput("b", "cake", RuleKind.SOFT_EXCLUDE),
            ],
        )

        assert result.questions == (
            Question("i1", "a", QuestionReason.SOFT_RULE),
            Question("i1", "c", QuestionReason.SOFT_RULE),
            Question("i2", None, QuestionReason.NO_ELIGIBLE_MEMBERS),
            Question("i3", "b", QuestionReason.SOFT_RULE),
        )

    def test_canonical_key_hides_the_raw_name(self) -> None:
        result = split_receipt(
            [item("i1", "milk", 600, canonical="oat milk")],
            ["a", "raj"],
            rules=[RuleInput("raj", "milk", RuleKind.EXCLUDE)],
        )

        assert result.shares == {"a": 300, "raj": 300}


class TestAmounts:
    def test_negative_subtotal_gets_no_adjustment(self) -> None:
        # E15: Raj's only line is a refund on a shared shop; he gets the refund, no tip or tax.
        result = split_receipt(
            [item("i1", "Groceries", 3000), item("i2", "Refund", -300)],
            ["a", "raj"],
            overrides={"i1": ["a"], "i2": ["raj"]},
            adjustments_cents=300,
        )

        assert result.shares == {"a": 3300, "raj": -300}

    def test_only_discounts_split_adjustments_equally(self) -> None:
        result = split_receipt(
            [item("i1", "Refund", -500)], ["a", "b"], overrides={"i1": ["a"]}, adjustments_cents=101
        )

        assert result.shares == {"a": -449, "b": 50}

    def test_tip_weights_do_not_jump_near_zero(self) -> None:
        # P24: a +1000, b -999 → weights 1000 and 0 (b pays no tip).
        result = split_receipt(
            [item("i1", "A", 1000), item("i2", "B", -999)],
            ["a", "b"],
            overrides={"i1": ["a"], "i2": ["b"]},
            adjustments_cents=100,
        )

        assert result.shares == {"a": 1100, "b": -999}

    def test_negative_shares_round_with_floor_and_largest_remainder(self) -> None:
        result = split_receipt([item("i1", "Coupon", -1000)], ["a", "b", "c"])

        # exact -333.33 each: floors -334, leftover 2 cents to a and b by member order.
        assert result.shares == {"a": -333, "b": -333, "c": -334}

    def test_negative_adjustments(self) -> None:
        result = split_receipt(
            [item("i1", "A", 1000), item("i2", "B", 3000)],
            ["a", "b"],
            overrides={"i1": ["a"], "i2": ["b"]},
            adjustments_cents=-400,
        )

        assert result.shares == {"a": 900, "b": 2700}

    def test_rounding_uses_the_total_share_not_each_part(self) -> None:
        # Rounding each item on its own would give a 668; the exact total share is 666.67.
        result = split_receipt(
            [item("i1", "X", 1000), item("i2", "Y", 1000)],
            ["a", "b", "c"],
        )

        assert result.shares == {"a": 667, "b": 667, "c": 666}

    def test_largest_remainder_beats_member_order(self) -> None:
        result = split_receipt(
            [item("i1", "X", 10)], ["a", "b", "c"], overrides={"i1": {"a": 3, "b": 3, "c": 1}}
        )

        # exact 4.29, 4.29, 1.43 → floors 4, 4, 1; the leftover cent goes to c (largest remainder).
        assert result.shares == {"a": 4, "b": 4, "c": 2}

    def test_large_amounts_stay_exact(self) -> None:
        big = 10**15 + 7
        result = split_receipt([item("i1", "House", big)], ["a", "b", "c"], adjustments_cents=1)

        assert sum(result.shares.values()) == big + 1
        assert max(result.shares.values()) - min(result.shares.values()) <= 1

    def test_many_members(self) -> None:
        members = [f"m{n:03}" for n in range(200)]
        result = split_receipt([item("i1", "Party", 100_001)], members, adjustments_cents=1000)

        assert sum(result.shares.values()) == 101_001
        assert result.shares["m000"] == 506
        assert set(list(result.shares.values())[1:]) == {505}
        assert list(result.shares) == members

    def test_shares_are_listed_in_member_order(self) -> None:
        result = split_receipt([item("i1", "X", 10)], ["c", "a", "b"])

        assert list(result.shares) == ["c", "a", "b"]


class TestValidation:
    @pytest.mark.parametrize(
        "overrides",
        [
            {"nope": ["a"]},
            {"i1": []},
            {"i1": {}},
            {"i1": ["zed"]},
            {"i1": {"zed": 1}},
            {"i1": {"a": 0}},
            {"i1": {"a": -1}},
            {"i1": {"a": True}},
            {"i1": "a"},
        ],
    )
    def test_bad_overrides_raise(
        self, overrides: Mapping[str, Sequence[str] | Mapping[str, int]]
    ) -> None:
        with pytest.raises(ValueError):
            split_receipt([item("i1", "X", 100)], ["a", "b"], overrides=overrides)

    def test_non_integer_weight_raises(self) -> None:
        weights = cast("dict[str, int]", {"a": 1, "b": 1.5})
        with pytest.raises(ValueError):
            split_receipt([item("i1", "X", 100)], ["a", "b"], overrides={"i1": weights})

    def test_duplicate_item_ids_raise(self) -> None:
        with pytest.raises(ValueError):
            split_receipt([item("i1", "X", 100), item("i1", "Y", 200)], ["a"])


@given(
    amounts=st.lists(st.integers(min_value=-10_000, max_value=10**9), min_size=1, max_size=8),
    weights=st.lists(st.integers(min_value=1, max_value=50), min_size=1, max_size=5),
    adjustments=st.integers(min_value=-10_000, max_value=10**7),
)
def test_weighted_shares_always_sum_exactly(
    amounts: list[int], weights: list[int], adjustments: int
) -> None:
    members = [f"m{n}" for n in range(len(weights))]
    items = [item(f"i{n}", "x", cents) for n, cents in enumerate(amounts)]
    override = dict(zip(members, weights, strict=True))

    result = split_receipt(
        items, members, adjustments_cents=adjustments, overrides={"i0": override}
    )

    assert sum(result.shares.values()) == sum(amounts) + adjustments
    assert list(result.shares) == members
