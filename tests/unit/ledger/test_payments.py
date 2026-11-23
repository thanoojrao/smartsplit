"""allocate_payment and square_up (SPEC section 9)."""

from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from smartsplit.domain.values import Context, GroupContext
from smartsplit.ledger import (
    Allocation,
    ContextLedger,
    Transfer,
    allocate_payment,
    balances,
    overall_between,
    pair_debts,
    square_up,
)
from smartsplit.ledger.overall import owed_to
from tests.unit.ledger.builders import FLAT, PERSONAL, TRIP, bill, ledger, paid

GOA = GroupContext("goa")


def raj_owes_me() -> list[ContextLedger]:
    """Raj owes me 300 in the flat, 500 on the trip, 300 in Goa (Goa's first bill is older)."""
    return [
        ledger(FLAT, ("me", "raj"), [bill(FLAT, "me", {"raj": 300}, minutes=50)]),
        ledger(TRIP, ("me", "raj"), [bill(TRIP, "me", {"raj": 500}, minutes=60)]),
        ledger(GOA, ("me", "raj"), [bill(GOA, "me", {"raj": 300}, minutes=10)]),
        ledger(PERSONAL, ("me", "raj"), [bill(PERSONAL, "raj", {"me": 40})]),
    ]


def test_a_named_context_takes_the_whole_payment() -> None:
    # Said in the flat's chat (or "for the flat"): all of it counts there.
    allocations, overpaid = allocate_payment("raj", "me", 400, raj_owes_me(), named=FLAT)

    assert allocations == (Allocation(FLAT, 400),)
    assert overpaid == 100


def test_otherwise_largest_debt_first_then_oldest_bill() -> None:
    allocations, overpaid = allocate_payment("raj", "me", 900, raj_owes_me(), named=None)

    assert allocations == (Allocation(TRIP, 500), Allocation(GOA, 300), Allocation(FLAT, 100))
    assert overpaid == 0


def test_a_small_payment_only_touches_the_largest_debt() -> None:
    allocations, overpaid = allocate_payment("raj", "me", 400, raj_owes_me(), named=None)

    assert allocations == (Allocation(TRIP, 400),)
    assert overpaid == 0


def test_a_deleted_bill_does_not_count_as_the_oldest() -> None:
    # Goa's oldest bill was deleted (reversed), so the flat's bill is the oldest left.
    old = bill(GOA, "me", {"raj": 300}, minutes=1)
    contexts = [
        ledger(FLAT, ("me", "raj"), [bill(FLAT, "me", {"raj": 300}, minutes=50)]),
        ledger(
            GOA,
            ("me", "raj"),
            [
                old,
                bill(GOA, "me", {"raj": -300}, minutes=2, reverses=old.id),
                bill(GOA, "me", {"raj": 300}, minutes=60),
            ],
        ),
    ]

    allocations, _ = allocate_payment("raj", "me", 300, contexts, named=None)

    assert allocations == (Allocation(FLAT, 300),)


def test_beyond_what_is_owed_goes_to_personal_splits() -> None:
    # Raj's personal 40 is *owed to* him, so it isn't a debt to pay off.
    allocations, overpaid = allocate_payment("raj", "me", 1200, raj_owes_me(), named=None)

    assert allocations[-1] == Allocation(PERSONAL, 100)
    assert sum(a.amount_cents for a in allocations) == 1200
    assert overpaid == 100


def test_an_overpayment_adds_to_a_personal_debt_being_paid() -> None:
    contexts = [ledger(PERSONAL, ("me", "raj"), [bill(PERSONAL, "me", {"raj": 100})])]

    allocations, overpaid = allocate_payment("raj", "me", 150, contexts, named=None)

    assert allocations == (Allocation(PERSONAL, 150),)
    assert overpaid == 50


def test_a_named_context_with_no_bills_is_all_overpayment() -> None:
    assert allocate_payment("raj", "me", 50, [], named=FLAT) == ((Allocation(FLAT, 50),), 50)


def test_a_payment_must_be_positive() -> None:
    with pytest.raises(ValueError):
        allocate_payment("raj", "me", 0, raj_owes_me(), named=None)


def apply(
    ledgers: list[ContextLedger], rows: tuple[tuple[Context, Transfer], ...]
) -> list[ContextLedger]:
    out = []
    for led in ledgers:
        extra = [paid(c, t.from_id, t.to_id, t.amount_cents) for c, t in rows if c == led.context]
        out.append(replace(led, settlements=led.settlements + tuple(extra)))
    return out


