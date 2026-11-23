"""Turning a tool's handles into the things they stand for, for the speaker of this turn
(SPEC 8.2, 12.3). Only handles issued this turn resolve; anything else is refused."""

from collections.abc import Sequence

from smartsplit.domain.enums import DraftState
from smartsplit.domain.model import Bill, BillDraft
from smartsplit.domain.prompts import Prompt
from smartsplit.ports.repository import OPEN_DRAFT_STATES
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.text import name_for
from smartsplit.services.turn import Turn


def person(turn: Turn, handle: str) -> str:
    return turn.handles.resolve(handle, "person")


def people(turn: Turn, handles: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(person(turn, h) for h in handles))


def maybe_person(turn: Turn, handle: str | None) -> str | None:
    return person(turn, handle) if handle else None


def person_handle(turn: Turn, person_id: str) -> str:
    """A handle for someone a tool result mentions (valid for the rest of the turn)."""
    return turn.handles.issue("person", person_id, name_for(turn.uow, turn.viewer, person_id))


def draft(turn: Turn, handle: str) -> BillDraft:
    """An open draft of this chat."""
    found = turn.uow.drafts.get(turn.handles.resolve(handle, "draft"))
    if (
        found is None
        or found.conversation != turn.conversation.key
        or found.state not in OPEN_DRAFT_STATES
    ):
        raise NotAllowedError("That bill isn't open here any more.")
    return found


def draft_handle(turn: Turn, found: BillDraft) -> str:
    return turn.handles.issue("draft", found.id, found.description)


def bill(turn: Turn, handle: str) -> Bill:
    found = turn.uow.bills.get(turn.handles.resolve(handle, "bill"))
    if found is None:
        raise NotAllowedError("I can't find that bill.")
    return found


def bill_handle(turn: Turn, found: Bill) -> str:
    return turn.handles.issue("bill", found.id, found.description)


def group(turn: Turn, handle: str) -> str:
    return turn.handles.resolve(handle, "group")


def question(turn: Turn, handle: str) -> Prompt:
    found = turn.uow.prompts.get(turn.handles.resolve(handle, "question"))
    if found is None or found.conversation != turn.conversation.key:
        raise NotAllowedError("That question isn't open here.")
    return found


def action(turn: Turn, handle: str) -> str:
    return turn.handles.resolve(handle, "action")


def payment(turn: Turn, handle: str | None) -> str | None:
    return turn.handles.resolve(handle, "payment") if handle else None


def reviewable(turn: Turn, handle: str) -> BillDraft:
    """An open draft of this chat that may be edited now: not queued, and in a personal chat
    the speaker's own."""
    found = draft(turn, handle)
    if found.state is DraftState.QUEUED:
        raise NotAllowedError(
            f"The {found.description} bill waits until the one before it is done."
        )
    if not turn.in_group and found.added_by != turn.speaker.id:
        raise NotAllowedError("That's someone else's bill.")
    return found
