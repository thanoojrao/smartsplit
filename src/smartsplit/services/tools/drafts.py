"""Draft tools: starting a bill, choosing people, review edits, answers, filing, saving and
cancelling (SPEC 8.3, 8.4, 10.4)."""

from dataclasses import replace
from typing import Any

from smartsplit.domain.enums import DraftState, PhotoOutcome
from smartsplit.domain.model import BillDraft, PhotoRead
from smartsplit.domain.tools import (
    AddManualBill,
    AddPeople,
    EditDraft,
    SetDraftPeople,
    StartReceipt,
)
from smartsplit.domain.values import Override, PersonalContext
from smartsplit.services.bill_start import (
    NewBill,
    WhoSaid,
    context_here,
    receipt_lines,
    resolve_who,
    start_bill,
    with_duplicate_check,
)
from smartsplit.services.drafting import (
    Totals,
    change,
    manual_line,
    present,
)
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.membership import set_nickname
from smartsplit.services.money_args import parse_money
from smartsplit.services.names import candidates
from smartsplit.services.review import (
    apply_change,
    exact_override,
)
from smartsplit.services.tools import refs
from smartsplit.services.tools.registry import Data, Tool
from smartsplit.services.tools.settling import file_draft
from smartsplit.services.turn import Turn


def _started(turn: Turn, draft: BillDraft) -> Data:
    data: dict[str, object] = {"draft": refs.draft_handle(turn, draft), "state": draft.state.value}
    if draft.waiting_for:
        data["still_to_find"] = list(draft.waiting_for)
    if draft.state is DraftState.AWAITING_PEOPLE and not draft.waiting_for:
        data["next"] = "ask who it's with"
    if draft.state is DraftState.QUEUED:
        data["next"] = "it waits until the speaker's current bill is saved or cancelled"
    return data


def _photo(turn: Turn) -> PhotoRead:
    """This message's receipt photo, else the sender's last unused one here (10 minutes)."""
    uow = turn.uow
    mine = uow.photos.get(turn.conversation.key, turn.message_id)
    if mine is not None and mine.outcome is PhotoOutcome.RECEIPT and mine.used_by_draft_id is None:
        return mine
    since = turn.now - turn.settings.photo_pickup_within
    found = uow.photos.latest_unused(turn.conversation.key, turn.speaker.id, since)
    if found is None:
        raise NotAllowedError("There's no receipt photo from you here in the last 10 minutes.")
    return found


def _who(
    turn: Turn, people: tuple[str, ...], everyone_except: tuple[str, ...], **more: Any
) -> WhoSaid:
    return WhoSaid(refs.people(turn, people), refs.people(turn, everyone_except), **more)


def _start_receipt(turn: Turn, args: StartReceipt) -> Data:
    photo = _photo(turn)
    receipt = turn.uow.receipts.get(photo.receipt_id or "")
    if receipt is None:
        raise NotAllowedError("That photo wasn't a receipt I could read.")
    said = _who(
        turn,
        args.people,
        args.everyone_except,
        payer=refs.maybe_person(turn, args.payer),
        owes_all=refs.maybe_person(turn, args.owes_all),
        unknown_names=args.unknown_names,
    )
    lines = receipt_lines(turn, receipt, context_here(turn))
    totals = Totals(receipt.tax_cents, receipt.other_adjustments_cents, receipt.total_cents)
    bill = NewBill(receipt.merchant or "Receipt", lines, totals, receipt.purchased_at, receipt.id)
    draft = start_bill(turn, said, bill)
    turn.uow.photos.update(replace(photo, used_by_draft_id=draft.id))
    for warning in receipt.warnings:
        turn.show(warning)
    return _started(turn, draft)


