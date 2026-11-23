"""Editing, deleting and "not mine" for saved bills (SPEC 10.5).

A saved bill is never changed: the effect is computed and restated as a pending action, and
on a "yes" a reversing bill (and, for an edit, a new bill) is written. The saved assignments
become overrides, so rules that changed since don't silently re-split the bill.
"""

from dataclasses import replace

from smartsplit.domain.enums import DraftState, MatchHow, NotificationKind
from smartsplit.domain.model import Bill, BillDraft, BillLine, LineItem
from smartsplit.domain.prompts import BillChangeEffect, ChatRef
from smartsplit.domain.tools import (
    AddLine,
    ChangeBill,
    DeleteBill,
    DraftChange,
    NotMine,
    NotThisItem,
    RemoveLine,
    SetLineAmount,
)
from smartsplit.domain.values import EqualSplit, GroupContext, Override, Share, Weighted
from smartsplit.ports.repository import UnitOfWork
from smartsplit.services.drafting import split_of
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.ledgers import group_balances_text, overall_text
from smartsplit.services.notifications import tell_participants
from smartsplit.services.pending_types import Proposal
from smartsplit.services.review import apply_change, people_of
from smartsplit.services.saving import bill_from_draft
from smartsplit.services.speaker import group_chat
from smartsplit.services.text import day_label, money, name_for
from smartsplit.services.turn import Turn


def is_live(uow: UnitOfWork, bill: Bill) -> bool:
    """Neither a reversal nor reversed."""
    if bill.reverses_id is not None:
        return False
    return not any(b.reverses_id == bill.id for b in uow.bills.for_context(bill.context))


def bill_version(uow: UnitOfWork, bill_id: str) -> int:
    """Grows with every bill written in that bill's context (a reversal included)."""
    bill = uow.bills.get(bill_id)
    return len(uow.bills.for_context(bill.context)) if bill else -1


def propose_change(turn: Turn, args: ChangeBill) -> Proposal:
    """The effect of an edit, a delete or "not mine" (`args` holds ids), restated."""
    bill = turn.uow.bills.get(args.bill)
    if bill is None or not is_live(turn.uow, bill):
        raise NotAllowedError("That bill was already changed or deleted.")
    if turn.speaker.id not in (*bill.participants, bill.added_by):
        raise NotAllowedError("Only people in that bill can change it.")
    version = bill_version(turn.uow, bill.id)
    match args.change:
        case DeleteBill():
            total = money(bill.total_cents, turn.settings.currency)
            text = f"Delete {bill.description} ({total})?"
            return Proposal(BillChangeEffect(bill.id, None), version, text)
        case NotMine():
            new = _not_mine(turn, bill)
        case NotThisItem():
            raise NotAllowedError("Item matches can only be fixed while a bill is under review.")
        case _:
            new = _edited(turn, bill, args.change, args.reason)
    return Proposal(BillChangeEffect(bill.id, new), version, _restate(turn, bill, new))


def _edited(turn: Turn, bill: Bill, edit: DraftChange, reason: str | None) -> Bill:
    """A line edit moves the total with it ("add water 300" makes the bill 300 more); a new
    total on its own is shared like a tip. The restatement shows both. People are ids here."""
    draft = apply_change(turn, as_draft(turn, bill), edit, lambda person_id: person_id)
    if isinstance(edit, AddLine | RemoveLine | SetLineAmount):
        difference = split_of(turn, draft).difference_cents
        draft = replace(draft, total_cents=draft.total_cents - difference)
    return _rebuilt(turn, bill, draft, reason)


def _not_mine(turn: Turn, bill: Bill) -> Bill:
    """The speaker leaves the bill; their part of each line goes to the others on it, or to
    everyone left if they were alone on it."""
    me = turn.speaker.id
    if me not in bill.participants:
        raise NotAllowedError("You're not in that bill.")
    if me == bill.payer_id:
        raise NotAllowedError(
            "You paid for that one, so it stays yours. It can be deleted instead."
        )
    rest = tuple(p for p in bill.participants if p != me)
    draft = as_draft(turn, bill)
    overrides: list[tuple[str, Override]] = []
    for line_id, override in draft.overrides:
        people = tuple(p for p in people_of(override) if p != me) or rest
        overrides.append((line_id, EqualSplit(people)))
    draft = replace(draft, participants=rest, overrides=tuple(overrides))
    return _rebuilt(turn, bill, draft, "not mine")


def as_draft(turn: Turn, bill: Bill) -> BillDraft:
    """A working copy of a saved bill, with every line pinned to who shared it."""
    lines = tuple(
        LineItem(
            line.id,
            line.position,
            line.name,
            line.quantity,
            line.amount_cents,
            line.taxed,
            1.0,
            line.item_key,
            line.discount_for,
            MatchHow.EXACT,
            False,
        )
        for line in bill.lines
    )
    return BillDraft(
        id=bill.id,
        conversation=bill.origin,
        context=bill.context,
        added_by=bill.added_by,
        payer_id=bill.payer_id,
        receipt_id=bill.receipt_id,
        description=bill.description,
        purchased_at=bill.purchased_at,
        lines=lines,
        tax_cents=bill.tax_cents,
        other_adjustments_cents=bill.other_adjustments_cents,
        total_cents=bill.total_cents,
        participants=bill.participants,
        overrides=tuple((line.id, _pinned(line)) for line in bill.lines),
        owes_all_id=None,
        possible_duplicate_of=None,
        waiting_for=(),
        state=DraftState.REVIEWING,
        version=0,
        created_at=turn.now,
        last_activity_at=turn.now,
        reminded_at=None,
    )


