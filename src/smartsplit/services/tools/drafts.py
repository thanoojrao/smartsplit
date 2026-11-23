"""Draft tools: starting a bill, choosing people, review edits, answers, filing, saving and
cancelling (SPEC 8.3, 8.4, 10.4)."""

from dataclasses import replace
from typing import Any

from smartsplit.domain.enums import DraftState, PhotoOutcome, PromptStatus, QuestionReason
from smartsplit.domain.model import BillDraft, PhotoRead
from smartsplit.domain.prompts import EngineQuestionPayload, PromptAnswer
from smartsplit.domain.tools import (
    AddManualBill,
    AddPeople,
    AnswerQuestion,
    CancelDraft,
    ConfirmDraft,
    EditDraft,
    FileIntoGroup,
    SetDraftPeople,
    StartReceipt,
)
from smartsplit.domain.values import EqualSplit, GroupContext, Override, PersonalContext, Weight
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
    split_of,
)
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.money_args import parse_money
from smartsplit.services.names import candidates
from smartsplit.services.review import (
    apply_change,
    current_assignees,
    exact_override,
    with_override,
)
from smartsplit.services.rules import is_current_member
from smartsplit.services.saving import cancel, save_bill
from smartsplit.services.speaker import current_member_ids
from smartsplit.services.text import name_for
from smartsplit.services.tools import refs
from smartsplit.services.tools.registry import Data, Tool
from smartsplit.services.transcript import last_shown_version
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


def _reviewable(turn: Turn, handle: str) -> BillDraft:
    found = refs.draft(turn, handle)
    if found.state is DraftState.QUEUED:
        raise NotAllowedError(
            f"The {found.description} bill waits until the one before it is done."
        )
    if not turn.in_group and found.added_by != turn.speaker.id:
        raise NotAllowedError("That's someone else's bill.")
    return found


def _set_draft_people(turn: Turn, args: SetDraftPeople) -> Data:
    """The answer to "who's this with?": people, or a group name (files it there)."""
    found = _reviewable(turn, args.draft)
    if args.group is not None:
        return _file(turn, found, refs.group(turn, args.group))
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
    found = _reviewable(turn, args.draft)
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
    nobody is missing (L5)."""
    added = set(after.participants) - set(before.participants)
    region = turn.settings.default_region
    left = tuple(
        name
        for name in after.waiting_for
        if not added & set(candidates(turn.uow, turn.speaker.id, name, region))
    )
    personal_alone = isinstance(after.context, PersonalContext) and len(after.participants) == 1
    state = after.state
    if state is DraftState.AWAITING_PEOPLE and not left and not personal_alone:
        state = DraftState.REVIEWING
    return replace(after, waiting_for=left, state=state)


def _answer_question(turn: Turn, args: AnswerQuestion) -> Data:
    """An answer changes that line's current split; the latest answer wins (G2, G3)."""
    prompt = refs.question(turn, args.question)
    payload = prompt.payload
    found = turn.uow.drafts.get(prompt.draft_id or "")
    if (
        prompt.status is not PromptStatus.OPEN
        or not isinstance(payload, EngineQuestionPayload)
        or found is None
    ):
        raise NotAllowedError("That question was already settled.")
    found = _reviewable(turn, refs.draft_handle(turn, found))
    line = next((x for x in found.lines if x.id == payload.line_id), None)
    if line is None:
        raise NotAllowedError("That line is gone.")
    now_on = current_assignees(turn, found, line.id)
    if (
        payload.reason is QuestionReason.SOFT_RULE
        and payload.member_id
        and args.included is not None
    ):
        keep = {*now_on, payload.member_id} if args.included else set(now_on) - {payload.member_id}
        on_line = tuple(p for p in found.participants if p in keep)
    elif args.people:
        chosen = set(refs.people(turn, args.people))
        if not chosen <= set(found.participants):
            raise NotAllowedError("Add them to the bill first.")
        on_line = tuple(p for p in found.participants if p in chosen)
    else:
        raise NotAllowedError("Say whether they're in, or who shares that line.")
    if not on_line:
        raise NotAllowedError("Someone has to share it.")
    answer = PromptAnswer(turn.speaker.id, tuple(Weight(p, 1) for p in on_line), turn.now)
    turn.uow.prompts.update(
        replace(prompt, status=PromptStatus.ANSWERED, answers=(*prompt.answers, answer))
    )
    shown = change(turn, found, with_override(found, line.id, EqualSplit(on_line)))
    present(turn, shown)
    return {"draft": refs.draft_handle(turn, shown)}


