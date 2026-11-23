"""match_item and discount propagation (SPEC section 6.4)."""

from smartsplit.domain.enums import MatchHow
from smartsplit.domain.model import LineItem
from smartsplit.domain.values import EqualSplit, Override, Weight, Weighted
from smartsplit.engine import Match, match_item, propagate_discount_overrides

KEYS = frozenset({"milk", "oat milk", "bread", "protein powder"})


def test_exact_match_on_the_normalized_name() -> None:
    assert match_item("  MILK ", {}, KEYS, 85) == Match("milk", MatchHow.EXACT)


def test_alias_in_this_scope_wins_over_exact() -> None:
    aliases = {"milk": "oat milk", "2% mlk gal": "milk"}

    assert match_item("Milk", aliases, KEYS, 85) == Match("oat milk", MatchHow.ALIAS)
    assert match_item("2% MLK  GAL", aliases, KEYS, 85) == Match("milk", MatchHow.ALIAS)


def test_fuzzy_match_at_or_above_the_threshold() -> None:
    assert match_item("Protein Powdr", {}, KEYS, 85) == Match("protein powder", MatchHow.FUZZY)


def test_below_the_threshold_nothing_matches() -> None:
    assert match_item("2% MLK GAL", {}, KEYS, 85) == Match(None, MatchHow.NONE)
    assert match_item("Protein Powdr", {}, KEYS, 100) == Match(None, MatchHow.NONE)


def test_no_known_keys_means_no_match() -> None:
    assert match_item("milk", {}, frozenset(), 85) == Match(None, MatchHow.NONE)


def test_fuzzy_ties_go_to_the_first_key_in_order() -> None:
    assert match_item("ab", {}, frozenset({"ac", "aa"}), 50) == Match("aa", MatchHow.FUZZY)


def line(line_id: str, discount_for: str | None = None) -> LineItem:
    return LineItem(
        line_id, 1, line_id, 1, 100, None, 1.0, None, discount_for, MatchHow.EXACT, False
    )


def test_a_linked_discount_follows_its_lines_override() -> None:
    # E11: "MILK 20% OFF" is shared by the same people as the milk.
    lines = [line("milk"), line("off", discount_for="milk"), line("coupon")]
    overrides: list[tuple[str, Override]] = [("milk", EqualSplit(("me", "sam")))]

    assert propagate_discount_overrides(lines, overrides) == (
        ("milk", EqualSplit(("me", "sam"))),
        ("off", EqualSplit(("me", "sam"))),
    )


def test_a_discount_with_its_own_override_keeps_it() -> None:
    lines = [line("milk"), line("off", discount_for="milk")]
    overrides: list[tuple[str, Override]] = [
        ("milk", Weighted((Weight("sam", 2),))),
        ("off", EqualSplit(("raj",))),
    ]

    assert propagate_discount_overrides(lines, overrides) == tuple(overrides)


def test_nothing_to_follow_leaves_overrides_alone() -> None:
    lines = [line("milk"), line("off", discount_for="milk")]

    assert propagate_discount_overrides(lines, []) == ()
