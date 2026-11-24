"""Who is talking, in which chat, and whether the bot should react (SPEC 6.1, 10.2, 10.3)."""

from dataclasses import dataclass, replace
from datetime import datetime

from smartsplit.domain.enums import ConversationKind
from smartsplit.domain.messages import InboundMessage, Mention
from smartsplit.domain.model import ChatIdentity, Conversation, Group, Membership, Person
from smartsplit.domain.phone import normalize_phone
from smartsplit.ports.repository import UnitOfWork
from smartsplit.ports.system import IdGenerator


@dataclass(frozen=True, slots=True)
class Arrival:
    """The resolved speaker and chat, and what is new about them this message."""

    speaker: Person
    conversation: Conversation
    first_personal_message: bool
    new_group: bool


def find_speaker(uow: UnitOfWork, message: InboundMessage) -> Person | None:
    """The person behind this message, through either of their chat identities."""
    for ref in (message.sender_ref, message.sender_alt_ref):
        if ref:
            identity = uow.identities.get(message.conversation.channel, ref)
            if identity:
                return uow.people.get(identity.person_id)
    return None


def arrive(
    uow: UnitOfWork, ids: IdGenerator, message: InboundMessage, region: str, now: datetime
) -> Arrival | None:
    """Resolve (or create) the speaker and the chat; None if they can't be identified.

    An unknown identity needs a phone number: a hidden id alone can't create a person.
    """
    speaker = find_speaker(uow, message) or _from_phone(uow, ids, message, region, now)
    if speaker is None:
        return None
    _link_identities(uow, message, speaker.id)
    first = message.conversation_kind is ConversationKind.PERSONAL and not speaker.has_used_bot
    if first:
        speaker = replace(
            speaker,
            has_used_bot=True,
            display_name=message.sender_name.strip() or speaker.display_name,
        )
        uow.people.update(speaker)
    conversation = uow.conversations.get(message.conversation)
    new_group = False
    if conversation is None:
        conversation = _new_conversation(uow, ids, message, speaker, now)
        new_group = conversation.group_id is not None
    return Arrival(speaker, conversation, first, new_group)


def mentioned(
    uow: UnitOfWork,
    ids: IdGenerator,
    message: InboundMessage,
    *,
    region: str,
    now: datetime,
    by: str,
) -> tuple[tuple[Mention, str | None], ...]:
    """Who each mention is: a known chat identity, or the person with the mention's phone (a
    new one if nobody has it, so "add @Priya" needs nothing more, SPEC 10.3); None when the
    gateway gave only a name. A new person is in no group until someone adds them."""
    found: list[tuple[Mention, str | None]] = []
    for mention in message.mentions:
        identity = uow.identities.get(message.conversation.channel, mention.ref)
        person_id = identity.person_id if identity else None
        if person_id is None and mention.phone:
            person = _person_with(
                uow, ids, phone=mention.phone, name=mention.name, region=region, now=now, by=by
            )
            if person is not None:
                person_id = person.id
                uow.identities.add(
                    ChatIdentity(message.conversation.channel, mention.ref, person_id)
                )
        found.append((mention, person_id))
    return tuple(found)


def _person_with(
    uow: UnitOfWork,
    ids: IdGenerator,
    *,
    phone: str,
    name: str,
    region: str,
    now: datetime,
    by: str | None,
) -> Person | None:
    """The person with this number, or a new one; None if it isn't a phone number."""
    try:
        number = normalize_phone(phone, region)
    except ValueError:
        return None
    existing = uow.people.by_phone(number)
    if existing:
        return existing
    person = Person(ids.new_id(), name.strip(), number, by, True, False, now)
    uow.people.add(person)
    return person


def _from_phone(
    uow: UnitOfWork, ids: IdGenerator, message: InboundMessage, region: str, now: datetime
) -> Person | None:
    if not message.sender_phone:
        return None
    return _person_with(
        uow,
        ids,
        phone=message.sender_phone,
        name=message.sender_name,
        region=region,
        now=now,
        by=None,
    )


def _link_identities(uow: UnitOfWork, message: InboundMessage, person_id: str) -> None:
    """Both refs of a message (e.g. number and hidden id) map to the same person (A6)."""
    for ref in (message.sender_ref, message.sender_alt_ref):
        if ref and uow.identities.get(message.conversation.channel, ref) is None:
            uow.identities.add(ChatIdentity(message.conversation.channel, ref, person_id))


def _new_conversation(
    uow: UnitOfWork, ids: IdGenerator, message: InboundMessage, speaker: Person, now: datetime
) -> Conversation:
    """A new personal chat, or a new group chat: the group is created and the sender joins."""
    if message.conversation_kind is ConversationKind.PERSONAL:
        conversation = Conversation(
            message.conversation, ConversationKind.PERSONAL, None, None, speaker.id
        )
    else:
        group = Group(
            ids.new_id(), message.conversation_name or "this group", message.conversation, now
        )
        uow.groups.add(group)
        uow.memberships.add(Membership(group.id, speaker.id, 1, now, None))
        conversation = Conversation(
            message.conversation, ConversationKind.GROUP, group.name, group.id, None
        )
    uow.conversations.add(conversation)
    return conversation


def current_member_ids(uow: UnitOfWork, group_id: str) -> list[str]:
    """Current members in position order (rounding ties go by this order)."""
    return [m.person_id for m in uow.memberships.for_group(group_id) if m.left_at is None]


def next_position(uow: UnitOfWork, group_id: str) -> int:
    return max((m.position for m in uow.memberships.for_group(group_id)), default=0) + 1


def group_chat(uow: UnitOfWork, group_id: str) -> Conversation | None:
    """The group chat a group is linked to, if any."""
    group = uow.groups.get(group_id)
    if group is None or group.channel_ref is None:
        return None
    return uow.conversations.get(group.channel_ref)
