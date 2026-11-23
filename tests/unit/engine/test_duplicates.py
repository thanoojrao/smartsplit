"""find_likely_duplicate (SPEC 10.4, C11)."""

from datetime import date

from smartsplit.domain.values import GroupContext, PersonalContext
from smartsplit.engine import DuplicateCandidate, find_likely_duplicate

DAY = date(2026, 11, 20)
FLAT = GroupContext("flat")


def candidate(
    cid: str,
    *,
    context: GroupContext | PersonalContext = FLAT,
    total: int = 1000,
    day: date | None = DAY,
    people: frozenset[str] = frozenset({"me", "sam"}),
) -> DuplicateCandidate:
    return DuplicateCandidate(cid, False, context, total, day, people)


def test_same_group_same_total_within_three_days() -> None:
    near = candidate("b1", day=date(2026, 11, 23))

    assert find_likely_duplicate(FLAT, 1000, DAY, frozenset(), [near], window_days=3) == near


def test_different_total_group_or_far_in_time_is_not_a_duplicate() -> None:
    others = [
        candidate("t", total=999),
        candidate("g", context=GroupContext("goa")),
        candidate("d", day=date(2026, 11, 24)),
    ]

    assert find_likely_duplicate(FLAT, 1000, DAY, frozenset(), others, window_days=3) is None


def test_personal_splits_compare_the_people() -> None:
    mine = candidate("p1", context=PersonalContext(), people=frozenset({"me", "sam"}))
    other = candidate("p2", context=PersonalContext(), people=frozenset({"me", "raj"}))
    people = frozenset({"me", "sam"})

    assert (
        find_likely_duplicate(PersonalContext(), 1000, DAY, people, [other, mine], window_days=3)
        == mine
    )


def test_an_undated_candidate_counts_as_close() -> None:
    undated = candidate("d", day=None)

    assert find_likely_duplicate(FLAT, 1000, DAY, frozenset(), [undated], window_days=3) == undated
