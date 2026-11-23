"""Rule scopes, stating and deleting rules, and who may (SPEC section 6.2)."""

from datetime import UTC, datetime, timedelta

import pytest

from smartsplit.adapters.fakes.repository import InMemoryRepository
from smartsplit.domain.enums import ConversationKind, RuleKind, RuleSource
from smartsplit.domain.model import Group, Membership, Person, Rule
from smartsplit.domain.values import (
    Everywhere,
    GroupContext,
    GroupScope,
    NotesScope,
    PersonalContext,
)
from smartsplit.engine import ItemInput, resolve_rules, split_receipt
from smartsplit.ports.repository import UnitOfWork
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.rules import (
    find_stated_rule,
    is_current_member,
    propose_stated_rule,
    put_rule,
)
from smartsplit.services.scopes import local_scope_for, stated_rule_scope

T0 = datetime(2026, 11, 1, tzinfo=UTC)
LATER = T0 + timedelta(days=2)
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
    """Flat 4B: me and Sam are members; Raj moved out after a day."""
    repo = InMemoryRepository()
    with repo.unit_of_work() as uow:
        for n, pid in enumerate(("me", "sam", "raj")):
            uow.people.add(Person(pid, pid.title(), f"+91987654321{n}", None, True, True, T0))
        uow.groups.add(Group("flat", "Flat 4B", None, T0))
        uow.memberships.add(Membership("flat", "me", 1, T0, None))
        uow.memberships.add(Membership("flat", "sam", 2, T0, None))
        uow.memberships.add(Membership("flat", "raj", 3, T0, T0 + timedelta(days=1)))
    return repo


def add(
    uow: UnitOfWork,
    kind_of_chat: ConversationKind = GROUP,
    *,
    subject: str = "raj",
    item: str = "Milk",
    kind: RuleKind = RuleKind.EXCLUDE,
    author: str = "me",
    rule_id: str = "r1",
    minutes: int = 0,
) -> Rule:
    rule = propose_stated_rule(
        uow,
        rule_id=rule_id,
        conversation_kind=kind_of_chat,
        group_id="flat" if kind_of_chat is GROUP else None,
        subject_id=subject,
        item=item,
        kind=kind,
        author_id=author,
        now=LATER + timedelta(minutes=minutes),
    )
    put_rule(uow, rule)
    return rule


def delete(
    uow: UnitOfWork, kind_of_chat: ConversationKind, by: str, item: str = "milk"
) -> Rule | None:
    rule = find_stated_rule(
        uow,
        conversation_kind=kind_of_chat,
        group_id="flat" if kind_of_chat is GROUP else None,
        subject_id="raj",
        item=item,
        by=by,
        now=LATER,
    )
    if rule is not None:
        uow.rules.delete(rule.id)
    return rule


def test_a_stated_rule_is_stored_normalized_and_its_item_is_known() -> None:
    repo = make_repo()
    with repo.unit_of_work() as uow:
        rule = add(uow, item="  Protein   POWDER", subject="sam", kind=RuleKind.ONLY)

    with repo.unit_of_work() as uow:
        assert uow.rules.find(FLAT, "sam", "protein powder") == rule
        assert (rule.source, rule.author_id) == (RuleSource.STATED, "me")
        assert uow.items.keys() >= {"protein powder"}


def test_the_scope_follows_the_chat_and_the_subject() -> None:
    # F1, F2, F4: Raj in his chat → his Everywhere rule; in the flat → flat rule; my note on Sam.
    repo = make_repo()
    with repo.unit_of_work() as uow:
        his = add(uow, PERSONAL, author="raj", rule_id="his")
        flat = add(uow, GROUP, author="sam", rule_id="flat")
        note = add(uow, PERSONAL, subject="sam", item="dessert", rule_id="note")

    assert (his.scope, flat.scope, note.scope) == (Everywhere(), FLAT, NotesScope("me"))


