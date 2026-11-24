"""Who a name in a new bill means, and "Which Sam?" when it isn't sure (SPEC 6.1, 10.4; L5).

The model passes names it isn't sure of as they were said. Code looks each up for the bill's
adder (in a group chat, among the group's current members): a sure match (a number, a
nickname, a full name) joins the bill; anything else waits. A name with possible matches
gets a "which person" question listing them; the list is stored with the question, so the
number in the answer means exactly who was shown, whatever changed in between. A name that
matches nobody asks for a contact card or number (in a group chat: that they join first).
"""

from dataclasses import replace

from smartsplit.domain import normalize_item_name
from smartsplit.domain.enums import DraftState, PromptKind, PromptStatus
from smartsplit.domain.model import BillDraft, Nickname
from smartsplit.domain.phone import mask_phone
from smartsplit.domain.prompts import ChatRef, Prompt, PromptAnswer, WhichPersonPayload
from smartsplit.domain.values import PersonalContext
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.names import meant_by
from smartsplit.services.speaker import current_member_ids
from smartsplit.services.text import name_for
from smartsplit.services.turn import Turn


def sure_people(
    turn: Turn, adder_id: str, group_id: str | None, names: tuple[str, ...]
) -> tuple[list[str], tuple[str, ...]]:
    """The people the names surely mean, and the names still open."""
    sure: list[str] = []
    still: list[str] = []
    for name in names:
        meant, certain = _meant(turn, adder_id, group_id, name)
        if certain and len(meant) == 1:
            sure.append(meant[0])
        else:
            still.append(name)
    return sure, tuple(still)


def ask_which(turn: Turn, draft: BillDraft) -> None:
    """Say what a bill waiting for people needs, in code's words, and keep one open "which
    person" question per name that has candidates (a question for a name no longer waited on
    is dropped)."""
    open_ = {payload.name: (p, payload) for p, payload in which_questions(turn, draft)}
    for name, (prompt, _) in open_.items():
        if name not in draft.waiting_for:
            turn.uow.prompts.update(replace(prompt, status=PromptStatus.DROPPED))
    parts: list[str] = []
    refs: list[ChatRef] = [ChatRef("draft", draft.id, draft.version)]
    group_id = _group_of(draft)
    for name in draft.waiting_for:
        found = open_.get(name) or _new_question(turn, draft, name)
        if found is None:
            parts.append(_nobody(name, group_id))
            continue
        prompt, payload = found
        options = payload.options
        labels = option_labels(turn, draft.added_by, group_id, options)
        listed = [f"{n}. {label}" for n, label in enumerate(labels, start=1)]
        parts.append("\n".join([f"Which {name}?", *listed]))
        refs += [ChatRef("question", prompt.id), *(ChatRef("person", p) for p in options)]
    if parts:
        chat = turn.uow.conversations.get(draft.conversation) or turn.conversation
        turn.post(chat, "\n".join(parts), tuple(refs))


def pick(turn: Turn, prompt: Prompt, option: int) -> tuple[BillDraft, BillDraft]:
    """The draft before and after the adder picked someone from a "which person" list: they
    join the bill, the name stops waiting, and it becomes the adder's nickname for them."""
    payload = prompt.payload
    draft = turn.uow.drafts.get(prompt.draft_id or "")
    if (
        prompt.status is not PromptStatus.OPEN
        or not isinstance(payload, WhichPersonPayload)
        or draft is None
    ):
        raise NotAllowedError("That question was already settled.")
    if turn.speaker.id != draft.added_by:
        adder = name_for(turn.uow, None, draft.added_by)
        raise NotAllowedError(f"Only {adder} can say who they meant.")
    if not 1 <= option <= len(payload.options):
        raise NotAllowedError(f"Pick a number from 1 to {len(payload.options)}.")
    person_id = payload.options[option - 1]
    group_id = _group_of(draft)
    if group_id is not None and person_id not in current_member_ids(turn.uow, group_id):
        name = name_for(turn.uow, None, person_id)
        raise NotAllowedError(f"{name} isn't in this group any more.")
    key = normalize_item_name(payload.name)
    if key:
        turn.uow.nicknames.put(Nickname(draft.added_by, person_id, key))
    answered = PromptAnswer(turn.speaker.id, (), turn.now)
    turn.uow.prompts.update(
        replace(prompt, status=PromptStatus.ANSWERED, answers=(*prompt.answers, answered))
    )
    waiting = tuple(n for n in draft.waiting_for if n != payload.name)
    participants = tuple(dict.fromkeys([*draft.participants, person_id]))
    if group_id is not None:  # member order decides rounding ties
        order = current_member_ids(turn.uow, group_id)
        participants = tuple(p for p in order if p in participants)
    alone = isinstance(draft.context, PersonalContext) and len(participants) == 1
    state = draft.state
    if state is DraftState.AWAITING_PEOPLE and not waiting and not alone:
        state = DraftState.REVIEWING
    return draft, replace(draft, participants=participants, waiting_for=waiting, state=state)


