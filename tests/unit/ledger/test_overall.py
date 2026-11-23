"""Overall balances across contexts (SPEC section 9, use case B6)."""

from smartsplit.ledger import ContextLedger, OverallBalance, overall_between, overall_for
from tests.unit.ledger.builders import FLAT, PERSONAL, TRIP, bill, ledger


def my_contexts() -> list[ContextLedger]:
    """ "You owe Sam 50: Trip you owe 80, Flat 4B he owes 20, personal he owes 10"."""
    return [
        ledger(TRIP, ("me", "sam", "raj"), [bill(TRIP, "sam", {"me": 80, "sam": 80})]),
        ledger(FLAT, ("me", "sam"), [bill(FLAT, "me", {"me": 20, "sam": 20})]),
        ledger(
            PERSONAL,
            ("me", "priya", "sam"),
            [bill(PERSONAL, "me", {"me": 10, "sam": 10}), bill(PERSONAL, "priya", {"me": 30})],
        ),
    ]


def test_overall_between_two_people_with_a_breakdown() -> None:
    assert overall_between("me", "sam", my_contexts()) == OverallBalance(
        "sam", -50, ((TRIP, -80), (FLAT, 20), (PERSONAL, 10))
    )


def test_overall_with_someone_i_have_nothing_with() -> None:
    assert overall_between("me", "raj", my_contexts()) == OverallBalance("raj", 0, ())


def test_overall_for_lists_everyone_i_have_anything_open_with() -> None:
    assert overall_for("me", my_contexts()) == (
        OverallBalance("priya", -30, ((PERSONAL, -30),)),
        OverallBalance("sam", -50, ((TRIP, -80), (FLAT, 20), (PERSONAL, 10))),
    )


def test_a_zero_net_is_still_listed_when_contexts_are_open() -> None:
    # P13: owe Sam 30 on the trip, he owes me 30 in the flat: even overall, both still open.
    contexts = [
        ledger(TRIP, ("me", "sam"), [bill(TRIP, "sam", {"me": 30})]),
        ledger(FLAT, ("me", "sam"), [bill(FLAT, "me", {"sam": 30})]),
    ]

    assert overall_for("me", contexts) == (OverallBalance("sam", 0, ((TRIP, -30), (FLAT, 30))),)
