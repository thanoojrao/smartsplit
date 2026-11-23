"""Matching receipt lines to item keys, remembered per place (SPEC section 6.4)."""

from smartsplit.adapters.fakes.llm import FakeCanonicalizer
from smartsplit.adapters.fakes.repository import InMemoryRepository
from smartsplit.domain.enums import MatchHow
from smartsplit.domain.model import ItemAlias, LineItem
from smartsplit.domain.values import GroupScope, LocalScope, NotesScope
from smartsplit.services.matching import (
    MatchedLines,
    load_match_inputs,
    match_lines,
    remember_matches,
)

FLAT, GOA, MY_NOTES = GroupScope("flat"), GroupScope("goa"), NotesScope("me")


def line(line_id: str, name: str, discount_for: str | None = None) -> LineItem:
    return LineItem(line_id, 1, name, 1, 100, None, 0.9, None, discount_for, MatchHow.NONE, False)


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
    model: FakeCanonicalizer | None = None,
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
    assert [m.canonical for m in matched.lines] == ["oat milk", "oat milk"]
    assert len(matched.new_aliases) == 1


def test_a_linked_discount_takes_its_lines_key_without_asking() -> None:
    # E11: "MILK 20% OFF" linked to the milk line shares its key, so the same rules apply.
    model = FakeCanonicalizer({"2% mlk gal": "milk"})
    lines = [line("1", "2% MLK GAL"), line("2", "MILK 20% OFF", discount_for="1")]

    matched = run(repo_with_items("milk"), FLAT, lines, model)

    assert how(matched) == [("milk", MatchHow.LLM, True), ("milk", MatchHow.LLM, False)]
    assert model.calls == ["2% MLK GAL"]


def test_links_to_unknown_or_discount_lines_are_matched_on_their_own_names() -> None:
    lines = [
        line("1", "Milk"),
        line("2", "Coupon", discount_for="1"),
        line("3", "Bread", discount_for="2"),
        line("4", "Eggs", discount_for="gone"),
    ]

    matched = run(repo_with_items("milk", "bread", "eggs"), FLAT, lines)

    assert [m.canonical for m in matched.lines] == ["milk", "milk", "bread", "eggs"]
