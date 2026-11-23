"""Items, aliases, rules, answer observations and model-call counts."""

import threading
from datetime import date

import pytest
from sqlalchemy import Engine

from smartsplit.adapters.db.repository import SqlRepository
from smartsplit.domain.enums import AnswerOutcome, RuleKind
from smartsplit.domain.model import AnswerObservation, ItemAlias
from smartsplit.domain.values import Everywhere, GroupScope, NotesScope, RuleScope
from smartsplit.ports.repository import Repository
from tests.repository.builders import at, rule


def test_items_are_an_install_wide_set(repo: Repository) -> None:
    with repo.unit_of_work() as uow:
        uow.items.ensure("milk")
        uow.items.ensure("milk")
        uow.items.ensure("bread")

    with repo.unit_of_work() as uow:
        assert uow.items.keys() == frozenset({"milk", "bread"})


def test_aliases_are_per_scope(repo: Repository) -> None:
    flat, notes = GroupScope("g1"), NotesScope("sam")
    with repo.unit_of_work() as uow:
        uow.aliases.put(ItemAlias(flat, "oat mlk", "milk"))
        uow.aliases.put(ItemAlias(flat, "2% mlk gal", "milk"))
        uow.aliases.put(ItemAlias(notes, "oat mlk", "oat milk"))
        uow.aliases.put(ItemAlias(flat, "oat mlk", "oat milk"))

    with repo.unit_of_work() as uow:
        assert uow.aliases.for_scope(flat) == (
            ItemAlias(flat, "2% mlk gal", "milk"),
            ItemAlias(flat, "oat mlk", "oat milk"),
        )
        uow.aliases.delete(flat, "oat mlk")
        uow.aliases.delete(flat, "never stored")

    with repo.unit_of_work() as uow:
        assert uow.aliases.for_scope(flat) == (ItemAlias(flat, "2% mlk gal", "milk"),)
        assert uow.aliases.for_scope(notes) == (ItemAlias(notes, "oat mlk", "oat milk"),)
        assert uow.aliases.for_scope(GroupScope("g2")) == ()


def test_rules_one_per_scope_subject_and_item(repo: Repository) -> None:
    with repo.unit_of_work() as uow:
        uow.rules.put(rule("r1", Everywhere()))
        uow.rules.put(rule("r2", GroupScope("g1"), minutes=1))
        uow.rules.put(rule("r3", GroupScope("g1"), kind=RuleKind.SOFT_EXCLUDE, minutes=2))
        uow.rules.put(rule("r4", NotesScope("sam"), subject="sam", key="dessert", minutes=3))

    with repo.unit_of_work() as uow:
        assert uow.rules.get("r2") is None
        assert uow.rules.find(GroupScope("g1"), "raj", "milk") == rule(
            "r3", GroupScope("g1"), kind=RuleKind.SOFT_EXCLUDE, minutes=2
        )
        assert uow.rules.find(GroupScope("g2"), "raj", "milk") is None
        assert [r.id for r in uow.rules.for_subjects(["raj", "sam"])] == ["r1", "r3", "r4"]
        assert [r.id for r in uow.rules.for_subjects(["sam"])] == ["r4"]
        assert uow.rules.for_subjects([]) == ()


def test_rule_delete(repo: Repository) -> None:
    with repo.unit_of_work() as uow:
        uow.rules.put(rule("r1", Everywhere()))
        uow.rules.delete("r1")
        uow.rules.delete("missing")

    with repo.unit_of_work() as uow:
        assert uow.rules.get("r1") is None


def test_rules_round_trip_every_scope(repo: Repository) -> None:
    scopes: list[RuleScope] = [Everywhere(), GroupScope("g1"), NotesScope("me")]
    with repo.unit_of_work() as uow:
        for n, scope in enumerate(scopes):
            uow.rules.put(rule(f"r{n}", scope, minutes=n))

    with repo.unit_of_work() as uow:
        assert [r.scope for r in uow.rules.for_subjects(["raj"])] == scopes


def test_observations_oldest_first_per_scope_subject_and_item(repo: Repository) -> None:
    flat = GroupScope("g1")

    def obs(outcome: AnswerOutcome, minutes: int, scope: GroupScope = flat) -> AnswerObservation:
        return AnswerObservation(scope, "sam", "chips", outcome, f"b{minutes}", at(minutes))

    with repo.unit_of_work() as uow:
        uow.observations.add(obs(AnswerOutcome.EXCLUDED, 5))
        uow.observations.add(obs(AnswerOutcome.INCLUDED, 1))
        uow.observations.add(obs(AnswerOutcome.EXCLUDED, 9, GroupScope("g2")))
        uow.observations.add(
            AnswerObservation(flat, "raj", "chips", AnswerOutcome.EXCLUDED, "b7", at(7))
        )

    with repo.unit_of_work() as uow:
        assert uow.observations.for_subject_item(flat, "sam", "chips") == (
            obs(AnswerOutcome.INCLUDED, 1),
            obs(AnswerOutcome.EXCLUDED, 5),
        )
        assert uow.observations.for_subject_item(NotesScope("sam"), "sam", "chips") == ()


def test_llm_usage_counts_per_person_per_day(repo: Repository) -> None:
    today, tomorrow = date(2026, 11, 1), date(2026, 11, 2)
    with repo.unit_of_work() as uow:
        assert uow.llm_usage.get("sam", today) is None
        assert uow.llm_usage.increment("sam", today) == 1
        assert uow.llm_usage.increment("sam", today) == 2
        assert uow.llm_usage.increment("sam", tomorrow) == 1

    with repo.unit_of_work() as uow:
        usage = uow.llm_usage.get("sam", today)
        assert usage is not None
        assert usage.calls == 2


@pytest.mark.db
def test_two_people_changing_the_same_rule_at_once_both_succeed(clean_pg: Engine) -> None:
    repo = SqlRepository(clean_pg)
    errors: list[Exception] = []

    def second() -> None:
        try:
            with repo.unit_of_work() as uow:
                uow.rules.put(rule("r2", GroupScope("g1"), kind=RuleKind.ONLY, minutes=1))
        except Exception as error:  # a failure in the thread is asserted on below
            errors.append(error)

    with repo.unit_of_work() as uow:
        uow.rules.put(rule("r1", GroupScope("g1")))
        worker = threading.Thread(target=second)
        worker.start()
        worker.join(timeout=0.3)
        assert worker.is_alive()  # really waiting on the first, uncommitted write
    worker.join()

    assert errors == []
    with repo.unit_of_work() as uow:
        found = uow.rules.find(GroupScope("g1"), "raj", "milk")
    assert found == rule("r2", GroupScope("g1"), kind=RuleKind.ONLY, minutes=1)
