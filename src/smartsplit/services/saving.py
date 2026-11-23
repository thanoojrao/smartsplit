"""Confirming, saving and cancelling drafts, and starting the next queued one (SPEC 10.4)."""

from smartsplit.domain import normalize_item_name
from smartsplit.domain.enums import DraftState, PromptKind
from smartsplit.domain.model import Bill, BillDraft, BillLine
from smartsplit.domain.prompts import ConfirmTotalPayload
from smartsplit.domain.values import EqualSplit, GroupContext, Share, Weight, Weighted
from smartsplit.services.drafting import split_of
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.learning import LineAnswer, learn_from_bill
from smartsplit.services.ledgers import group_balances_text, overall_text
from smartsplit.services.lifecycle import finish, start_next
from smartsplit.services.prompting import open_prompt
from smartsplit.services.rules import is_current_member
from smartsplit.services.scopes import local_scope_for
from smartsplit.services.splitting import DraftSplit, effective_overrides
from smartsplit.services.text import money, name_for
from smartsplit.services.turn import Turn


def confirm(turn: Turn, draft: BillDraft) -> None:
    """Only the adder saves. A total that still doesn't match is asked about first (C5)."""
    if turn.speaker.id != draft.added_by:
        adder = name_for(turn.uow, None, draft.added_by)
        raise NotAllowedError(f"Only {adder} can save this bill.")
    split = split_of(turn, draft)
    if split.difference_cents:
        ask_about_difference(turn, draft, split)
        return
    save_bill(turn, draft, split)


def ask_about_difference(turn: Turn, draft: BillDraft, split: DraftSplit) -> None:
    currency = turn.settings.currency
    payload = ConfirmTotalPayload(split.difference_cents)
    open_prompt(turn, draft.id, PromptKind.CONFIRM_TOTAL, payload, draft.added_by)
    turn.reply(
        f"The lines come to {money(split.lines_total_cents, currency)} but the total is "
        f"{money(draft.total_cents, currency)}.\n"
        'Fix a line, or say "yes" to share the difference like a tip.'
    )


def save_bill(turn: Turn, draft: BillDraft, split: DraftSplit) -> Bill:
    """Write the bill exactly as shown, learn from its answers, and reply with balances."""
    bill = bill_from_draft(turn, draft, split)
    turn.uow.bills.add(bill)
    finish(turn, draft, DraftState.SAVED)
    learn_from_bill(
        turn.uow,
        turn.ids,
        scope=local_scope_for(draft.context, draft.added_by),
        bill_id=bill.id,
        added_by=draft.added_by,
        answers=_answers(draft),
        now=turn.now,
    )
    currency = turn.settings.currency
    saved = f"Saved: {bill.description}, {money(bill.total_cents, currency)}."
    if isinstance(bill.context, GroupContext):
        balances = group_balances_text(turn.uow, bill.context.group_id, currency)
        group_chat = turn.uow.groups.get(bill.context.group_id)
        chat = (
            turn.uow.conversations.get(group_chat.channel_ref)
            if group_chat and group_chat.channel_ref
            else None
        )
        if chat is not None and chat.key != turn.conversation.key:
            shares = "\n".join(
                f"{name_for(turn.uow, None, share.person_id)}: {money(share.cents, currency)}"
                for share in bill.shares
            )
            added = f"{turn.speaker.display_name} added a bill. {saved}"
            turn.post(chat, f"{added}\n{shares}\n{balances}")
        turn.reply(f"{saved}\n{balances}")
    else:
        turn.reply(f"{saved}\n{overall_text(turn.uow, turn.speaker.id, currency)}")
    start_next(turn, draft)
    return bill


def bill_from_draft(turn: Turn, draft: BillDraft, split: DraftSplit) -> Bill:
    """The draft's working copy with each line's final assignment; shares are the split shown."""
    weighted = {
        line_id: o.weights for line_id, o in effective_overrides(draft) if isinstance(o, Weighted)
    }
    assigned = {a.item_id: a.member_ids for a in split.result.assignments}
    lines = tuple(
        BillLine(
            line.id,
            line.position,
            line.name,
            line.canonical or normalize_item_name(line.name),
            line.quantity,
            line.amount_cents,
            line.taxed,
            line.discount_for,
            weighted.get(line.id) or tuple(Weight(p, 1) for p in assigned[line.id]),
        )
        for line in draft.lines
    )
    return Bill(
        id=turn.ids.new_id(),
        context=draft.context,
        origin=draft.conversation,
        receipt_id=draft.receipt_id,
        payer_id=draft.payer_id,
        added_by=draft.added_by,
        description=draft.description,
        purchased_at=draft.purchased_at or turn.today,
        participants=draft.participants,
        lines=lines,
        tax_cents=draft.tax_cents,
        other_adjustments_cents=draft.other_adjustments_cents + draft.accepted_difference_cents,
        total_cents=draft.total_cents,
        shares=tuple(Share(p, split.result.shares[p]) for p in draft.participants),
        reverses_id=None,
        replaces_id=None,
        edit_reason=None,
        created_at=turn.now,
    )


def _answers(draft: BillDraft) -> list[LineAnswer]:
    """Lines someone answered or edited teach about every participant (SPEC 6.5); linked
    discounts only follow their line, so they teach nothing of their own."""
    lines = {line.id: line for line in draft.lines}
    answers: list[LineAnswer] = []
    for line_id, override in draft.overrides:
        line = lines.get(line_id)
        if line is None or line.discount_for is not None or line.canonical is None:
            continue
        people = (
            override.people
            if isinstance(override, EqualSplit)
            else tuple(w.person_id for w in override.weights)
        )
        on_line = tuple(p for p in people if p in draft.participants)
        answers += [
            LineAnswer(p, line.canonical, on_line, isinstance(override, Weighted))
            for p in draft.participants
        ]
    return answers


def cancel(turn: Turn, draft: BillDraft) -> None:
    """Group drafts: any current member, and the bot says who. Personal: only the adder."""
    if isinstance(draft.context, GroupContext) and turn.in_group:
        if not is_current_member(turn.uow, draft.context.group_id, turn.speaker.id, turn.now):
            raise NotAllowedError("Only members of this group can cancel its bills.")
    elif turn.speaker.id != draft.added_by:
        raise NotAllowedError("Only the person who added it can cancel this bill.")
    finish(turn, draft, DraftState.CANCELLED)
    who = f"{turn.speaker.display_name} cancelled" if turn.in_group else "Cancelled"
    turn.reply(f"{who} the {draft.description} bill. Nothing was saved.")
    start_next(turn, draft)
