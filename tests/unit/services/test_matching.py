"""Matching receipt lines to item keys, remembered per place (SPEC section 6.4)."""

from collections.abc import Sequence

import pytest

from smartsplit.adapters.fakes.llm import FakeCanonicalizer
from smartsplit.adapters.fakes.repository import InMemoryRepository
from smartsplit.domain.enums import MatchHow
from smartsplit.domain.model import ItemAlias, LineItem
from smartsplit.domain.values import GroupScope, LocalScope, NotesScope
from smartsplit.ports.llm import Canonicalizer, LlmUnavailableError
from smartsplit.services.matching import (
    MatchedLines,
    load_match_inputs,
    match_lines,
    remember_matches,
)

FLAT, GOA, MY_NOTES = GroupScope("flat"), GroupScope("goa"), NotesScope("me")


def line(line_id: str, name: str, discount_for: str | None = None, cents: int = 100) -> LineItem:
    return LineItem(line_id, 1, name, 1, cents, None, 0.9, None, discount_for, MatchHow.NONE, False)


def repo_with_items(*keys: str) -> InMemoryRepository:
    repo = InMemoryRepository()
    with repo.unit_of_work() as uow:
        for key in keys:
            uow.items.ensure(key)
    return repo


def run(
    repo: InMemoryRepository,
    scope: LocalScope,
    lines: list[LineItem],
    model: Canonicalizer | None = None,
) -> MatchedLines:
    with repo.unit_of_work() as uow:
        inputs = load_match_inputs(uow, scope)
    matched = match_lines(lines, inputs, model or FakeCanonicalizer(), threshold=85)
    with repo.unit_of_work() as uow:
        remember_matches(uow, matched)
    return matched


def how(matched: MatchedLines) -> list[tuple[str | None, MatchHow, bool]]:
    return [(m.canonical, m.match_how, m.match_is_new) for m in matched.lines]


def test_exact_then_fuzzy_then_the_model() -> None:
    # F10
    repo = repo_with_items("milk", "protein powder")
    model = FakeCanonicalizer({"2% MLK GAL": "milk"})

    matched = run(
        repo,
        FLAT,
        [line("1", "MILK"), line("2", "Protein Powdr"), line("3", "2% MLK GAL")],
        model,
    )

    assert how(matched) == [
        ("milk", MatchHow.EXACT, False),
        ("protein powder", MatchHow.FUZZY, True),
        ("milk", MatchHow.LLM, True),
    ]
    assert model.calls == ["2% MLK GAL"]
    assert matched.model_calls == 1


def test_new_matches_are_remembered_in_this_place_only() -> None:
    repo = repo_with_items("milk")
    model = FakeCanonicalizer({"2% MLK GAL": "milk"})
    run(repo, FLAT, [line("1", "2% MLK GAL")], model)

    again = run(repo, FLAT, [line("1", "2%  mlk gal")], model)
    elsewhere = run(repo, GOA, [line("1", "2% MLK GAL")], model)

    assert how(again) == [("milk", MatchHow.ALIAS, False)]
    assert how(elsewhere) == [("milk", MatchHow.LLM, True)]
    assert model.calls == ["2% MLK GAL", "2% MLK GAL"]
    with repo.unit_of_work() as uow:
        assert uow.aliases.for_scope(FLAT) == (ItemAlias(FLAT, "2% mlk gal", "milk"),)


def test_a_personal_split_remembers_matches_in_the_adders_notes() -> None:
    repo = repo_with_items("milk")
    run(repo, MY_NOTES, [line("1", "Milk Gallon")], FakeCanonicalizer({"milk gallon": "milk"}))

    with repo.unit_of_work() as uow:
        assert uow.aliases.for_scope(MY_NOTES) == (ItemAlias(MY_NOTES, "milk gallon", "milk"),)
        assert uow.aliases.for_scope(FLAT) == ()


def test_a_name_the_model_calls_new_becomes_its_own_item() -> None:
    repo = repo_with_items("milk")

    matched = run(repo, FLAT, [line("1", "Dragon Fruit")])

    assert how(matched) == [("dragon fruit", MatchHow.LLM, False)]
    assert matched.new_aliases == ()
    with repo.unit_of_work() as uow:
        assert uow.items.keys() == frozenset({"milk", "dragon fruit"})
        assert uow.aliases.for_scope(FLAT) == ()


