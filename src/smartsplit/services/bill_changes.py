"""Editing, deleting and "not mine" for saved bills (SPEC 10.5).

A saved bill is never changed: the effect is shown, the requester says "yes", and then a
reversing bill (and, for an edit, a new bill) is written. The saved assignments become
overrides, so rules that changed since don't silently re-split the bill.
"""

from dataclasses import replace

from smartsplit.domain.commands import Command
from smartsplit.domain.edits import EditOp
from smartsplit.domain.enums import DraftState, MatchHow, NotificationKind, PromptKind
from smartsplit.domain.model import Bill, BillDraft, BillLine, LineItem
from smartsplit.domain.prompts import BillChangeEffect, ConfirmActionPayload
from smartsplit.domain.values import (
    BillRef,
    EqualSplit,
    GroupContext,
    LastBill,
    NamedBill,
    NumberedBill,
    Override,
    Share,
    Weighted,
)
from smartsplit.services.drafting import split_of
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.ledgers import group_balances_text, overall_text
from smartsplit.services.names import Directory
from smartsplit.services.notifications import tell_participants
from smartsplit.services.prompting import open_prompt
from smartsplit.services.review import apply_edit
from smartsplit.services.saving import bill_from_draft
from smartsplit.services.text import money, name_for
from smartsplit.services.turn import Turn

BILL_VERSION = 0
"""A bill change goes stale only by the bill being changed first, which is checked directly."""


def find_bill(turn: Turn, ref: BillRef | None) -> Bill:
    """ "last bill" is the speaker's own last bill in this chat; "2" is the second of the
    bills last listed here; a name is the latest live bill here with that description."""
    chat = turn.uow.conversations.get(turn.conversation.key) or turn.conversation
    match ref:
        case NumberedBill(n):
            listed = chat.last_listed_bill_ids
            if not 1 <= n <= len(listed):
                raise NotAllowedError(f"I haven't listed a bill {n} here.")
            bill = turn.uow.bills.get(listed[n - 1])
        case None if len(chat.last_listed_bill_ids) == 1:
            bill = turn.uow.bills.get(chat.last_listed_bill_ids[0])
        case None:
            raise NotAllowedError('Which bill? Say "last bill", or its number from the list.')
        case LastBill():
            mine = [b for b in _bills_here(turn) if b.added_by == turn.speaker.id]
            bill = mine[-1] if mine else None
        case NamedBill(text):
            wanted = text.strip().casefold()
            named = [b for b in _bills_here(turn) if b.description.casefold() == wanted]
            bill = named[-1] if named else None
    if bill is None or not is_live(turn, bill):
        raise NotAllowedError("I can't find that bill.")
    if turn.speaker.id not in (*bill.participants, bill.added_by):
        raise NotAllowedError("Only people in that bill can change it.")
    return bill


def _bills_here(turn: Turn) -> list[Bill]:
    """Live bills that came from this chat, oldest first."""
    group_id = turn.conversation.group_id
    seen = (
        turn.uow.bills.for_context(GroupContext(group_id))
        if group_id
        else turn.uow.bills.for_participant(turn.speaker.id)
    )
    return [b for b in seen if b.origin == turn.conversation.key and is_live(turn, b)]


def is_live(turn: Turn, bill: Bill) -> bool:
    """Neither a reversal nor reversed."""
    if bill.reverses_id is not None:
        return False
    return not any(b.reverses_id == bill.id for b in turn.uow.bills.for_context(bill.context))


def propose_edit(
    turn: Turn,
    command: Command,
    bill: Bill,
    op: EditOp,
    *,
    directory: Directory,
    reason: str | None,
) -> None:
    draft = apply_edit(turn, as_draft(turn, bill), op, directory)
    _propose(turn, command, bill, _rebuilt(turn, bill, draft, reason))


def propose_delete(turn: Turn, command: Command, bill: Bill) -> None:
    total = money(bill.total_cents, turn.settings.currency)
    _ask(turn, command, BillChangeEffect(bill.id, None), f"Delete {bill.description} ({total})?")


