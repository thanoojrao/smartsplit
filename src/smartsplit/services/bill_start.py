"""Starting a bill: who it's with, queueing, duplicates and item matching (SPEC 10.4).

A draft is created even while some named people are still unknown (`awaiting_people`), so a
photo is never lost; a personal bill with nobody named waits the same way for "who's this
with?". A second bill from the same adder in the same chat waits as `queued`.
"""

from dataclasses import dataclass, replace
from datetime import date

from smartsplit.domain.enums import DraftState
from smartsplit.domain.model import BillDraft, DuplicateRef, LineItem, Receipt
from smartsplit.domain.values import Context, GroupContext, Override, PersonalContext
from smartsplit.engine import DuplicateCandidate, find_likely_duplicate
from smartsplit.services.bill_changes import is_live
from smartsplit.services.drafting import (
    Totals,
    Who,
    active_draft_of,
    change,
    new_draft,
    present,
    queued_of,
)
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.matching import load_match_inputs, match_lines, remember_matches
from smartsplit.services.scopes import local_scope_for
from smartsplit.services.speaker import current_member_ids
from smartsplit.services.turn import Turn


@dataclass(frozen=True, slots=True)
class WhoSaid:
    """Who a new bill is with, as the speaker said it (people as ids)."""

    people: tuple[str, ...] = ()
    everyone_except: tuple[str, ...] = ()
    payer: str | None = None
    owes_all: str | None = None
    unknown_names: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class NewBill:
    description: str
    lines: tuple[LineItem, ...]
    totals: Totals
    purchased_at: date | None = None
    receipt_id: str | None = None
    overrides: tuple[tuple[str, Override], ...] = ()


def context_here(turn: Turn) -> Context:
    group_id = turn.conversation.group_id
    return GroupContext(group_id) if group_id else PersonalContext()


def resolve_who(turn: Turn, said: WhoSaid) -> Who:
    """Group: all current members by default, or the subset named; only current members (P1).
    Personal: the speaker plus the people named; the speaker always pays (P5)."""
    me = turn.speaker.id
    group_id = turn.conversation.group_id
    if group_id is None:
        if said.payer not in (None, me):
            raise NotAllowedError("In your own splits you're always the one who paid.")
        participants = tuple(dict.fromkeys([me, *said.people]))
        payer = me
    else:
        members = current_member_ids(turn.uow, group_id)
        chosen = list(said.people) or members
        if any(p not in members for p in chosen):
            raise NotAllowedError("Only current members of this group can be in its bills.")
        participants = tuple(m for m in members if m in chosen and m not in said.everyone_except)
        payer = said.payer or me
        if payer not in members:
            raise NotAllowedError("The payer has to be a current member of this group.")
    if not participants:
        raise NotAllowedError("That leaves nobody in the bill.")
    if said.owes_all is not None and said.owes_all not in participants:
        raise NotAllowedError("Whoever owes all of it has to be in the bill.")
    return Who(participants, payer, said.owes_all)


def receipt_lines(turn: Turn, receipt: Receipt, context: Context) -> tuple[LineItem, ...]:
    """The receipt's lines with item keys for where the bill lives (SPEC 6.4)."""
    if turn.canonicalizer is None:
        raise NotAllowedError("I can't read item names right now.")
    inputs = load_match_inputs(turn.uow, local_scope_for(context, turn.speaker.id))
    matched = match_lines(
        receipt.line_items, inputs, turn.canonicalizer, turn.settings.fuzzy_threshold
    )
    remember_matches(turn.uow, matched)
    return matched.lines


def start_bill(turn: Turn, said: WhoSaid, bill: NewBill) -> BillDraft:
    """Create the draft (reviewing, waiting for people, or queued) and show what's next."""
    who = resolve_who(turn, said)
    context = context_here(turn)
    waiting = bool(said.unknown_names) or (
        isinstance(context, PersonalContext) and len(who.participants) == 1
    )
    if active_draft_of(turn, turn.speaker.id) is not None:
        if len(queued_of(turn, turn.speaker.id)) >= turn.settings.max_queued_drafts:
            raise NotAllowedError("There are already a few bills waiting. Finish one first.")
        state = DraftState.QUEUED
    else:
        state = DraftState.AWAITING_PEOPLE if waiting else DraftState.REVIEWING
    draft = new_draft(
        turn,
        context=context,
        who=who,
        description=bill.description,
        lines=bill.lines,
        totals=bill.totals,
        state=state,
        purchased_at=bill.purchased_at,
        receipt_id=bill.receipt_id,
        overrides=bill.overrides,
        waiting_for=said.unknown_names,
    )
    if state is DraftState.REVIEWING:
        draft = with_duplicate_check(turn, draft)
        present(turn, draft)
    return draft


def with_duplicate_check(turn: Turn, draft: BillDraft) -> BillDraft:
    """Mark a same-total bill or open draft in the same group (or between the same people)
    within a few days, wherever that draft is being reviewed (C11)."""
    found = likely_duplicate(turn, draft)
    if found == draft.possible_duplicate_of:
        return draft
    return change(turn, draft, replace(draft, possible_duplicate_of=found))


def likely_duplicate(turn: Turn, draft: BillDraft) -> DuplicateRef | None:
    uow = turn.uow
    candidates = [
        DuplicateCandidate(
            b.id, False, b.context, b.total_cents, b.purchased_at, frozenset(b.participants)
        )
        for b in uow.bills.for_context(draft.context)
        if is_live(uow, b)
    ]
    candidates += [
        DuplicateCandidate(
            d.id, True, d.context, d.total_cents, d.purchased_at, frozenset(d.participants)
        )
        for d in uow.drafts.open_in_context(draft.context)
        if d.id != draft.id and d.lines
    ]
    found = find_likely_duplicate(
        draft.context,
        draft.total_cents,
        draft.purchased_at or turn.today,
        frozenset(draft.participants),
        candidates,
        window_days=turn.settings.duplicate_window_days,
    )
    if found is None:
        return None
    return DuplicateRef(None, found.id) if found.is_draft else DuplicateRef(found.id, None)
