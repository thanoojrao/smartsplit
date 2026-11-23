"""Where a draft goes next: ending it, starting the queued one, asking who it's with (10.4)."""

from collections import Counter
from dataclasses import replace

from smartsplit.domain.enums import DraftState, PromptKind, PromptStatus
from smartsplit.domain.model import BillDraft
from smartsplit.domain.prompts import ListOption, WhoWithPayload
from smartsplit.domain.values import PersonalContext
from smartsplit.services.prompting import drop, open_prompt
from smartsplit.services.review import save
from smartsplit.services.text import name_for
from smartsplit.services.turn import Turn

WHO_WITH_OPTIONS = 6


def finish(turn: Turn, draft: BillDraft, state: DraftState) -> None:
    """End the draft and drop whatever it was still asking."""
    save(turn, draft, replace(draft, state=state))
    for prompt in turn.uow.prompts.for_draft(draft.id):
        if prompt.status in (PromptStatus.OPEN, PromptStatus.PENDING):
            drop(turn, prompt)


def start_next(turn: Turn, ended: BillDraft) -> None:
    """The oldest queued draft in that chat starts; its receipt is read after this commit."""
    queued = turn.uow.drafts.for_conversation(ended.conversation, (DraftState.QUEUED,))
    if queued:
        begin(turn, queued[0])


def begin(turn: Turn, draft: BillDraft) -> None:
    """A queued draft's turn: read it, or first ask who it's with."""
    if isinstance(draft.context, PersonalContext) and draft.participants == (draft.added_by,):
        waiting = replace(draft, state=DraftState.AWAITING_PEOPLE)
        save(turn, draft, waiting)
        ask_who_with(turn, waiting)
        return
    save(turn, draft, replace(draft, state=DraftState.PARSING))
    turn.to_parse.append(draft.id)


def ask_who_with(turn: Turn, draft: BillDraft) -> None:
    """A numbered list of the speaker's groups and most frequent split partners (D2)."""
    options = _who_with_options(turn)
    open_prompt(turn, draft.id, PromptKind.WHO_WITH, WhoWithPayload(options), draft.added_by)
    listed = [f"{o.n}. {o.label}" for o in options]
    turn.reply("\n".join(["Who's this with?", *listed, 'Or say names: "with Sam and Raj".']))


def _who_with_options(turn: Turn) -> tuple[ListOption, ...]:
    uow, me = turn.uow, turn.speaker.id
    options: list[ListOption] = []
    for membership in uow.memberships.for_person(me):
        group = uow.groups.get(membership.group_id)
        if membership.left_at is None and group is not None:
            options.append(ListOption(len(options) + 1, (), group.id, group.name))
    partners = Counter(
        p
        for bill in uow.bills.for_participant(me)
        if isinstance(bill.context, PersonalContext)
        for p in bill.participants
        if p != me
    )
    for person_id, _ in partners.most_common():
        options.append(
            ListOption(len(options) + 1, (person_id,), None, name_for(uow, me, person_id))
        )
    return tuple(options[:WHO_WITH_OPTIONS])
