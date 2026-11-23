"""balances, simplify_debts, pair_debts (SPEC section 9)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from smartsplit.domain.values import Share
from smartsplit.ledger import Transfer, balances, pair_debts, simplify_debts
from tests.unit.ledger.builders import FLAT, PERSONAL, bill, ledger, paid

ABC = ("a", "b", "c")


def as_dict(shares: tuple[Share, ...]) -> dict[str, int]:
    return {s.person_id: s.cents for s in shares}


def test_balance_is_paid_minus_shares_plus_settlements() -> None:
    flat = ledger(
        FLAT, ABC, [bill(FLAT, "a", {"a": 300, "b": 300, "c": 300})], [paid(FLAT, "b", "a", 300)]
    )

    assert as_dict(balances(flat)) == {"a": 300, "b": 0, "c": -300}


def test_a_reversing_bill_cancels_the_original() -> None:
    original = bill(FLAT, "a", {"a": 500, "b": 500})
    reversal = bill(FLAT, "a", {"a": -500, "b": -500}, reverses=original.id)

    assert as_dict(balances(ledger(FLAT, ("a", "b"), [original, reversal]))) == {"a": 0, "b": 0}


def test_everyone_in_member_order_then_others_by_id() -> None:
    # A leaver keeps their place; someone outside the order (e.g. data from before) goes last.
    flat = ledger(FLAT, ("c", "a"), [bill(FLAT, "z", {"y": 100, "a": 100})])

    assert [s.person_id for s in balances(flat)] == ["c", "a", "y", "z"]


people = st.sampled_from(["a", "b", "c", "d", "e"])
shares_st = st.dictionaries(people, st.integers(-10_000, 10**9), min_size=1)


@given(
    bills=st.lists(st.tuples(people, shares_st), max_size=8),
    settlements=st.lists(st.tuples(people, people, st.integers(-10_000, 10**9)), max_size=5),
)
def test_balances_always_sum_to_zero(
    bills: list[tuple[str, dict[str, int]]], settlements: list[tuple[str, str, int]]
) -> None:
    originals = [bill(FLAT, payer, shares) for payer, shares in bills]
    reversals = [
        bill(FLAT, b.payer_id, {s.person_id: -s.cents for s in b.shares}, reverses=b.id)
        for b in originals[::2]
    ]
    flat = ledger(
        FLAT, ABC, originals + reversals, [paid(FLAT, f, t, c) for f, t, c in settlements]
    )

    assert sum(s.cents for s in balances(flat)) == 0


def test_greedy_largest_debtor_pays_largest_creditor() -> None:
    plan = simplify_debts(
        [Share("a", 600), Share("b", 400), Share("c", -400), Share("d", -300), Share("e", -300)],
        ["a", "b", "c", "d", "e"],
    )

    # Greedy, not minimal: 4 transfers where 3 would do (DECISIONS: S15).
    assert plan == (
        Transfer("c", "a", 400),
        Transfer("d", "b", 300),
        Transfer("e", "a", 200),
        Transfer("e", "b", 100),
    )


def test_ties_go_by_member_order() -> None:
    plan = simplify_debts([Share("x", -100), Share("b", 50), Share("a", 50)], ["b", "a", "x"])

    assert plan == (Transfer("x", "b", 50), Transfer("x", "a", 50))


def test_unbalanced_input_is_refused() -> None:
    with pytest.raises(ValueError):
        simplify_debts([Share("a", 1)], ["a"])


@given(st.lists(st.integers(-(10**9), 10**9), min_size=1, max_size=8))
def test_a_plan_settles_everyone_with_few_positive_transfers(amounts: list[int]) -> None:
    order = [f"p{n}" for n in range(len(amounts) + 1)]
    shares = [Share(p, c) for p, c in zip(order, amounts, strict=False)]
    shares.append(Share(order[-1], -sum(amounts)))

    plan = simplify_debts(shares, order)

    left = {s.person_id: s.cents for s in shares}
    for t in plan:
        assert t.amount_cents > 0
        left[t.from_id] += t.amount_cents
        left[t.to_id] -= t.amount_cents
    assert set(left.values()) <= {0}
    assert len(plan) < len(shares)  # each transfer settles at least one person


def test_a_group_shows_its_simplified_plan() -> None:
    flat = ledger(
        FLAT,
        ABC,
        [bill(FLAT, "a", {"b": 100}), bill(FLAT, "b", {"c": 100})],
    )

    assert pair_debts(flat) == (Transfer("c", "a", 100),)


def test_personal_splits_are_raw_pairs_net_of_settlements() -> None:
    # Not simplified across people: c owes b and b owes a stay two debts.
    personal = ledger(
        PERSONAL,
        ABC,
        [
            bill(PERSONAL, "a", {"a": 300, "b": 300}),
            bill(PERSONAL, "b", {"b": 100, "c": 100}),
            bill(PERSONAL, "b", {"a": 50, "b": 50}),
        ],
        [paid(PERSONAL, "b", "a", 100)],
    )

    assert pair_debts(personal) == (Transfer("b", "a", 150), Transfer("c", "b", 100))


def test_personal_pairs_that_net_to_zero_disappear() -> None:
    personal = ledger(
        PERSONAL,
        ("a", "b"),
        [bill(PERSONAL, "a", {"b": 100})],
        [paid(PERSONAL, "b", "a", 100)],
    )

    assert pair_debts(personal) == ()
