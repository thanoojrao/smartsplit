"""Rule scopes, stating and deleting rules, and who may (SPEC section 6.2)."""

from datetime import UTC, datetime, timedelta

import pytest

from smartsplit.adapters.fakes.repository import InMemoryRepository
from smartsplit.domain.enums import ConversationKind, RuleKind, RuleSource
from smartsplit.domain.model import Membership, Rule
from smartsplit.domain.values import (
    Everywhere,
    GroupContext,
    GroupScope,
    NotesScope,
    PersonalContext,
    RuleScope,
)
from smartsplit.engine import ItemInput, resolve_rules, split_receipt
from smartsplit.ports.repository import UnitOfWork
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.rules import add_stated_rule, delete_rule
from smartsplit.services.scopes import local_scope_for, stated_rule_scope

T0 = datetime(2026, 11, 1, tzinfo=UTC)
FLAT = GroupScope("flat")
GROUP, PERSONAL = ConversationKind.GROUP, ConversationKind.PERSONAL


def test_where_a_stated_rule_lives() -> None:
    # F1-F4
    assert stated_rule_scope(PERSONAL, None, "raj", "raj") == Everywhere()
    assert stated_rule_scope(GROUP, "flat", "raj", "raj") == FLAT
    assert stated_rule_scope(GROUP, "flat", "me", "sam") == FLAT
    assert stated_rule_scope(PERSONAL, None, "me", "sam") == NotesScope("me")
    with pytest.raises(ValueError):
        stated_rule_scope(GROUP, None, "me", "sam")


def test_where_a_bill_matches_and_learns() -> None:
    assert local_scope_for(GroupContext("flat"), "me") == FLAT
    assert local_scope_for(PersonalContext(), "me") == NotesScope("me")


def make_repo() -> InMemoryRepository:
    repo = InMemoryRepository()
    with repo.unit_of_work() as uow:
        uow.memberships.add(Membership("flat", "me", 1, T0, None))
        uow.memberships.add(Membership("flat", "raj", 2, T0, T0 + timedelta(days=1)))
    return repo


def add(
    uow: UnitOfWork,
    scope: RuleScope,
    *,
    subject: str = "raj",
    item: str = "Milk",
    kind: RuleKind = RuleKind.EXCLUDE,
    author: str = "me",
    rule_id: str = "r1",
    minutes: int = 0,
) -> Rule:
    now = T0 + timedelta(days=2, minutes=minutes)
    return add_stated_rule(
        uow,
        rule_id=rule_id,
        scope=scope,
        subject_id=subject,
        item=item,
        kind=kind,
        author_id=author,
        now=now,
    )


def test_a_stated_rule_is_stored_normalized_and_its_item_is_known() -> None:
    repo = make_repo()
    with repo.unit_of_work() as uow:
        rule = add(uow, FLAT, item="  Protein   POWDER", subject="sam", kind=RuleKind.ONLY)

    with repo.unit_of_work() as uow:
        assert uow.rules.find(FLAT, "sam", "protein powder") == rule
        assert rule.source is RuleSource.STATED
        assert rule.author_id == "me"
        assert uow.items.keys() >= {"protein powder"}


def test_a_new_stated_rule_replaces_the_old_one_in_that_scope() -> None:
    repo = make_repo()
    with repo.unit_of_work() as uow:
        add(uow, FLAT, kind=RuleKind.EXCLUDE, rule_id="r1")
        add(uow, NotesScope("me"), kind=RuleKind.EXCLUDE, rule_id="r2")
        add(uow, FLAT, kind=RuleKind.SOFT_EXCLUDE, rule_id="r3", minutes=1)

    with repo.unit_of_work() as uow:
        assert [r.id for r in uow.rules.for_subjects(["raj"])] == ["r2", "r3"]


def test_raj_drinks_milk_now_deletes_the_rule_in_that_scope_only() -> None:
    # F9
    repo = make_repo()
    with repo.unit_of_work() as uow:
        add(uow, FLAT, rule_id="group")
        add(uow, Everywhere(), author="raj", rule_id="his")
        deleted = delete_rule(uow, scope=FLAT, subject_id="raj", item="MILK", by="me", now=T0)
        nothing = delete_rule(uow, scope=FLAT, subject_id="raj", item="milk", by="me", now=T0)

    assert deleted is not None
    assert deleted.id == "group"
    assert nothing is None
    with repo.unit_of_work() as uow:
        assert [r.id for r in uow.rules.for_subjects(["raj"])] == ["his"]


@pytest.mark.parametrize(
    ("scope", "speaker"),
    [
        (Everywhere(), "me"),
        (FLAT, "raj"),
        (FLAT, "stranger"),
        (NotesScope("sam"), "me"),
    ],
)
def test_who_may_change_rules(scope: RuleScope, speaker: str) -> None:
    # Everywhere: only the subject. Group: current members (Raj moved out). Notes: the owner.
    repo = make_repo()
    with pytest.raises(NotAllowedError), repo.unit_of_work() as uow:
        add(uow, scope, author=speaker)
    with pytest.raises(NotAllowedError), repo.unit_of_work() as uow:
        delete_rule(uow, scope=scope, subject_id="raj", item="milk", by=speaker, now=T0)


def test_a_group_rule_beats_an_everywhere_rule_on_a_group_bill() -> None:
    # F7, end to end: Raj excludes milk everywhere, but the flat's rule says he only usually
    # skips it; on a flat bill the group rule wins, so he stays in and is asked.
    repo = make_repo()
    with repo.unit_of_work() as uow:
        add(uow, Everywhere(), author="raj", rule_id="his")
        add(uow, FLAT, kind=RuleKind.SOFT_EXCLUDE, rule_id="flat", minutes=1)
        rules = uow.rules.for_subjects(["me", "raj"])

    resolved = resolve_rules(rules, ["me", "raj"], GroupContext("flat"), "me")
    result = split_receipt(
        [ItemInput("l1", "Milk", 600)], ["me", "raj"], [r.input for r in resolved]
    )

    assert result.shares == {"me": 300, "raj": 300}
    assert [q.member_id for q in result.questions] == ["raj"]
