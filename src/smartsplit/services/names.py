"""Turning a name as said into a person, for one speaker (SPEC section 6.1).

The speaker's nicknames come first, then the names of people they share a current group or a
past bill with. Several matches → ask which one; none → ask for a contact card or number.
Model output never supplies ids (SPEC 12.3): only these names are ever resolved.
"""

from dataclasses import dataclass

from smartsplit.domain import normalize_item_name
from smartsplit.domain.phone import normalize_phone
from smartsplit.domain.values import PersonRef
from smartsplit.ports.llm import NameablePerson
from smartsplit.ports.repository import UnitOfWork
from smartsplit.services.errors import NeedsClarificationError
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
        raise NeedsClarificationError(said, matches)

    def _by_phone(self, said: str, region: str) -> str | None:
        if sum(ch.isdigit() for ch in said) < MIN_PHONE_DIGITS:
            return None
        try:
            return self.by_phone.get(normalize_phone(said, region))
        except ValueError:
            return None


def directory(uow: UnitOfWork, speaker_id: str) -> Directory:
    """Build the speaker's directory from nicknames, current groups and past bills."""
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
