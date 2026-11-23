"""In-memory stores for people, identities, nicknames, groups, memberships and chats."""

from dataclasses import replace
from datetime import datetime

from smartsplit.adapters.fakes.base import insert, replace_existing, require_reference
from smartsplit.domain.model import (
    ChatIdentity,
    Conversation,
    Group,
    Membership,
    Nickname,
    Person,
)
from smartsplit.domain.values import ConversationKey
from smartsplit.ports.errors import DuplicateKeyError, InvalidRecordError


class PeopleStore:
    def __init__(self) -> None:
        self.records: dict[str, Person] = {}

    def get(self, person_id: str) -> Person | None:
        return self.records.get(person_id)

    def by_phone(self, phone: str) -> Person | None:
        return next((p for p in self.records.values() if p.phone == phone), None)

    def add(self, person: Person) -> None:
        self._check_phone_free(person)
        insert(self.records, person.id, person)

    def update(self, person: Person) -> None:
        self._check_phone_free(person)
        replace_existing(self.records, person.id, person)

    def _check_phone_free(self, person: Person) -> None:
        holder = self.by_phone(person.phone)
        if holder is not None and holder.id != person.id:
            raise DuplicateKeyError("duplicate phone")


class IdentityStore:
    def __init__(self, people: PeopleStore) -> None:
        self.records: dict[tuple[str, str], ChatIdentity] = {}
        self._people = people

    def get(self, channel: str, external_ref: str) -> ChatIdentity | None:
        return self.records.get((channel, external_ref))

    def add(self, identity: ChatIdentity) -> None:
        require_reference(self._people.records, identity.person_id)
        insert(self.records, (identity.channel, identity.external_ref), identity)

    def for_person(self, person_id: str) -> tuple[ChatIdentity, ...]:
        mine = [i for i in self.records.values() if i.person_id == person_id]
        return tuple(sorted(mine, key=lambda i: (i.channel, i.external_ref)))


class NicknameStore:
    def __init__(self, people: PeopleStore) -> None:
        self.records: dict[tuple[str, str], Nickname] = {}
        self._people = people

    def put(self, nickname: Nickname) -> None:
        require_reference(self._people.records, nickname.owner_id)
        require_reference(self._people.records, nickname.subject_id)
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
        self._check_chat_free(group)
        insert(self.records, group.id, group)

    def update(self, group: Group) -> None:
        self._check_chat_free(group)
        replace_existing(self.records, group.id, group)

    def _check_chat_free(self, group: Group) -> None:
        holder = self.by_channel_ref(group.channel_ref) if group.channel_ref else None
        if holder is not None and holder.id != group.id:
            raise DuplicateKeyError("duplicate channel_ref")


class MembershipStore:
    def __init__(self, groups: GroupStore, people: PeopleStore) -> None:
        self.records: list[Membership] = []
        self._groups = groups
        self._people = people

    def add(self, membership: Membership) -> None:
        require_reference(self._groups.records, membership.group_id)
        require_reference(self._people.records, membership.person_id)
        if self._current_index(membership.group_id, membership.person_id) is not None:
            raise DuplicateKeyError("already a current member")
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

    def personal_for(self, person_id: str) -> Conversation | None:
        mine = [c for c in self.records.values() if c.person_id == person_id]
        return min(mine, key=lambda c: (c.key.channel, c.key.ref), default=None)

    def add(self, conversation: Conversation) -> None:
        _check_group_or_person(conversation)
        insert(self.records, conversation.key, conversation)

    def update(self, conversation: Conversation) -> None:
        _check_group_or_person(conversation)
        replace_existing(self.records, conversation.key, conversation)


def _check_group_or_person(conversation: Conversation) -> None:
    if (conversation.group_id is None) == (conversation.person_id is None):
        raise InvalidRecordError("a conversation belongs to exactly one group or person")