def test_a_new_stated_rule_replaces_the_old_one_in_that_scope() -> None:
    repo = make_repo()
    with repo.unit_of_work() as uow:
        add(uow, GROUP, rule_id="r1")
        add(uow, PERSONAL, rule_id="r2")
        add(uow, GROUP, kind=RuleKind.SOFT_EXCLUDE, rule_id="r3", minutes=1)

    with repo.unit_of_work() as uow:
        assert [r.id for r in uow.rules.for_subjects(["raj"])] == ["r2", "r3"]


def test_a_stated_rule_replaces_a_learned_one() -> None:
    repo = make_repo()
    learned = Rule("l1", "raj", "milk", RuleKind.ONLY, FLAT, "me", RuleSource.LEARNED, T0)
    with repo.unit_of_work() as uow:
        uow.rules.put(learned)
        stated = add(uow, GROUP, rule_id="s1")

    with repo.unit_of_work() as uow:
        assert uow.rules.find(FLAT, "raj", "milk") == stated


def test_raj_drinks_milk_now_deletes_the_rule_in_that_scope_only() -> None:
    # F9
    repo = make_repo()
    with repo.unit_of_work() as uow:
        add(uow, GROUP, rule_id="group")
        add(uow, PERSONAL, author="raj", rule_id="his")
        deleted = delete(uow, GROUP, by="sam", item="MILK")
        nothing = delete(uow, GROUP, by="sam")

    assert deleted is not None
    assert deleted.id == "group"
    assert nothing is None
    with repo.unit_of_work() as uow:
        assert [r.id for r in uow.rules.for_subjects(["raj"])] == ["his"]


@pytest.mark.parametrize(
    ("kind_of_chat", "speaker"),
    [
        (GROUP, "raj"),  # moved out
        (GROUP, "stranger"),
    ],
)
def test_only_current_members_change_group_rules(
    kind_of_chat: ConversationKind, speaker: str
) -> None:
    repo = make_repo()
    with pytest.raises(NotAllowedError), repo.unit_of_work() as uow:
        add(uow, kind_of_chat, author=speaker)
    with pytest.raises(NotAllowedError), repo.unit_of_work() as uow:
        delete(uow, kind_of_chat, by=speaker)


def test_nobody_can_write_someone_elses_everywhere_rule_or_notes() -> None:
    # Said about Raj in my chat, it becomes my note, never Raj's Everywhere rule (F15 owners).
    repo = make_repo()
    with repo.unit_of_work() as uow:
        mine = add(uow, PERSONAL, author="me")
        add(uow, PERSONAL, author="raj", rule_id="his")
        assert delete(uow, PERSONAL, by="sam") is None

    assert mine.scope == NotesScope("me")
    with repo.unit_of_work() as uow:
        assert {r.id for r in uow.rules.for_subjects(["raj"])} == {"r1", "his"}


def test_membership_is_checked_at_that_moment() -> None:
    repo = make_repo()
    with repo.unit_of_work() as uow:
        assert is_current_member(uow, "flat", "raj", T0)
        assert not is_current_member(uow, "flat", "raj", T0 + timedelta(days=1))
        assert not is_current_member(uow, "flat", "me", T0 - timedelta(seconds=1))


def test_a_group_rule_beats_an_everywhere_rule_on_a_group_bill() -> None:
    # F7, end to end: Raj excludes milk everywhere, but the flat's rule says he only usually
    # skips it; on a flat bill the group rule wins, so he stays in and is asked.
    repo = make_repo()
    with repo.unit_of_work() as uow:
        add(uow, PERSONAL, author="raj", rule_id="his")
        add(uow, GROUP, kind=RuleKind.SOFT_EXCLUDE, rule_id="flat", minutes=1)
        rules = uow.rules.for_subjects(["me", "raj"])

    resolved = resolve_rules(rules, ["me", "raj"], GroupContext("flat"), "me")
    result = split_receipt(
        [ItemInput("l1", "Milk", 600)], ["me", "raj"], [r.input for r in resolved]
    )

    assert result.shares == {"me": 300, "raj": 300}
    assert [q.member_id for q in result.questions] == ["raj"]
