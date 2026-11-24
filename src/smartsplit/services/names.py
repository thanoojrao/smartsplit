"""Who a speaker can name, and who a name means to them (SPEC section 6.1).

The speaker's nicknames come first, then the names of people they share a current group or a
past bill with. In a group chat only the people who were ever in that group count, so a
group chat never shows or finds anyone from outside it.
"""

from collections.abc import Collection

from smartsplit.domain import normalize_item_name
from smartsplit.domain.phone import normalize_phone
from smartsplit.ports.repository import UnitOfWork
from smartsplit.services.speaker import current_member_ids

MIN_PHONE_DIGITS = 7
"""Fewer digits than this is a name with a number in it, not a phone number."""


def known_people(
    uow: UnitOfWork, speaker_id: str, within: Collection[str] | None = None
) -> list[str]:
    """Everyone the speaker can name, most recent bill partners first, then the rest."""
    recent = [
        p for bill in reversed(uow.bills.for_participant(speaker_id)) for p in bill.participants
    ]
    others: list[str] = [n.subject_id for n in uow.nicknames.for_owner(speaker_id)]
    for membership in uow.memberships.for_person(speaker_id):
        if membership.left_at is None:
            others += current_member_ids(uow, membership.group_id)
    ordered = list(dict.fromkeys([speaker_id, *recent, *sorted(set(others))]))
    if within is not None:
        allowed = {*within, speaker_id}
        ordered = [p for p in ordered if p in allowed]
    return [p for p in ordered if uow.people.get(p) is not None]


def candidates(
    uow: UnitOfWork,
    speaker_id: str,
    said: str,
    region: str,
    within: Collection[str] | None = None,
) -> tuple[str, ...]:
    """Who `said` can mean: a number, else the speaker's nickname, else display names."""
    return meant_by(uow, speaker_id, said, region, within)[0]


def meant_by(
    uow: UnitOfWork,
    speaker_id: str,
    said: str,
    region: str,
    within: Collection[str] | None = None,
) -> tuple[tuple[str, ...], bool]:
    """Who `said` can mean, and whether that is sure: a number, the speaker's nickname or a
    full display name is; a word of a longer name ("Sam" for "Sam Rao") isn't."""
    people = known_people(uow, speaker_id, within)
    by_phone = _by_phone(uow, people, said, region)
    if by_phone is not None:
        return (by_phone,), True
    key = normalize_item_name(said)
    if not key:
        return (), False
    nicknamed = [
        n.subject_id
        for n in uow.nicknames.for_owner(speaker_id)
        if n.name == key and n.subject_id in people
    ]
    if nicknamed:
        return tuple(dict.fromkeys(nicknamed)), True
    exact: list[str] = []
    partial: list[str] = []
    for person_id in people:
        person = uow.people.get(person_id)
        name = normalize_item_name(person.display_name) if person else ""
        if name == key:
            exact.append(person_id)
        elif key in name.split():
            partial.append(person_id)
    return (tuple(exact), True) if exact else (tuple(partial), False)


def _by_phone(uow: UnitOfWork, people: Collection[str], said: str, region: str) -> str | None:
    if sum(ch.isdigit() for ch in said) < MIN_PHONE_DIGITS:
        return None
    try:
        phone = normalize_phone(said, region)
    except ValueError:
        return None
    person = uow.people.by_phone(phone)
    return person.id if person is not None and person.id in people else None
