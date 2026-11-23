"""Joining, adding, leaving, nicknames and number fixes (SPEC 6.1, 10.3).

Membership changes need no "yes": they are announced in the group instead (SPEC 12.3).
"""

from dataclasses import replace

from smartsplit.domain import normalize_item_name
from smartsplit.domain.enums import DraftState, PromptStatus
from smartsplit.domain.model import BillDraft, Membership, Nickname, Person
from smartsplit.domain.phone import mask_phone, normalize_phone
from smartsplit.domain.prompts import ChatRef, EngineQuestionPayload
from smartsplit.domain.values import GroupContext
from smartsplit.services.drafting import change, present
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.lifecycle import finish, start_next
from smartsplit.services.speaker import current_member_ids, next_position
from smartsplit.services.text import name_for
from smartsplit.services.turn import Turn


def group_id_of(turn: Turn) -> str:
    if turn.conversation.group_id is None:
        raise NotAllowedError("That only works in a group chat.")
    return turn.conversation.group_id


def join(turn: Turn) -> None:
    """ "join": a member from now on, never in older bills (B5)."""
    group_id = group_id_of(turn)
    if turn.speaker.id in current_member_ids(turn.uow, group_id):
        turn.show("You're already in.")
        return
    add_member(turn, group_id, turn.speaker.id)
    turn.show(f"{turn.speaker.display_name} joined {turn.conversation.name}.")


def add_member(turn: Turn, group_id: str, person_id: str) -> None:
    turn.acted = True
    turn.uow.memberships.add(
        Membership(group_id, person_id, next_position(turn.uow, group_id), turn.now, None)
    )


def add_person(turn: Turn, name: str, phone: str) -> Person:
    """ "add Priya" with a contact card or number: no name-only people (A5, A11). In a group
    chat they also become a member, announced."""
    person = person_with_phone(turn, name, phone)
    if person.id != turn.speaker.id:
        _nickname(turn, person.id, name)
    if not turn.in_group:
        turn.show(f"Got it: {name} ({mask_phone(person.phone)}).", (ChatRef("person", person.id),))
        return person
    group_id = group_id_of(turn)
    members = current_member_ids(turn.uow, group_id)
    if person.id in members:
        turn.show(f"{name} is already in.")
        return person
    add_member(turn, group_id, person.id)
    turn.show(
        f"{turn.speaker.display_name} added {name} to {turn.conversation.name}.",
        (ChatRef("person", person.id),),
    )
    return person


def person_with_phone(turn: Turn, name: str, phone: str) -> Person:
    """The person with this number, or a new one who hasn't used the bot yet."""
    try:
        number = normalize_phone(phone, turn.settings.default_region)
    except ValueError as error:
        raise NotAllowedError(f"{phone} doesn't look like a phone number.") from error
    existing = turn.uow.people.by_phone(number)
    if existing is not None:
        return existing
    if not name.strip():
        raise NotAllowedError("What's their name?")
    person = Person(turn.ids.new_id(), name.strip(), number, turn.speaker.id, True, False, turn.now)
    turn.uow.people.add(person)
    turn.acted = True
    return person


def member_left(turn: Turn, person_id: str) -> None:
    """ "Raj moved out" or a left-the-chat event: announced; balances stay (B2, B3)."""
    group_id = group_id_of(turn)
    if person_id not in current_member_ids(turn.uow, group_id):
        turn.show(f"{name_for(turn.uow, None, person_id)} isn't in {turn.conversation.name}.")
        return
    turn.uow.memberships.end(group_id, person_id, turn.now)
    turn.acted = True
    name = name_for(turn.uow, None, person_id)
    turn.show(f"{name} left {turn.conversation.name}. Their balance stays until it's settled.")
    for draft in turn.uow.drafts.open_in_context(GroupContext(group_id)):
        _leave_draft(turn, draft, person_id)


def _leave_draft(turn: Turn, draft: BillDraft, person_id: str) -> None:
    """The adder leaving cancels the draft; anyone else is taken out and it is re-split."""
    here = draft.conversation == turn.conversation.key
    if draft.added_by == person_id:
        ended = finish(turn, draft, DraftState.CANCELLED)
        _tell(turn, draft, f"The {draft.description} bill was cancelled: whoever added it left.")
        start_next(turn, ended)
        return
    if person_id not in draft.participants:
        return
    for prompt in turn.uow.prompts.for_draft(draft.id):
        payload = prompt.payload
        asked_about = isinstance(payload, EngineQuestionPayload) and payload.member_id == person_id
        if prompt.status is PromptStatus.OPEN and (asked_about or prompt.asked_of == person_id):
            turn.uow.prompts.update(replace(prompt, status=PromptStatus.DROPPED))
    payer = draft.added_by if draft.payer_id == person_id else draft.payer_id
    left = replace(
        draft, participants=tuple(p for p in draft.participants if p != person_id), payer_id=payer
    )
    changed = change(turn, draft, left)
    if changed.state is not DraftState.REVIEWING:
        return
    if here:
        present(turn, changed)
    else:
        name = name_for(turn.uow, None, person_id)
        _tell(
            turn,
            draft,
            f"{name} left {turn.conversation.name}, so they're out of {draft.description}.",
        )


def _tell(turn: Turn, draft: BillDraft, text: str) -> None:
    """Say it in the draft's own chat, which for a filed bill is someone's personal chat."""
    if draft.conversation == turn.conversation.key:
        turn.show(text)
        return
    chat = turn.uow.conversations.get(draft.conversation)
    if chat is not None:
        turn.post(chat, text)


def set_nickname(turn: Turn, person_id: str, nickname: str) -> None:
    """Each nickname works for its owner only (A9); it is also how "which Sam?" is
    remembered (SPEC 6.1)."""
    if not normalize_item_name(nickname):
        raise NotAllowedError("What should I call them?")
    _nickname(turn, person_id, nickname)
    turn.acted = True


def _nickname(turn: Turn, person_id: str, name: str) -> None:
    key = normalize_item_name(name)
    if key:
        turn.uow.nicknames.put(Nickname(turn.speaker.id, person_id, key))


def correct_number(turn: Turn, person_id: str, phone: str) -> None:
    """Only by whoever gave the number, and only until that person uses the bot (A12)."""
    person = turn.uow.people.get(person_id)
    if person is None or person.has_used_bot:
        raise NotAllowedError("Their number came from their own chat, so it can't be changed.")
    if person.phone_added_by != turn.speaker.id:
        raise NotAllowedError("Only whoever gave me their number can correct it.")
    try:
        number = normalize_phone(phone, turn.settings.default_region)
    except ValueError as error:
        raise NotAllowedError(f"{phone} doesn't look like a phone number.") from error
    taken = turn.uow.people.by_phone(number)
    if taken is not None and taken.id != person.id:
        raise NotAllowedError("Someone else already has that number.")
    turn.uow.people.update(replace(person, phone=number, phone_added_by=turn.speaker.id))
    turn.acted = True
    turn.show(f"Updated: {name_for(turn.uow, turn.speaker.id, person.id)} is {mask_phone(number)}.")