def _add_manual_bill(turn: Turn, args: AddManualBill) -> Data:
    """ "electricity 1800, split all": one line, reviewed like a receipt (C4)."""
    cents = parse_money(args.amount, turn.settings.max_amount_cents)
    description = args.description.strip() or "Bill"
    exact_people = tuple(e.person for e in args.exact)
    said = _who(
        turn,
        args.people or (exact_people if turn.conversation.group_id is None else ()),
        args.everyone_except,
        payer=refs.maybe_person(turn, args.payer),
        owes_all=refs.maybe_person(turn, args.owes_all),
        unknown_names=args.unknown_names,
    )
    line = manual_line(turn, description, cents, 1)
    overrides: tuple[tuple[str, Override], ...] = ()
    if args.exact:
        participants = resolve_who(turn, said).participants
        override = exact_override(
            turn, cents, args.exact, participants, lambda h: refs.person(turn, h)
        )
        overrides = ((line.id, override),)
    bill = NewBill(description, (line,), Totals(0, 0, cents), args.purchased_on, None, overrides)
    return _started(turn, start_bill(turn, said, bill))


def _set_draft_people(turn: Turn, args: SetDraftPeople) -> Data:
    """The answer to "who's this with?": people, or a group name (files it there)."""
    found = refs.reviewable(turn, args.draft)
    if args.group is not None:
        return file_draft(turn, found, refs.group(turn, args.group))
    payer = found.payer_id if turn.in_group else None
    said = _who(turn, args.people, args.everyone_except, payer=payer, owes_all=found.owes_all_id)
    who = resolve_who(turn, said)
    if not turn.in_group and len(who.participants) == 1:
        raise NotAllowedError("Who else is in it?")
    moved = replace(
        found, participants=who.participants, waiting_for=(), state=DraftState.REVIEWING
    )
    shown = with_duplicate_check(turn, change(turn, found, moved))
    present(turn, shown)
    return {"draft": refs.draft_handle(turn, shown), "state": shown.state.value}


def _edit_draft(turn: Turn, args: EditDraft) -> Data:
    found = refs.reviewable(turn, args.draft)
    edited = apply_change(turn, found, args.change, lambda h: refs.person(turn, h))
    if isinstance(args.change, AddPeople):
        edited = _found_people(turn, found, edited)
    shown = change(turn, found, edited)
    if shown.state is DraftState.REVIEWING:
        shown = with_duplicate_check(turn, shown)
        present(turn, shown)
    return {"draft": refs.draft_handle(turn, shown), "state": shown.state.value}


def _found_people(turn: Turn, before: BillDraft, after: BillDraft) -> BillDraft:
    """Names still to be found that now mean someone added: the draft can be reviewed once
    nobody is missing. A name that meant several people becomes the speaker's nickname for
    the one picked, so "Sam" means that Sam next time without asking (L5)."""
    added = set(after.participants) - set(before.participants)
    region = turn.settings.default_region
    left: list[str] = []
    for name in after.waiting_for:
        meant = set(candidates(turn.uow, turn.speaker.id, name, region))
        picked = added & meant
        if not picked:
            left.append(name)
        elif len(meant) > 1 and len(picked) == 1:
            set_nickname(turn, picked.pop(), name)
    personal_alone = isinstance(after.context, PersonalContext) and len(after.participants) == 1
    state = after.state
    if state is DraftState.AWAITING_PEOPLE and not left and not personal_alone:
        state = DraftState.REVIEWING
    return replace(after, waiting_for=tuple(left), state=state)


DRAFT_TOOLS: tuple[Tool[Any], ...] = (
    Tool(
        "start_receipt",
        "Start a bill from this message's receipt photo, or the speaker's last unused one "
        "here (10 minutes). Group: everyone by default. Personal: the speaker plus `people`. "
        "Names you couldn't find go in unknown_names; the draft waits for them.",
        StartReceipt,
        _start_receipt,
    ),
    Tool(
        "add_manual_bill",
        'Start a bill typed in chat: description and amount; exact parts ("Sam 12000, me '
        '9000") must add up to the amount.',
        AddManualBill,
        _add_manual_bill,
    ),
    Tool(
        "set_draft_people",
        "Who a draft is with (people), or the group to file it into: the answer to \"who's "
        'this with?".',
        SetDraftPeople,
        _set_draft_people,
    ),
    Tool(
        "edit_draft",
        'One review edit of a draft. Lines are L1, L2… as shown; amounts like "120".',
        EditDraft,
        _edit_draft,
    ),
)
