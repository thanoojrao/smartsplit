"""Learning from saved bills (SPEC section 6.5)."""

from datetime import UTC, datetime, timedelta

from smartsplit.adapters.fakes.repository import InMemoryRepository
from smartsplit.adapters.fakes.system import SequentialIds
from smartsplit.domain.enums import AnswerOutcome, RuleKind, RuleSource
from smartsplit.domain.model import Rule
from smartsplit.domain.values import (
    Everywhere,
    GroupContext,
    GroupScope,
    LocalScope,
    NotesScope,
)
from smartsplit.engine import ItemInput, resolve_rules, split_receipt
from smartsplit.services.learning import LineAnswer, learn_from_bill

T0 = datetime(2026, 11, 1, tzinfo=UTC)
FLAT = GroupScope("flat")


def save_bill(
    repo: InMemoryRepository,
    ids: SequentialIds,
    bill_id: str,
    answers: list[LineAnswer],
    scope: LocalScope = FLAT,
) -> tuple[Rule, ...]:
    with repo.unit_of_work() as uow:
        return learn_from_bill(
            uow,
            ids,
            scope=scope,
            bill_id=bill_id,
            added_by="me",
            answers=answers,
            now=T0 + timedelta(days=int(bill_id.removeprefix("b"))),
        )


def sam_left_out(item: str = "chips") -> LineAnswer:
    return LineAnswer("sam", item, ("me", "raj"), weighted=False)


def test_sam_excluded_on_two_bills_in_a_row_learns_a_group_rule_and_stops_asking() -> None:
    # F5
    repo, ids = InMemoryRepository(), SequentialIds("r")
    assert save_bill(repo, ids, "b1", [sam_left_out()]) == ()

    (learned,) = save_bill(repo, ids, "b2", [sam_left_out()])

    assert (learned.kind, learned.scope, learned.source) == (
        RuleKind.EXCLUDE,
        FLAT,
        RuleSource.LEARNED,
    )
    assert learned.author_id == "me"
    with repo.unit_of_work() as uow:
        rules = uow.rules.for_subjects(["sam"])
    resolved = resolve_rules(rules, ["me", "sam"], GroupContext("flat"), "me")
    result = split_receipt(
        [ItemInput("l1", "Chips", 300)], ["me", "sam"], [r.input for r in resolved]
    )
    assert result.shares == {"me": 300, "sam": 0}
    assert result.questions == ()


def test_the_same_pattern_in_personal_splits_learns_a_note() -> None:
    # F6
    repo, ids = InMemoryRepository(), SequentialIds("r")
    notes = NotesScope("me")
    save_bill(repo, ids, "b1", [LineAnswer("sam", "dessert", ("sam",), weighted=False)], notes)

    (learned,) = save_bill(
        repo, ids, "b2", [LineAnswer("sam", "dessert", ("sam",), weighted=False)], notes
    )

    assert (learned.kind, learned.scope) == (RuleKind.ONLY, notes)


def test_one_bill_gives_one_observation_per_person_and_item() -> None:
    repo, ids = InMemoryRepository(), SequentialIds("r")

    assert save_bill(repo, ids, "b1", [sam_left_out(), sam_left_out()]) == ()
    with repo.unit_of_work() as uow:
        assert len(uow.observations.for_subject_item(FLAT, "sam", "chips")) == 1


def test_lines_that_disagree_count_as_included() -> None:
    repo, ids = InMemoryRepository(), SequentialIds("r")
    save_bill(repo, ids, "b1", [sam_left_out()])

    mixed = [sam_left_out(), LineAnswer("sam", "chips", ("sam", "me"), weighted=False)]
    assert save_bill(repo, ids, "b2", mixed) == ()
    with repo.unit_of_work() as uow:
        outcomes = [o.outcome for o in uow.observations.for_subject_item(FLAT, "sam", "chips")]
    assert outcomes == [AnswerOutcome.EXCLUDED, AnswerOutcome.INCLUDED]


def test_an_included_answer_breaks_the_streak() -> None:
    repo, ids = InMemoryRepository(), SequentialIds("r")
    save_bill(repo, ids, "b1", [sam_left_out()])
    save_bill(repo, ids, "b2", [LineAnswer("sam", "chips", ("sam", "me"), weighted=True)])

    assert save_bill(repo, ids, "b3", [sam_left_out()]) == ()


def test_a_stated_rule_is_kept_unless_it_is_a_soft_exclude() -> None:
    repo, ids = InMemoryRepository(), SequentialIds("r")
    with repo.unit_of_work() as uow:
        uow.rules.put(Rule("s1", "sam", "chips", RuleKind.ONLY, FLAT, "sam", RuleSource.STATED, T0))
        uow.rules.put(
            Rule("s2", "sam", "beer", RuleKind.SOFT_EXCLUDE, FLAT, "sam", RuleSource.STATED, T0)
        )
    save_bill(repo, ids, "b1", [sam_left_out("chips"), sam_left_out("beer")])

    (learned,) = save_bill(repo, ids, "b2", [sam_left_out("chips"), sam_left_out("beer")])

    assert (learned.item_key, learned.kind) == ("beer", RuleKind.EXCLUDE)
    with repo.unit_of_work() as uow:
        assert uow.rules.get("s1") is not None
        assert uow.rules.get("s2") is None


def test_relearning_the_same_rule_changes_nothing() -> None:
    repo, ids = InMemoryRepository(), SequentialIds("r")
    save_bill(repo, ids, "b1", [sam_left_out()])
    (first,) = save_bill(repo, ids, "b2", [sam_left_out()])

    assert save_bill(repo, ids, "b3", [sam_left_out()]) == ()
    with repo.unit_of_work() as uow:
        assert uow.rules.find(FLAT, "sam", "chips") == first


def test_learning_leaves_everywhere_rules_alone() -> None:
    # Everywhere rules are never learned: Sam's own "usually skips chips" stays as he said it.
    repo, ids = InMemoryRepository(), SequentialIds("r")
    his = Rule(
        "e1", "sam", "chips", RuleKind.SOFT_EXCLUDE, Everywhere(), "sam", RuleSource.STATED, T0
    )
    with repo.unit_of_work() as uow:
        uow.rules.put(his)
    save_bill(repo, ids, "b1", [sam_left_out()])
    (learned,) = save_bill(repo, ids, "b2", [sam_left_out()])

    assert learned.scope == FLAT
    with repo.unit_of_work() as uow:
        assert uow.rules.get("e1") == his
