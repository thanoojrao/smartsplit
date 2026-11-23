"""In-memory stores for people, identities, nicknames, groups, memberships and chats."""

from dataclasses import replace
from datetime import datetime

from smartsplit.adapters.fakes.base import insert, replace_existing
from smartsplit.domain.model import (
    ChatIdentity,
    Conversation,
    Group,
    Membership,
    Nickname,
    Person,
)
from smartsplit.domain.values import ConversationKey


class PeopleStore:
    def __init__(self) -> None:
        self.records: dict[str, Person] = {}

    def get(self, person_id: str) -> Person | None:
        return self.records.get(person_id)

    def by_phone(self, phone: str) -> Person | None:
        return next((p for p in self.records.values() if p.phone == phone), None)

    def add(self, person: Person) -> None:
        if self.by_phone(person.phone):
            raise ValueError("duplicate phone")
        insert(self.records, person.id, person)

    def update(self, person: Person) -> None:
        replace_existing(self.records, person.id, person)


class IdentityStore:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], ChatIdentity] = {}

    def get(self, channel: str, external_ref: str) -> ChatIdentity | None:
        return self.records.get((channel, external_ref))

    def add(self, identity: ChatIdentity) -> None:
        insert(self.records, (identity.channel, identity.external_ref), identity)

    def for_person(self, person_id: str) -> tuple[ChatIdentity, ...]:
        return tuple(i for i in self.records.values() if i.person_id == person_id)


class NicknameStore:
    def __init__(self) -> None:
        self.records: dict[tuple[str, str], Nickname] = {}

    def put(self, nickname: Nickname) -> None:
        self.records[(nickname.owner_id, nickname.name)] = nickname

    def for_owner(self, owner_id: str) -> tuple[Nickname, ...]:
        return tuple(
            sorted((n for n in self.records.values() if n.owner_id == owner_id), key=_name)
        )


def _name(nickname: Nickname) -> str:
    return nickname.name


class GroupStore:
    def __init__(self) -> None:
        self.records: dict[str, Group] = {}

    def get(self, group_id: str) -> Group | None:
        return self.records.get(group_id)

    def by_channel_ref(self, key: ConversationKey) -> Group | None:
        return next((g for g in self.records.values() if g.channel_ref == key), None)

    def add(self, group: Group) -> None:
        if group.channel_ref and self.by_channel_ref(group.channel_ref):
            raise ValueError("duplicate channel_ref")
        insert(self.records, group.id, group)

    def update(self, group: Group) -> None:
        replace_existing(self.records, group.id, group)


class MembershipStore:
    def __init__(self) -> None:
        self.records: list[Membership] = []

    def add(self, membership: Membership) -> None:
        if self._current_index(membership.group_id, membership.person_id) is not None:
            raise ValueError("already a current member")
        self.records.append(membership)

    def end(self, group_id: str, person_id: str, left_at: datetime) -> None:
        index = self._current_index(group_id, person_id)
        if index is None:
            raise KeyError((group_id, person_id))
        self.records[index] = replace(self.records[index], left_at=left_at)

    def for_group(self, group_id: str) -> tuple[Membership, ...]:
        mine = [m for m in self.records if m.group_id == group_id]
        return tuple(sorted(mine, key=lambda m: m.position))

    def for_person(self, person_id: str) -> tuple[Membership, ...]:
        mine = [m for m in self.records if m.person_id == person_id]
        return tuple(sorted(mine, key=lambda m: m.joined_at))

    def _current_index(self, group_id: str, person_id: str) -> int | None:
        return next(
            (
                i
                for i, m in enumerate(self.records)
                if (m.group_id, m.person_id) == (group_id, person_id) and m.left_at is None
            ),
            None,
        )


class ConversationStore:
    def __init__(self) -> None:
        self.records: dict[ConversationKey, Conversation] = {}

    def get(self, key: ConversationKey) -> Conversation | None:
        return self.records.get(key)

    def add(self, conversation: Conversation) -> None:
        insert(self.records, conversation.key, conversation)

    def update(self, conversation: Conversation) -> None:
        replace_existing(self.records, conversation.key, conversation)