def test_the_model_is_asked_once_per_distinct_name() -> None:
    model = FakeCanonicalizer({"oat mlk": "oat milk"})

    matched = run(repo_with_items(), FLAT, [line("1", "OAT MLK"), line("2", "oat  mlk")], model)

    assert model.calls == ["OAT MLK"]
    assert matched.model_calls == 1
    assert [m.canonical for m in matched.lines] == ["oat milk", "oat milk"]
    assert len(matched.new_aliases) == 1


def test_a_linked_discount_takes_its_lines_key_without_asking() -> None:
    # E11: "MILK 20% OFF" linked to the milk line shares its key, so the same rules apply.
    model = FakeCanonicalizer({"2% mlk gal": "milk"})
    lines = [line("1", "2% MLK GAL"), line("2", "MILK 20% OFF", discount_for="1", cents=-20)]

    matched = run(repo_with_items("milk"), FLAT, lines, model)

    assert how(matched) == [("milk", MatchHow.LLM, True), ("milk", MatchHow.LLM, False)]
    assert model.calls == ["2% MLK GAL"]


def test_a_refund_is_matched_by_name_and_follows_that_items_rules() -> None:
    # Checkpoint A decision: "PROTEIN POWDER REFUND" is protein powder, so Sam's "only" applies.
    model = FakeCanonicalizer({"protein powder refund": "protein powder"})
    lines = [line("1", "Protein Powder"), line("2", "PROTEIN POWDER REFUND", cents=-500)]

    matched = run(repo_with_items("protein powder"), FLAT, lines, model)

    assert [m.canonical for m in matched.lines] == ["protein powder", "protein powder"]
    assert model.calls == ["PROTEIN POWDER REFUND"]


def test_a_generic_coupon_becomes_its_own_item_with_no_rules() -> None:
    # It gets its own key, which no rule mentions, so everyone shares it (E10).
    matched = run(
        repo_with_items("milk"), FLAT, [line("1", "Milk"), line("2", "COUPON", cents=-50)]
    )

    assert how(matched)[1] == ("coupon", MatchHow.LLM, False)


def test_positive_lines_and_broken_links_are_matched_on_their_own_names() -> None:
    lines = [
        line("1", "Milk"),
        line("2", "Bread", discount_for="1"),
        line("3", "Eggs", discount_for="gone", cents=-5),
    ]

    matched = run(repo_with_items("milk", "bread", "eggs"), FLAT, lines)

    assert [m.canonical for m in matched.lines] == ["milk", "bread", "eggs"]


def test_keys_the_model_creates_count_as_known_for_the_rest_of_the_receipt() -> None:
    model = FakeCanonicalizer()
    lines = [line("1", "Dragon Fruit"), line("2", "Dragon Fruits")]

    matched = run(repo_with_items(), FLAT, lines, model)

    assert model.calls == ["Dragon Fruit"]
    assert how(matched) == [
        ("dragon fruit", MatchHow.LLM, False),
        ("dragon fruit", MatchHow.FUZZY, True),
    ]
    assert matched.model_calls == 1


class Unavailable:
    def canonicalize(self, name: str, known_keys: Sequence[str]) -> str:
        raise LlmUnavailableError


def test_a_model_outage_propagates_and_nothing_is_remembered() -> None:
    repo = repo_with_items("milk")
    with repo.unit_of_work() as uow:
        inputs = load_match_inputs(uow, FLAT)

    with pytest.raises(LlmUnavailableError):
        match_lines([line("1", "Milk"), line("2", "Dragon fruit")], inputs, Unavailable(), 85)

    with repo.unit_of_work() as uow:
        assert uow.items.keys() == frozenset({"milk"})
        assert uow.aliases.for_scope(FLAT) == ()


class InsistsOnNoOpenTransaction:
    """A model stand-in that fails if any unit of work is open while it is asked (SPEC 12.2)."""

    def __init__(self, repo: InMemoryRepository) -> None:
        self._repo = repo
        self.calls = 0

    def canonicalize(self, name: str, known_keys: Sequence[str]) -> str:
        with self._repo.unit_of_work():  # the fake refuses this while another is open
            self.calls += 1
        return name


def test_the_model_is_never_asked_while_a_unit_of_work_is_open() -> None:
    """The guarantee is structural: `match_lines` takes no unit of work, so the documented
    read → match → remember flow keeps the model call outside any transaction. M7 runs the
    same check against the orchestrator."""
    repo = repo_with_items("milk")
    model = InsistsOnNoOpenTransaction(repo)

    run(repo, FLAT, [line("1", "Dragon Fruit"), line("2", "Milk")], model)

    assert model.calls == 1
