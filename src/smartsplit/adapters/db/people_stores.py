"""Postgres stores for people, identities, nicknames, groups, memberships and chats."""

from datetime import datetime

from sqlalchemy import Row, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from smartsplit.adapters.db import tables as t
from smartsplit.adapters.db.base import Store, require_one
from smartsplit.adapters.db.mapping import key_from
from smartsplit.domain.enums import ConversationKind
from smartsplit.domain.model import (
    ChatIdentity,
    Conversation,
    Group,
    Membership,
    Nickname,
    Person,
)
from smartsplit.domain.values import ConversationKey


def _person(row: Row[tuple[object, ...]]) -> Person:
    m = row._mapping
    return Person(
        m["id"],
        m["display_name"],
        m["phone"],
        m["phone_added_by"],
        m["notifications_enabled"],
        m["has_used_bot"],
        m["created_at"],
    )


def _person_values(person: Person) -> dict[str, object]:
    return {
        "id": person.id,
        "display_name": person.display_name,
        "phone": person.phone,
        "phone_added_by": person.phone_added_by,
        "notifications_enabled": person.notifications_enabled,
        "has_used_bot": person.has_used_bot,
        "created_at": person.created_at,
    }


class PeopleStore(Store):
    def get(self, person_id: str) -> Person | None:
        row = self._execute(select(t.people).where(t.people.c.id == person_id)).first()
        return _person(row) if row else None

    def by_phone(self, phone: str) -> Person | None:
        row = self._execute(select(t.people).where(t.people.c.phone == phone)).first()
        return _person(row) if row else None

    def add(self, person: Person) -> None:
        self._execute(insert(t.people).values(_person_values(person)))

    def update(self, person: Person) -> None:
        require_one(
            self._execute(
                update(t.people).where(t.people.c.id == person.id).values(_person_values(person))
            ).rowcount
        )


class IdentityStore(Store):
    def get(self, channel: str, external_ref: str) -> ChatIdentity | None:
        c = t.chat_identities.c
        row = self._execute(
            select(c.person_id).where(c.channel == channel, c.external_ref == external_ref)
        ).first()
        return ChatIdentity(channel, external_ref, row.person_id) if row else None

    def add(self, identity: ChatIdentity) -> None:
        self._execute(
            insert(t.chat_identities).values(
                channel=identity.channel,
                external_ref=identity.external_ref,
                person_id=identity.person_id,
            )
        )

    def for_person(self, person_id: str) -> tuple[ChatIdentity, ...]:
        c = t.chat_identities.c
        rows = self._execute(
            select(c.channel, c.external_ref)
            .where(c.person_id == person_id)
            .order_by(c.channel, c.external_ref)
        )
        return tuple(ChatIdentity(r.channel, r.external_ref, person_id) for r in rows)


class NicknameStore(Store):
    def put(self, nickname: Nickname) -> None:
        statement = pg_insert(t.nicknames).values(
            owner_id=nickname.owner_id, name=nickname.name, subject_id=nickname.subject_id
        )
        self._execute(
            statement.on_conflict_do_update(
                index_elements=["owner_id", "name"],
                set_={"subject_id": statement.excluded.subject_id},
            )
        )

    def for_owner(self, owner_id: str) -> tuple[Nickname, ...]:
        c = t.nicknames.c
        rows = self._execute(
            select(c.name, c.subject_id).where(c.owner_id == owner_id).order_by(c.name)
        )
        return tuple(Nickname(owner_id, r.subject_id, r.name) for r in rows)


def _group(row: Row[tuple[object, ...]]) -> Group:
    m = row._mapping
    channel_ref = key_from(m["channel"], m["channel_ref"]) if m["channel"] is not None else None
    return Group(m["id"], m["name"], channel_ref, m["created_at"])


def _group_values(group: Group) -> dict[str, object]:
    ref = group.channel_ref
    return {
        "id": group.id,
        "name": group.name,
        "channel": ref.channel if ref else None,
        "channel_ref": ref.ref if ref else None,
        "created_at": group.created_at,
    }


class GroupStore(Store):
    def get(self, group_id: str) -> Group | None:
        row = self._execute(select(t.groups).where(t.groups.c.id == group_id)).first()
        return _group(row) if row else None

    def by_channel_ref(self, key: ConversationKey) -> Group | None:
        c = t.groups.c
        row = self._execute(
            select(t.groups).where(c.channel == key.channel, c.channel_ref == key.ref)
        ).first()
        return _group(row) if row else None

    def add(self, group: Group) -> None:
        self._execute(insert(t.groups).values(_group_values(group)))

    def update(self, group: Group) -> None:
        require_one(
            self._execute(
                update(t.groups).where(t.groups.c.id == group.id).values(_group_values(group))
            ).rowcount
        )


def _membership(row: Row[tuple[object, ...]]) -> Membership:
    m = row._mapping
    return Membership(m["group_id"], m["person_id"], m["position"], m["joined_at"], m["left_at"])


class MembershipStore(Store):
    def add(self, membership: Membership) -> None:
        self._execute(
            insert(t.memberships).values(
                group_id=membership.group_id,
                person_id=membership.person_id,
                position=membership.position,
                joined_at=membership.joined_at,
                left_at=membership.left_at,
            )
        )

    def end(self, group_id: str, person_id: str, left_at: datetime) -> None:
        c = t.memberships.c
        require_one(
            self._execute(
                update(t.memberships)
                .where(c.group_id == group_id, c.person_id == person_id, c.left_at.is_(None))
                .values(left_at=left_at)
            ).rowcount
        )

    def for_group(self, group_id: str) -> tuple[Membership, ...]:
        c = t.memberships.c
        rows = self._execute(
            select(t.memberships).where(c.group_id == group_id).order_by(c.position, c.seq)
        )
        return tuple(_membership(r) for r in rows)

    def for_person(self, person_id: str) -> tuple[Membership, ...]:
        c = t.memberships.c
        rows = self._execute(
            select(t.memberships).where(c.person_id == person_id).order_by(c.joined_at, c.seq)
        )
        return tuple(_membership(r) for r in rows)


def _conversation_values(conversation: Conversation) -> dict[str, object]:
    return {
        "channel": conversation.key.channel,
        "ref": conversation.key.ref,
        "kind": conversation.kind.value,
        "name": conversation.name,
        "group_id": conversation.group_id,
        "person_id": conversation.person_id,
    }


def _conversation(row: Row[tuple[object, ...]]) -> Conversation:
    m = row._mapping
    return Conversation(
        key_from(m["channel"], m["ref"]),
        ConversationKind(m["kind"]),
        m["name"],
        m["group_id"],
        m["person_id"],
    )


class ConversationStore(Store):
    def get(self, key: ConversationKey) -> Conversation | None:
        c = t.conversations.c
        row = self._execute(
            select(t.conversations).where(c.channel == key.channel, c.ref == key.ref)
        ).first()
        return _conversation(row) if row else None

    def personal_for(self, person_id: str) -> Conversation | None:
        c = t.conversations.c
        row = self._execute(
            select(t.conversations).where(c.person_id == person_id).order_by(c.channel, c.ref)
        ).first()
        return _conversation(row) if row else None

    def add(self, conversation: Conversation) -> None:
        self._execute(insert(t.conversations).values(_conversation_values(conversation)))

    def update(self, conversation: Conversation) -> None:
        c = t.conversations.c
        key = conversation.key
        require_one(
            self._execute(
                update(t.conversations)
                .where(c.channel == key.channel, c.ref == key.ref)
                .values(_conversation_values(conversation))
            ).rowcount
        )
