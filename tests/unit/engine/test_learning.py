"""observe and learned_kind (SPEC section 6.5)."""

from datetime import UTC, datetime, timedelta

import pytest

from smartsplit.domain.enums import AnswerOutcome, RuleKind, RuleSource
from smartsplit.domain.model import AnswerObservation, Rule
from smartsplit.domain.values import GroupScope
from smartsplit.engine import learned_kind, observe

T0 = datetime(2026, 11, 1, tzinfo=UTC)
FLAT = GroupScope("flat")
EXCLUDED, SOLE, INCLUDED = (
    AnswerOutcome.EXCLUDED,
    AnswerOutcome.SOLE_ASSIGNEE,
    AnswerOutcome.INCLUDED,
)


def history(*outcomes: AnswerOutcome) -> list[AnswerObservation]:
    return [
        AnswerObservation(FLAT, "sam", "chips", outcome, f"b{n}", T0 + timedelta(days=n))
        for n, outcome in enumerate(outcomes)
    ]


def existing(kind: RuleKind, source: RuleSource) -> Rule:
    return Rule("r", "sam", "chips", kind, FLAT, "raj", source, T0)


def test_observe_outcomes() -> None:
    assert observe("sam", ["me", "raj"], weighted=False) is EXCLUDED
    assert observe("sam", ["sam"], weighted=False) is SOLE
    assert observe("sam", ["sam", "raj"], weighted=False) is INCLUDED
    assert observe("sam", ["sam"], weighted=True) is INCLUDED


def test_on_a_weighted_line_the_people_on_it_are_included_and_the_rest_excluded() -> None:
    # "2 for Sam, 1 for me": Sam and I are included, Raj (removed) is excluded.
    assert observe("sam", ["sam", "me"], weighted=True) is INCLUDED
    assert observe("raj", ["sam", "me"], weighted=True) is EXCLUDED


@pytest.mark.parametrize(
    ("outcomes", "kind"),
    [
        ((EXCLUDED, EXCLUDED), RuleKind.EXCLUDE),
        ((INCLUDED, SOLE, SOLE), RuleKind.ONLY),
        ((EXCLUDED,), None),
        ((), None),
        ((EXCLUDED, INCLUDED), None),
        ((EXCLUDED, EXCLUDED, INCLUDED), None),
        ((EXCLUDED, SOLE), None),
        ((INCLUDED, INCLUDED), None),
    ],
)
def test_two_consistent_answers_in_a_row_teach_a_rule(
    outcomes: tuple[AnswerOutcome, ...], kind: RuleKind | None
) -> None:
    # F5, F6
    assert learned_kind(history(*outcomes), None) is kind


@pytest.mark.parametrize("kind", [RuleKind.EXCLUDE, RuleKind.ONLY])
def test_stated_exclude_or_only_is_never_overridden(kind: RuleKind) -> None:
    assert learned_kind(history(SOLE, SOLE), existing(kind, RuleSource.STATED)) is None
    assert learned_kind(history(EXCLUDED, EXCLUDED), existing(kind, RuleSource.STATED)) is None


def test_stated_soft_exclude_and_learned_rules_can_be_replaced() -> None:
    soft = existing(RuleKind.SOFT_EXCLUDE, RuleSource.STATED)
    learned = existing(RuleKind.EXCLUDE, RuleSource.LEARNED)

    assert learned_kind(history(EXCLUDED, EXCLUDED), soft) is RuleKind.EXCLUDE
    assert learned_kind(history(SOLE, SOLE), learned) is RuleKind.ONLY