def _pinned(line: BillLine) -> Override:
    if all(w.weight == 1 for w in line.assignees):
        return EqualSplit(tuple(w.person_id for w in line.assignees))
    return Weighted(line.assignees)


def _rebuilt(turn: Turn, bill: Bill, draft: BillDraft, reason: str | None) -> Bill:
    """The bill after the change; a total that no longer matches its lines is shared like a
    tip, and the restatement shows it."""
    difference = split_of(turn, draft).difference_cents
    draft = replace(draft, other_adjustments_cents=draft.other_adjustments_cents + difference)
    new = bill_from_draft(turn, draft, split_of(turn, draft))
    return replace(new, replaces_id=bill.id, edit_reason=reason, purchased_at=bill.purchased_at)


def _restate(turn: Turn, bill: Bill, new: Bill) -> str:
    currency = turn.settings.currency
    old = {s.person_id: s.cents for s in bill.shares}
    changes = [
        f"{_name(turn, s.person_id)} {money(old.get(s.person_id, 0), currency)} → "
        f"{money(s.cents, currency)}"
        for s in new.shares
        if old.get(s.person_id, 0) != s.cents
    ]
    changes += [
        f"{_name(turn, p)} {money(cents, currency)} → {money(0, currency)}"
        for p, cents in old.items()
        if p not in new.participants and cents
    ]
    if not changes:
        raise NotAllowedError("That doesn't change anyone's share.")
    if new.total_cents != bill.total_cents:
        changes.insert(
            0, f"total {money(bill.total_cents, currency)} → {money(new.total_cents, currency)}"
        )
    return f"Change {bill.description}: {', '.join(changes)}?"


def apply_bill_change(turn: Turn, effect: BillChangeEffect) -> None:
    """Write the reversal (and the new bill), and tell everyone in it."""
    bill = turn.uow.bills.get(effect.reverse_bill_id)
    if bill is None or not is_live(turn.uow, bill):
        raise NotAllowedError("That bill was changed meanwhile, so I left it.")
    turn.uow.bills.add(reversal_of(turn, bill))
    shown = bill
    if effect.new_bill is not None:
        shown = replace(effect.new_bill, id=turn.ids.new_id(), created_at=turn.now)
        turn.uow.bills.add(shown)
    currency = turn.settings.currency
    done = (
        f"Deleted {bill.description}."
        if effect.new_bill is None
        else f"Changed {bill.description}."
    )
    refs = (ChatRef("bill", shown.id),) if effect.new_bill is not None else ()
    if isinstance(bill.context, GroupContext):
        balances = group_balances_text(turn.uow, bill.context.group_id, currency)
        chat = group_chat(turn.uow, bill.context.group_id)
        if chat is not None and chat.key != turn.conversation.key:
            turn.post(chat, f"{turn.speaker.display_name}: {done}\n{balances}", refs)
        turn.show(f"{done}\n{balances}", refs)
        return
    reason = effect.new_bill.edit_reason if effect.new_bill else None
    changed = shown if effect.new_bill is not None else bill
    tell_participants(turn, changed, NotificationKind.BILL_CHANGED, reason, also=bill.participants)
    turn.show(f"{done}\n{overall_text(turn.uow, turn.speaker.id, currency)}", refs)


def reversal_of(turn: Turn, bill: Bill) -> Bill:
    """Every amount and share negated, same date, so balances drop it by plain addition."""
    return replace(
        bill,
        id=turn.ids.new_id(),
        lines=tuple(replace(line, amount_cents=-line.amount_cents) for line in bill.lines),
        tax_cents=-bill.tax_cents,
        other_adjustments_cents=-bill.other_adjustments_cents,
        total_cents=-bill.total_cents,
        shares=tuple(Share(s.person_id, -s.cents) for s in bill.shares),
        reverses_id=bill.id,
        replaces_id=None,
        edit_reason=None,
        created_at=turn.now,
    )


def bill_details(turn: Turn, bill: Bill) -> str:
    """Every line with who shared it, tax and other adjustments, then each person's share."""
    currency = turn.settings.currency
    rows = [
        f"{bill.description} ({day_label(bill.purchased_at)}), paid by "
        f"{_name(turn, bill.payer_id)}, {money(bill.total_cents, currency)}"
    ]
    rows += [
        f"{line.position}. {line.name} {money(line.amount_cents, currency)}: "
        + ", ".join(_name(turn, w.person_id) for w in line.assignees)
        for line in bill.lines
    ]
    if bill.tax_cents:
        rows.append(f"Tax {money(bill.tax_cents, currency)}")
    if bill.other_adjustments_cents:
        rows.append(f"Tip, charges and discounts {money(bill.other_adjustments_cents, currency)}")
    rows += [f"{_name(turn, s.person_id)}: {money(s.cents, currency)}" for s in bill.shares]
    return "\n".join(rows)


def _name(turn: Turn, person_id: str) -> str:
    return name_for(turn.uow, turn.viewer, person_id)