def _file_into_group(turn: Turn, args: FileIntoGroup) -> Data:
    return _file(turn, _reviewable(turn, args.draft), refs.group(turn, args.group))


def _file(turn: Turn, found: BillDraft, group_id: str) -> Data:
    """ "add to Flat 4B" from a personal chat: the group's rules apply, questions are asked
    here, the adder confirms here, and the saved bill is posted in the group (D5)."""
    if turn.in_group:
        raise NotAllowedError("That's for bills in your own chat with me.")
    if not is_current_member(turn.uow, group_id, turn.speaker.id, turn.now):
        raise NotAllowedError("You're not in that group.")
    members = current_member_ids(turn.uow, group_id)
    named = [p for p in found.participants if p != turn.speaker.id]
    group = turn.uow.groups.get(group_id)
    if any(p not in members for p in named):
        raise NotAllowedError(
            f"Everyone in this bill has to be in {group.name if group else 'it'}."
        )
    participants = tuple(found.participants) if named else tuple(members)
    filed = replace(
        found,
        context=GroupContext(group_id),
        participants=participants,
        waiting_for=(),
        state=DraftState.REVIEWING,
    )
    shown = with_duplicate_check(turn, change(turn, found, filed))
    present(turn, shown)
    return {"draft": refs.draft_handle(turn, shown), "state": shown.state.value}


def _confirm_draft(turn: Turn, args: ConfirmDraft) -> Data:
    """Only the adder saves, on a later message than the summary it confirms (SPEC 8.4)."""
    found = refs.draft(turn, args.draft)
    if found.added_by != turn.speaker.id:
        who = name_for(turn.uow, turn.viewer, found.added_by)
        raise NotAllowedError(f"Only {who} can save this bill.")
    if found.state is not DraftState.REVIEWING:
        raise NotAllowedError("That bill isn't ready to save yet.")
    if found.id in turn.changed_drafts:
        return {
            "saved": False,
            "why": "it was just shown or changed: the adder has to see it first",
        }
    seen = last_shown_version(
        turn.uow, turn.conversation.key, found.id, turn.settings.chat_history_keep
    )
    if seen != found.version:
        present(turn, found)
        return {"saved": False, "why": "it changed since the adder saw it; the new split is shown"}
    if found.possible_duplicate_of is not None and not args.keep_duplicate:
        return {"saved": False, "why": "it looks like a duplicate: ask whether to keep it"}
    difference = split_of(turn, found).difference_cents
    if difference and not args.accept_difference:
        return {
            "saved": False,
            "why": "the lines don't add up to the total: fix a line or keep the difference",
        }
    bill = save_bill(turn, found, accept_difference=bool(difference))
    return {"saved": True, "bill": refs.bill_handle(turn, bill)}


def _cancel_draft(turn: Turn, args: CancelDraft) -> Data:
    cancel(turn, refs.draft(turn, args.draft))
    return {"cancelled": True}


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
    Tool(
        "answer_question",
        'Answer an open question (Q): included true/false for "is X in?", or people for '
        '"who is it for?".',
        AnswerQuestion,
        _answer_question,
    ),
    Tool(
        "file_into_group",
        "File a draft from the speaker's own chat into one of their groups.",
        FileIntoGroup,
        _file_into_group,
    ),
    Tool(
        "confirm_draft",
        "Save a draft the adder has seen and said yes to. Set keep_duplicate or "
        "accept_difference only after they said so.",
        ConfirmDraft,
        _confirm_draft,
    ),
    Tool("cancel_draft", "Cancel a draft; nothing is saved.", CancelDraft, _cancel_draft),
)
