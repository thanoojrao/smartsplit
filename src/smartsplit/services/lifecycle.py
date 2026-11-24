"""Where a draft goes next: ending it and starting the adder's next queued one (SPEC 10.4)."""

from dataclasses import replace

from smartsplit.domain.enums import DraftState
from smartsplit.domain.model import BillDraft
from smartsplit.domain.prompts import ChatRef
from smartsplit.domain.values import PersonalContext
from smartsplit.services.choosing import show_waiting
from smartsplit.services.drafting import change, drop_prompts, present
from smartsplit.services.turn import Turn


def finish(turn: Turn, draft: BillDraft, state: DraftState) -> BillDraft:
    """End the draft and drop whatever it was still asking."""
    ended = change(turn, draft, replace(draft, state=state))
    drop_prompts(turn, ended)
    return ended


def start_next(turn: Turn, ended: BillDraft) -> None:
    """The adder's oldest queued draft in that chat starts, and its summary is posted."""
    queued = [
        d
        for d in turn.uow.drafts.for_conversation(ended.conversation, (DraftState.QUEUED,))
        if d.added_by == ended.added_by
    ]
    if not queued:
        return
    draft = queued[0]
    waiting = draft.waiting_for or (
        isinstance(draft.context, PersonalContext) and draft.participants == (draft.added_by,)
    )
    state = DraftState.AWAITING_PEOPLE if waiting else DraftState.REVIEWING
    started = change(turn, draft, replace(draft, state=state))
    chat = turn.uow.conversations.get(started.conversation) or turn.conversation
    if state is DraftState.REVIEWING:
        turn.post(chat, f"Next up, the {started.description} bill:")
        present(turn, started)
    elif started.waiting_for:
        turn.post(chat, f"Next up, the {started.description} bill.")
        show_waiting(turn, started)
    else:
        ref = ChatRef("draft", started.id, started.version)
        turn.post(chat, f"Next up, the {started.description} bill. Who's it with?", (ref,))