def test_square_up_clears_every_group_and_moves_the_net_to_personal_splits() -> None:
    # P13: owe Sam 800 on the trip, Sam owes me 800 in the flat.
    contexts = [
        ledger(TRIP, ("me", "sam"), [bill(TRIP, "sam", {"me": 800})]),
        ledger(FLAT, ("me", "sam"), [bill(FLAT, "me", {"sam": 800})]),
        ledger(PERSONAL, ("me", "sam"), [bill(PERSONAL, "me", {"sam": 50})]),
    ]

    rows = square_up("me", "sam", contexts)

    assert rows == ((TRIP, Transfer("me", "sam", 800)), (FLAT, Transfer("sam", "me", 800)))
    after = apply(contexts, rows)
    assert pair_debts(after[0]) == pair_debts(after[1]) == ()
    assert pair_debts(after[2]) == (Transfer("sam", "me", 50),)


def test_square_up_puts_an_uneven_net_into_personal_splits() -> None:
    contexts = [
        ledger(TRIP, ("me", "sam"), [bill(TRIP, "sam", {"me": 800})]),
        ledger(FLAT, ("me", "sam"), [bill(FLAT, "me", {"sam": 300})]),
    ]

    rows = square_up("me", "sam", contexts)

    assert rows[-1] == (PERSONAL, Transfer("sam", "me", 500))
    personal = apply([ledger(PERSONAL, ("me", "sam"), [])], rows)[0]
    assert pair_debts(personal) == (Transfer("me", "sam", 500),)


def test_nothing_to_square_up() -> None:
    assert square_up("me", "raj", [ledger(FLAT, ("me", "raj"), [])]) == ()


group_people = st.sampled_from(["a", "b", "c", "d", "e"])
group_bills = st.lists(
    st.tuples(group_people, st.dictionaries(group_people, st.integers(1, 10_000), min_size=1)),
    min_size=1,
    max_size=6,
)


def total_money(person: str, ledgers: list[ContextLedger]) -> int:
    return sum(s.cents for led in ledgers for s in balances(led) if s.person_id == person)


@given(
    groups=st.lists(group_bills, min_size=1, max_size=3),
    personal=st.lists(st.tuples(st.sampled_from(["a", "b"]), st.integers(1, 10_000)), max_size=3),
)
def test_after_square_up_only_personal_splits_show_anything_between_the_two(
    groups: list[list[tuple[str, dict[str, int]]]], personal: list[tuple[str, int]]
) -> None:
    contexts = [
        ledger(
            GroupContext(f"g{n}"),
            ("a", "b", "c", "d", "e"),
            [bill(GroupContext(f"g{n}"), p, s) for p, s in bills],
        )
        for n, bills in enumerate(groups)
    ]
    other = {"a": "b", "b": "a"}
    contexts.append(
        ledger(PERSONAL, ("a", "b"), [bill(PERSONAL, p, {other[p]: c}) for p, c in personal])
    )

    rows = square_up("a", "b", contexts)
    after = apply(contexts, rows)

    for led in after[:-1]:
        assert owed_to("a", pair_debts(led)).get("b", 0) == 0
    assert {c for c, _ in overall_between("a", "b", after).breakdown} <= {PERSONAL}
    # No money changes hands: everyone's real position across contexts is unchanged.
    for person in ("a", "b", "c", "d", "e"):
        assert total_money(person, after) == total_money(person, contexts)
    assert all(t.amount_cents > 0 for _, t in rows)


def test_square_up_keeps_settling_when_the_greedy_plan_reshuffles() -> None:
    # CONTRACTS 3: greedy can't guarantee that paying a shown amount clears that pair. Here the
    # plan shows e→c 1; after paying it, re-simplifying shows e→c 1 again. Square-up iterates.
    group = ledger(
        FLAT,
        ("a", "b", "c", "d", "e"),
        [bill(FLAT, "a", {"e": 2, "a": 1, "b": 2}), bill(FLAT, "c", {"d": 2, "a": 1, "b": 1})],
    )
    shown = Transfer("e", "c", 1)
    assert shown in pair_debts(group)
    once = apply([group], ((FLAT, shown),))[0]
    assert shown in pair_debts(once)

    rows = square_up("e", "c", [group])

    after = apply([group], rows)[0]
    assert owed_to("c", pair_debts(after)).get("e", 0) == 0
    assert rows[0] == (FLAT, Transfer("e", "c", 2))