def propose_not_mine(turn: Turn, command: Command, bill: Bill) -> None:
    """The speaker leaves the bill; their part of each line goes to the others on it, or to
    everyone left if they were alone on it."""
    me = turn.speaker.id
    if me not in bill.participants:
        raise NotAllowedError("You're not in that bill.")
    if me == bill.payer_id:
        raise NotAllowedError('You paid for that one. Say "delete last bill" to remove it.')
    rest = tuple(p for p in bill.participants if p != me)
    draft = as_draft(turn, bill)
    overrides: list[tuple[str, Override]] = []
    for line_id, override in draft.overrides:
        people = tuple(p for p in _people(override) if p != me) or rest
        overrides.append((line_id, EqualSplit(people)))
    draft = replace(draft, participants=rest, overrides=tuple(overrides))
    _propose(turn, command, bill, _rebuilt(turn, bill, draft, "not mine"))


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
        image_ref=None,
        image_mime_type=None,
        description=bill.description,
        purchased_at=bill.purchased_at,
        lines=lines,
        tax_cents=bill.tax_cents,
        other_adjustments_cents=bill.other_adjustments_cents,
        total_cents=bill.total_cents,
        accepted_difference_cents=0,
        participants=bill.participants,
        overrides=tuple((line.id, _pinned(line)) for line in bill.lines),
        owes_all_id=None,
        state=DraftState.REVIEWING,
        created_at=turn.now,
        last_activity_at=turn.now,
        reminded_at=None,
    )


def _pinned(line: BillLine) -> Override:
    if all(w.weight == 1 for w in line.assignees):
        return EqualSplit(tuple(w.person_id for w in line.assignees))
    return Weighted(line.assignees)


def _people(override: Override) -> tuple[str, ...]:
    if isinstance(override, EqualSplit):
        return override.people
    return tuple(w.person_id for w in override.weights)


def _rebuilt(turn: Turn, bill: Bill, draft: BillDraft, reason: str | None) -> Bill:
    """The bill after the change; a total that no longer matches its lines is shared like a
    tip, and the restatement shows it."""
    difference = split_of(turn, draft).difference_cents
    draft = replace(draft, accepted_difference_cents=draft.accepted_difference_cents + difference)
    new = bill_from_draft(turn, draft, split_of(turn, draft))
    return replace(new, replaces_id=bill.id, edit_reason=reason, purchased_at=bill.purchased_at)


def _propose(turn: Turn, command: Command, bill: Bill, new: Bill) -> None:
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
    question = f"Change {bill.description}: {', '.join(changes)}?"
    _ask(turn, command, BillChangeEffect(bill.id, new), question)


def _ask(turn: Turn, command: Command, effect: BillChangeEffect, question: str) -> None:
    payload = ConfirmActionPayload(command, effect, BILL_VERSION)
    open_prompt(turn, None, PromptKind.CONFIRM_ACTION, payload, turn.speaker.id)
    turn.reply(f'{question} Say "yes" to confirm.')


def apply_bill_change(turn: Turn, effect: BillChangeEffect) -> None:
    """Write the reversal (and the new bill), unless the bill was changed meanwhile."""
    bill = turn.uow.bills.get(effect.reverse_bill_id or "")
    if bill is None or not is_live(turn, bill):
        turn.reply("That bill was changed meanwhile, so I left it. Have a look and try again.")
        return
    reversal = reversal_of(turn, bill)
    turn.uow.bills.add(reversal)
    shown = reversal
    if effect.new_bill is not None:
        shown = replace(effect.new_bill, id=turn.ids.new_id(), created_at=turn.now)
        turn.uow.bills.add(shown)
    currency = turn.settings.currency
    done = (
        f"Deleted {bill.description}."
        if effect.new_bill is None
        else f"Changed {bill.description}."
    )
    if isinstance(bill.context, GroupContext):
        balances = group_balances_text(turn.uow, bill.context.group_id, currency)
        group = turn.uow.groups.get(bill.context.group_id)
        chat = (
            turn.uow.conversations.get(group.channel_ref) if group and group.channel_ref else None
        )
        if chat is not None and chat.key != turn.conversation.key:
            turn.post(chat, f"{turn.speaker.display_name}: {done}\n{balances}")
        turn.reply(f"{done}\n{balances}")
        return
    reason = effect.new_bill.edit_reason if effect.new_bill else None
    tell_participants(turn, shown, NotificationKind.BILL_CHANGED, reason)
    turn.reply(f"{done}\n{overall_text(turn.uow, turn.speaker.id, currency)}")


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
    """Every line with who shared it, then each person's share."""
    currency = turn.settings.currency
    rows = [
        f"{bill.description} ({bill.purchased_at.day} {bill.purchased_at:%b}), paid by "
        f"{_name(turn, bill.payer_id)}, {money(bill.total_cents, currency)}"
    ]
    rows += [
        f"{line.position}. {line.name} {money(line.amount_cents, currency)}: "
        + ", ".join(_name(turn, w.person_id) for w in line.assignees)
        for line in bill.lines
    ]
    rows += [f"{_name(turn, s.person_id)}: {money(s.cents, currency)}" for s in bill.shares]
    return "\n".join(rows)


def _name(turn: Turn, person_id: str) -> str:
    return name_for(turn.uow, None if turn.in_group else turn.speaker.id, person_id)
