"""People, identities, nicknames, groups, memberships and conversations."""

from dataclasses import replace

import pytest

from smartsplit.domain.enums import ConversationKind
from smartsplit.domain.model import ChatIdentity, Conversation, Group, Membership, Nickname
from smartsplit.domain.values import ConversationKey
from smartsplit.ports.repository import Repository
from tests.repository.builders import CHAT, DUPLICATE, T0, at, person


def test_people_by_id_and_phone_and_update(repo: Repository) -> None:
    with repo.unit_of_work() as uow:
        uow.people.add(person("sam", "+919876543210", used_bot=False))
        uow.people.update(replace(person("sam", "+919876543210"), display_name="Samuel"))

    with repo.unit_of_work() as uow:
        found = uow.people.by_phone("+919876543210")
        assert found is not None
        assert (found.display_name, found.has_used_bot) == ("Samuel", True)
        assert uow.people.by_phone("+910000000000") is None
        assert uow.people.get("nobody") is None


def test_phone_is_unique(repo: Repository) -> None:
    with pytest.raises(DUPLICATE), repo.unit_of_work() as uow:
        uow.people.add(person("sam", "+919876543210"))
        uow.people.add(person("other", "+919876543210"))


def test_changing_a_phone_to_one_already_taken_raises(repo: Repository) -> None:
    with repo.unit_of_work() as uow:
        uow.people.add(person("sam", "+919876543210"))
        uow.people.add(person("raj", "+919876543211"))

    with pytest.raises(DUPLICATE), repo.unit_of_work() as uow:
        uow.people.update(person("raj", "+919876543210"))


def test_linking_a_group_to_a_chat_already_taken_raises(repo: Repository) -> None:
    with repo.unit_of_work() as uow:
        uow.groups.add(Group("g1", "Flat 4B", CHAT, T0))
        uow.groups.add(Group("g2", "Other", None, T0))

    with pytest.raises(DUPLICATE), repo.unit_of_work() as uow:
        uow.groups.update(Group("g2", "Other", CHAT, T0))


def test_updating_a_missing_record_raises(repo: Repository) -> None:
    with pytest.raises(KeyError), repo.unit_of_work() as uow:
        uow.people.update(person("ghost"))


def test_two_identities_map_to_one_person(repo: Repository) -> None:
    # A6: a WhatsApp number and a hidden id are two identities of one person.
    with repo.unit_of_work() as uow:
        uow.people.add(person("sam"))
        uow.identities.add(ChatIdentity("whatsapp", "+919876543210", "sam"))
        uow.identities.add(ChatIdentity("whatsapp_lid", "123@lid", "sam"))

    with repo.unit_of_work() as uow:
        assert uow.identities.get("whatsapp_lid", "123@lid") == ChatIdentity(
            "whatsapp_lid", "123@lid", "sam"
        )
        assert uow.identities.get("whatsapp", "nope") is None
        assert [i.channel for i in uow.identities.for_person("sam")] == ["whatsapp", "whatsapp_lid"]


def test_nicknames_are_per_owner_and_replaceable(repo: Repository) -> None:
    with repo.unit_of_work() as uow:
        for pid in ("me", "raj", "sam", "sam2"):
            uow.people.add(person(pid))
        uow.nicknames.put(Nickname("me", "sam", "sam"))
        uow.nicknames.put(Nickname("raj", "sam", "samuel"))
        uow.nicknames.put(Nickname("me", "sam2", "sam"))
        uow.nicknames.put(Nickname("me", "raj", "boss"))

    with repo.unit_of_work() as uow:
        assert uow.nicknames.for_owner("me") == (
            Nickname("me", "raj", "boss"),
            Nickname("me", "sam2", "sam"),
        )
        assert uow.nicknames.for_owner("raj") == (Nickname("raj", "sam", "samuel"),)


def test_groups_by_id_and_chat(repo: Repository) -> None:
    group = Group("g1", "Flat 4B", CHAT, T0)
    with repo.unit_of_work() as uow:
        uow.groups.add(group)
        uow.groups.add(Group("g2", "No chat", None, T0))
        uow.groups.update(replace(group, name="Flat 4B (new)"))

    with repo.unit_of_work() as uow:
        assert uow.groups.by_channel_ref(CHAT) == replace(group, name="Flat 4B (new)")
        assert uow.groups.get("g2") == Group("g2", "No chat", None, T0)
        assert uow.groups.by_channel_ref(ConversationKey("cli", "other")) is None


def test_memberships_end_and_rejoin(repo: Repository) -> None:
    with repo.unit_of_work() as uow:
        uow.groups.add(Group("g1", "Flat 4B", CHAT, T0))
        for pid in ("sam", "raj"):
            uow.people.add(person(pid))
        uow.memberships.add(Membership("g1", "raj", 2, at(1), None))
        uow.memberships.add(Membership("g1", "sam", 1, at(0), None))
        uow.memberships.end("g1", "raj", at(10))
        uow.memberships.add(Membership("g1", "raj", 3, at(20), None))

    with repo.unit_of_work() as uow:
        assert uow.memberships.for_group("g1") == (
            Membership("g1", "sam", 1, at(0), None),
            Membership("g1", "raj", 2, at(1), at(10)),
            Membership("g1", "raj", 3, at(20), None),
        )
        assert [m.joined_at for m in uow.memberships.for_person("raj")] == [at(1), at(20)]


def test_one_current_membership_per_person_and_group(repo: Repository) -> None:
    with pytest.raises(DUPLICATE), repo.unit_of_work() as uow:
        uow.groups.add(Group("g1", "Flat 4B", CHAT, T0))
        uow.people.add(person("sam"))
        uow.memberships.add(Membership("g1", "sam", 1, at(0), None))
        uow.memberships.add(Membership("g1", "sam", 2, at(1), None))


def test_ending_a_membership_that_isnt_current_raises(repo: Repository) -> None:
    with pytest.raises(KeyError), repo.unit_of_work() as uow:
        uow.memberships.end("g1", "sam", at(1))


def test_conversations(repo: Repository) -> None:
    chat = Conversation(CHAT, ConversationKind.GROUP, "Flat 4B", "g1", None, ())
    with repo.unit_of_work() as uow:
        uow.conversations.add(chat)
        uow.conversations.update(replace(chat, last_listed_bill_ids=("b2", "b1")))

    with repo.unit_of_work() as uow:
        assert uow.conversations.get(CHAT) == replace(chat, last_listed_bill_ids=("b2", "b1"))
        assert uow.conversations.get(ConversationKey("cli", "x")) is None
