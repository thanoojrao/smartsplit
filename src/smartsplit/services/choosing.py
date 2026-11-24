"""Who a name in a new bill means, and the numbered choice when it means several people
(SPEC 6.1, 10.4; use case L5).

The model passes names it isn't sure of as they were said. Code finds who they can mean: one
match joins the bill; several are listed by code ("Which Sam? 1. Sam (Flat 4B) 2. Sam (Goa
trip)"), and the model only picks a number; nobody needs a contact card or number. The list
is rebuilt the same way when the answer comes, so the numbers mean the same people.
"""

from smartsplit.domain.model import BillDraft
from smartsplit.domain.prompts import ChatRef
from smartsplit.services.names import candidates
from smartsplit.services.text import name_for
from smartsplit.services.turn import Turn


def choices(turn: Turn, name: str) -> list[str]:
    """Everyone the name can mean to the speaker, here, in a stable order: by how each is
    listed, then by id."""
    group_id = turn.conversation.group_id
    within = (
        {m.person_id for m in turn.uow.memberships.for_group(group_id) if m.left_at is None}
        if group_id
        else None
    )
    found = candidates(turn.uow, turn.speaker.id, name, turn.settings.default_region, within)
    return sorted(found, key=lambda person_id: (option_label(turn, person_id), person_id))


def option_label(turn: Turn, person_id: str) -> str:
    """ "Sam (Flat 4B, Goa trip)": the name and the groups the speaker shares with them."""
    name = name_for(turn.uow, turn.viewer, person_id)
    groups = known_from(turn, person_id)
    return f"{name} ({', '.join(groups)})" if groups else name


def known_from(turn: Turn, person_id: str) -> list[str]:
    """Groups both are in (only this one, in a group chat), so "which Sam?" can be asked."""
    if turn.conversation.group_id is not None:
        return [turn.conversation.name or "this group"]
    mine = {
        m.group_id for m in turn.uow.memberships.for_person(turn.speaker.id) if m.left_at is None
    }
    shared = []
    for membership in turn.uow.memberships.for_person(person_id):
        group = turn.uow.groups.get(membership.group_id)
        if membership.left_at is None and membership.group_id in mine and group is not None:
            shared.append(group.name)
    return sorted(shared)


def sort_names(turn: Turn, names: tuple[str, ...]) -> tuple[list[str], tuple[str, ...]]:
    """The people the names surely mean, and the names still open (no match, or several)."""
    sure: list[str] = []
    still: list[str] = []
    for name in names:
        meant = choices(turn, name)
        if len(meant) == 1:
            sure.append(meant[0])
        else:
            still.append(name)
    return sure, tuple(still)


def show_waiting(turn: Turn, draft: BillDraft) -> None:
    """What a bill waiting for people needs, worded by code: a numbered choice for a name
    that means several people, a contact card or number for one that means nobody."""
    parts: list[str] = []
    refs: list[ChatRef] = [ChatRef("draft", draft.id, draft.version)]
    for name in draft.waiting_for:
        meant = choices(turn, name)
        if len(meant) > 1:
            options = [f"{n}. {option_label(turn, p)}" for n, p in enumerate(meant, start=1)]
            parts.append("\n".join([f"Which {name}?", *options]))
            refs += [ChatRef("person", p) for p in meant]
        else:
            parts.append(f"I don't know {name} yet: send their contact card or number.")
    if parts:
        chat = turn.uow.conversations.get(draft.conversation) or turn.conversation
        turn.post(chat, "\n".join(parts), tuple(refs))
