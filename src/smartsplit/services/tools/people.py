"""People tools: adding someone, joining, leaving, nicknames, number fixes (SPEC 6.1, 10.3).

Membership changes are done at once and announced in the group: announcing is the safeguard
(SPEC 8.4).
"""

from typing import Any

from smartsplit.domain.tools import AddPerson, CorrectNumber, JoinGroup, MemberLeft, SetNickname
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.membership import (
    add_member,
    add_person,
    correct_number,
    join,
    member_left,
    set_nickname,
)
from smartsplit.services.speaker import current_member_ids
from smartsplit.services.text import name_for
from smartsplit.services.tools import refs
from smartsplit.services.tools.registry import Data, Tool
from smartsplit.services.turn import Turn


def _add_person(turn: Turn, args: AddPerson) -> Data:
    """A name with a number, this message's contact card, or someone already known (a
    mention). In a group chat they also join it."""
    if args.mention is not None:
        person_id = refs.person(turn, args.mention)
        group_id = turn.conversation.group_id
        if group_id is None:
            raise NotAllowedError("Mentions only add people in a group chat.")
        if person_id not in current_member_ids(turn.uow, group_id):
            add_member(turn, group_id, person_id)
            name = name_for(turn.uow, None, person_id)
            turn.show(f"{turn.speaker.display_name} added {name} to {turn.conversation.name}.")
        return {"person": refs.person_handle(turn, person_id)}
    phone = turn.contact.phone if args.use_contact and turn.contact else args.phone
    if not phone:
        raise NotAllowedError(f"I need {args.name}'s contact card or phone number.")
    person = add_person(turn, args.name, phone)
    return {"person": refs.person_handle(turn, person.id), "name": args.name}


def _join_group(turn: Turn, args: JoinGroup) -> Data:
    join(turn)
    return {}


def _member_left(turn: Turn, args: MemberLeft) -> Data:
    member_left(turn, refs.person(turn, args.person))
    return {}


def _set_nickname(turn: Turn, args: SetNickname) -> Data:
    person_id = refs.person(turn, args.person)
    set_nickname(turn, person_id, args.nickname)
    return {"person": refs.person_handle(turn, person_id)}


def _correct_number(turn: Turn, args: CorrectNumber) -> Data:
    correct_number(turn, refs.person(turn, args.person), args.phone)
    return {}


PEOPLE_TOOLS: tuple[Tool[Any], ...] = (
    Tool(
        "add_person",
        "Add someone: a name with a phone number, this message's contact card (use_contact), "
        "or a mentioned person. In a group chat they join the group too.",
        AddPerson,
        _add_person,
    ),
    Tool(
        "join_group", "The speaker joins this group chat's group.", JoinGroup, _join_group, "anyone"
    ),
    Tool(
        "member_left",
        'Someone moved out or left (or "me"): their membership ends; balances stay.',
        MemberLeft,
        _member_left,
    ),
    Tool(
        "set_nickname",
        "Remember what the speaker calls someone.",
        SetNickname,
        _set_nickname,
        "anyone",
    ),
    Tool(
        "correct_number",
        "Fix a number the speaker gave for someone who hasn't used the bot yet.",
        CorrectNumber,
        _correct_number,
    ),
)
