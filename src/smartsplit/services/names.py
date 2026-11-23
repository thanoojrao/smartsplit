"""Turning a name as said into a person, for one speaker (SPEC section 6.1).

The speaker's nicknames come first, then the names of people they share a current group or a
past bill with. Several matches → ask which one; none → ask for a contact card or number.
Model output never supplies ids (SPEC 12.3): only these names are ever resolved.
"""

from collections.abc import Collection
from dataclasses import dataclass, replace

from smartsplit.domain import normalize_item_name
from smartsplit.domain.phone import normalize_phone
from smartsplit.domain.values import PersonRef
from smartsplit.ports.llm import NameablePerson
from smartsplit.ports.repository import UnitOfWork
from smartsplit.services.errors import NeedsClarificationError, NotAllowedError
from smartsplit.services.speaker import current_member_ids

SELF_WORDS = frozenset({"i", "me", "myself"})
MIN_PHONE_DIGITS = 7
"""Fewer digits than this is a name with a number in it, not a phone number."""


@dataclass(frozen=True, slots=True)
class Directory:
    """Everyone one speaker can name, with their names as the speaker would use them."""

    speaker_id: str
    by_nickname: dict[str, tuple[str, ...]]
    by_name: dict[str, tuple[str, ...]]
    by_phone: dict[str, str]
    people: tuple[NameablePerson, ...]
    group_name: str | None = None
    """Set for a group chat's directory: an unknown name is someone outside the group."""

    def resolve(self, said: PersonRef, region: str) -> str:
        """A person id, or NeedsClarificationError."""
        key = normalize_item_name(said)
        if key in SELF_WORDS:
            return self.speaker_id
        phone_match = self._by_phone(said, region)
        if phone_match:
            return phone_match
        matches = self.by_nickname.get(key) or self.by_name.get(key, ())
        if len(matches) == 1:
            return matches[0]
        if not matches and self.group_name is not None:
            raise NotAllowedError(
                f'{said} isn\'t in {self.group_name}. "add {said}" with a contact.'
            )
        raise NeedsClarificationError(said, matches)

    def _by_phone(self, said: str, region: str) -> str | None:
        if sum(ch.isdigit() for ch in said) < MIN_PHONE_DIGITS:
            return None
        try:
            return self.by_phone.get(normalize_phone(said, region))
        except ValueError:
            return None


def group_directory(uow: UnitOfWork, speaker_id: str, group_id: str) -> Directory:
    """The speaker's names for the people of one group, current and past."""
    ever = {m.person_id for m in uow.memberships.for_group(group_id)}
    group = uow.groups.get(group_id)
    found = directory(uow, speaker_id, ever)
    return replace(found, group_name=group.name if group else "this group")


def directory(uow: UnitOfWork, speaker_id: str, within: Collection[str] | None = None) -> Directory:
    """Build the speaker's directory from nicknames, current groups and past bills.

    `within` limits it to those people (in a group chat: everyone who was ever a member), so
    a group chat never asks about, or shows, someone from outside the group.
    """
    known: dict[str, set[str]] = {}
    by_nickname: dict[str, list[str]] = {}
    for nickname in uow.nicknames.for_owner(speaker_id):
        by_nickname.setdefault(nickname.name, []).append(nickname.subject_id)
        known.setdefault(nickname.subject_id, set()).add(nickname.name)
    others: set[str] = set()
    for membership in uow.memberships.for_person(speaker_id):
        if membership.left_at is None:
            others.update(current_member_ids(uow, membership.group_id))
    for bill in uow.bills.for_participant(speaker_id):
        others.update(bill.participants)
    others.update(known)
    others.add(speaker_id)  # "Sam and Raj", said by Raj, includes Raj
    if within is not None:
        allowed = {*within, speaker_id}
        others &= allowed
        known = {p: n for p, n in known.items() if p in allowed}
        by_nickname = {
            k: [p for p in v if p in allowed] for k, v in by_nickname.items() if set(v) & allowed
        }
    by_name: dict[str, list[str]] = {}
    by_phone: dict[str, str] = {}
    for person_id in sorted(others):
        person = uow.people.get(person_id)
        if person is None:
            continue
        by_phone[person.phone] = person_id
        name = normalize_item_name(person.display_name)
        known.setdefault(person_id, set()).add(name)
        if name and person_id not in by_nickname.get(name, []):
            by_name.setdefault(name, []).append(person_id)
    return Directory(
        speaker_id,
        {k: tuple(v) for k, v in by_nickname.items()},
        {k: tuple(v) for k, v in by_name.items()},
        by_phone,
        tuple(NameablePerson(p, tuple(sorted(n))) for p, n in sorted(known.items())),
    )