def which_questions(turn: Turn, draft: BillDraft) -> list[tuple[Prompt, WhichPersonPayload]]:
    """The draft's open "which person" questions, with their lists."""
    return [
        (p, p.payload)
        for p in turn.uow.prompts.for_draft(draft.id)
        if isinstance(p.payload, WhichPersonPayload) and p.status is PromptStatus.OPEN
    ]


def option_labels(
    turn: Turn, adder_id: str, group_id: str | None, options: tuple[str, ...]
) -> list[str]:
    """How each option reads, always telling them apart: the name, in a personal chat the
    groups the adder shares with them, and a masked number when that still isn't enough."""
    labels = []
    for person_id in options:
        name = name_for(turn.uow, adder_id, person_id)
        groups = [] if group_id else known_from(turn, adder_id, person_id)
        labels.append(f"{name} ({', '.join(groups)})" if groups else name)
    clashing = {label for label in labels if labels.count(label) > 1}
    told_apart = []
    for person_id, label in zip(options, labels, strict=True):
        person = turn.uow.people.get(person_id)
        clash = label in clashing and person is not None
        told_apart.append(f"{label}, {mask_phone(person.phone)}" if clash and person else label)
    return told_apart


def known_from(turn: Turn, viewer_id: str, person_id: str) -> list[str]:
    """Groups both are currently in, by name."""
    mine = {m.group_id for m in turn.uow.memberships.for_person(viewer_id) if m.left_at is None}
    shared = []
    for membership in turn.uow.memberships.for_person(person_id):
        group = turn.uow.groups.get(membership.group_id)
        if membership.left_at is None and membership.group_id in mine and group is not None:
            shared.append(group.name)
    return sorted(shared)


def _new_question(
    turn: Turn, draft: BillDraft, name: str
) -> tuple[Prompt, WhichPersonPayload] | None:
    meant, _ = _meant(turn, draft.added_by, _group_of(draft), name)
    options = [p for p in meant if p != draft.added_by]
    if not options:
        return None
    labels = option_labels(turn, draft.added_by, _group_of(draft), tuple(options))
    ordered = tuple(p for _, p in sorted(zip(labels, options, strict=True)))
    payload = WhichPersonPayload(name, ordered)
    prompt = Prompt(
        turn.ids.new_id(),
        draft.conversation,
        draft.id,
        PromptKind.WHICH_PERSON,
        payload,
        PromptStatus.OPEN,
        draft.added_by,
        turn.speaker.id,
        turn.now,
        None,
        (),
    )
    turn.uow.prompts.add(prompt)
    return prompt, payload


def _meant(
    turn: Turn, adder_id: str, group_id: str | None, name: str
) -> tuple[tuple[str, ...], bool]:
    within = current_member_ids(turn.uow, group_id) if group_id else None
    return meant_by(turn.uow, adder_id, name, turn.settings.default_region, within)


def _nobody(name: str, group_id: str | None) -> str:
    if group_id is not None:
        return f"I can't find {name} in this group. If they're in this chat, they can say \"join\"."
    return f"I don't know {name} yet: send their contact card or number."


def _group_of(draft: BillDraft) -> str | None:
    return None if isinstance(draft.context, PersonalContext) else draft.context.group_id
