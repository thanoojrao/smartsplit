"""resolve_rules (SPEC section 6.3)."""

from datetime import UTC, datetime, timedelta

from smartsplit.domain.enums import RuleKind, RuleSource
from smartsplit.domain.model import Rule
from smartsplit.domain.values import (
    Context,
    Everywhere,
    GroupContext,
    GroupScope,
    NotesScope,
    PersonalContext,
    RuleScope,
)
from smartsplit.engine import RuleInput, resolve_rules

T0 = datetime(2026, 11, 1, tzinfo=UTC)
FLAT = GroupContext("flat")


def rule(
    rule_id: str,
    scope: RuleScope,
    kind: RuleKind = RuleKind.EXCLUDE,
    *,
    subject: str = "raj",
    key: str = "milk",
    source: RuleSource = RuleSource.STATED,
    minutes: int = 0,
) -> Rule:
    created = T0 + timedelta(minutes=minutes)
    return Rule(rule_id, subject, key, kind, scope, "someone", source, created)


def chosen(rules: list[Rule], context: Context = FLAT, added_by: str = "me") -> list[str]:
    return [r.rule.id for r in resolve_rules(rules, ["me", "sam", "raj"], context, added_by)]


def test_group_bill_uses_everywhere_rules_and_this_groups_rules_only() -> None:
    rules = [
        rule("every", Everywhere(), key="beer"),
        rule("flat", GroupScope("flat"), key="milk"),
        rule("goa", GroupScope("goa"), key="chips"),
        rule("notes", NotesScope("me"), key="cake"),
    ]

    assert chosen(rules) == ["every", "flat"]


def test_personal_split_uses_the_adders_notes_only() -> None:
    # F8: when Sam adds a personal split, my notes about Raj don't apply; Sam's do.
    rules = [
        rule("mine", NotesScope("me"), key="dessert"),
        rule("sams", NotesScope("sam"), key="chips"),
        rule("flat", GroupScope("flat"), key="milk"),
    ]

    assert chosen(rules, PersonalContext(), added_by="me") == ["mine"]
    assert chosen(rules, PersonalContext(), added_by="sam") == ["sams"]


def test_group_rule_beats_everywhere_rule() -> None:
    # F7
    rules = [
        rule("every", Everywhere(), RuleKind.EXCLUDE, minutes=5),
        rule("flat", GroupScope("flat"), RuleKind.SOFT_EXCLUDE, minutes=0),
    ]

    (resolved,) = resolve_rules(rules, ["raj"], FLAT, "me")
    assert resolved.input == RuleInput("raj", "milk", RuleKind.SOFT_EXCLUDE)
    assert resolved.rule.id == "flat"


def test_notes_beat_everywhere_in_personal_splits() -> None:
    rules = [rule("every", Everywhere(), minutes=9), rule("note", NotesScope("me"))]

    assert chosen(rules, PersonalContext()) == ["note"]


def test_stated_beats_learned_then_newest_wins() -> None:
    learned_new = rule("learned", Everywhere(), source=RuleSource.LEARNED, minutes=9)
    stated_old = rule("stated_old", Everywhere(), minutes=1)
    stated_new = rule("stated_new", Everywhere(), minutes=2)

    assert chosen([learned_new, stated_old]) == ["stated_old"]
    assert chosen([stated_new, stated_old, learned_new]) == ["stated_new"]


def test_exact_time_ties_are_broken_by_id() -> None:
    assert chosen([rule("b", Everywhere()), rule("a", Everywhere())]) == ["b"]


def test_rules_about_people_not_in_the_bill_are_ignored() -> None:
    # B3: Raj moved out, so he isn't a participant and Flat 4B's rules about him don't apply.
    assert resolve_rules([rule("r", GroupScope("flat"))], ["me", "sam"], FLAT, "me") == ()


def test_results_are_in_participant_then_key_order() -> None:
    rules = [
        rule("raj-milk", Everywhere(), subject="raj", key="milk"),
        rule("me-wine", Everywhere(), subject="me", key="wine"),
        rule("me-beer", Everywhere(), subject="me", key="beer"),
    ]

    assert chosen(rules) == ["me-beer", "me-wine", "raj-milk"]


def test_resolved_input_carries_kind_subject_and_key() -> None:
    (resolved,) = resolve_rules(
        [rule("r", GroupScope("flat"), RuleKind.ONLY, subject="sam", key="protein powder")],
        ["sam"],
        FLAT,
        "me",
    )

    assert resolved.input == RuleInput("sam", "protein powder", RuleKind.ONLY)
