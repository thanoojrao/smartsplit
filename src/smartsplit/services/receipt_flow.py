"""A receipt from photo to review: who it's with, queueing, parsing, duplicates (SPEC 10.4).

The model reads the receipt outside the conversation lock: a draft is written in `parsing`
and listed on the turn, the orchestrator parses after the commit, and `finish_parse` brings
the result back in a second transaction, only if the draft is still waiting for it.
"""

from dataclasses import replace

from smartsplit.domain.commands import AnswerPrompt
from smartsplit.domain.enums import DraftState, PromptKind
from smartsplit.domain.messages import ImageAttachment
from smartsplit.domain.model import BillDraft, Receipt
from smartsplit.domain.prompts import DuplicateWarningPayload, Prompt, WhoWithPayload
from smartsplit.domain.values import GroupContext, PersonalContext
from smartsplit.engine import DuplicateCandidate, find_likely_duplicate
from smartsplit.ports.llm import ParsedReceipt
from smartsplit.services.drafting import ACTIVE, Who, active_draft, new_draft, present
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.lifecycle import ask_who_with, finish, start_next
from smartsplit.services.matching import MatchedLines, remember_matches
from smartsplit.services.names import Directory
from smartsplit.services.prompting import mark_answered, open_prompt
from smartsplit.services.review import save
from smartsplit.services.speaker import current_member_ids
from smartsplit.services.text import money, name_for
from smartsplit.services.turn import Turn


def add_photo(turn: Turn, image_ref: str, image: ImageAttachment, who: Who | None) -> None:
    """Start a receipt, or queue it behind the draft under review. `who` None: a personal
    photo with nobody named, so the bot asks who it's with first."""
    context = turn.conversation.group_id
    draft_context = GroupContext(context) if context else PersonalContext()
    current = active_draft(turn)
    if current is not None:
        queued = turn.uow.drafts.for_conversation(turn.conversation.key, (DraftState.QUEUED,))
        if len(queued) >= turn.settings.max_queued_drafts:
            raise NotAllowedError("There are already a few receipts waiting. Finish one first.")
        state = DraftState.QUEUED
    else:
        state = DraftState.PARSING if who else DraftState.AWAITING_PEOPLE
    draft = new_draft(
        turn,
        context=draft_context,
        who=who or Who((turn.speaker.id,), turn.speaker.id, None),
        description="Receipt",
        lines=(),
        totals=(0, 0, 0),
        state=state,
        image=(image_ref, image.mime_type),
    )
    if current is not None:
        turn.reply(f"I'll do this one after we finish the {current.description} bill.")
    elif state is DraftState.PARSING:
        turn.to_parse.append(draft.id)
    else:
        ask_who_with(turn, draft)


def answer_who_with(
    turn: Turn, draft: BillDraft, prompt: Prompt, answer: AnswerPrompt, directory: Directory
) -> None:
    """A listed option or names; then the receipt is read (a typed bill goes straight to review)."""
    payload = prompt.payload
    if not isinstance(payload, WhoWithPayload):
        raise NotAllowedError("That isn't a question about who it's with.")
    region = turn.settings.default_region
    chosen = next((o for o in payload.options if o.n == answer.choice), None)
    if answer.choice is not None and chosen is None:
        raise NotAllowedError(f"Pick a number from 1 to {len(payload.options)}.")
    if chosen is not None and chosen.group_id is not None:
        members = current_member_ids(turn.uow, chosen.group_id)
        if turn.speaker.id not in members:
            raise NotAllowedError("You're not in that group any more.")
        changed = replace(draft, context=GroupContext(chosen.group_id), participants=tuple(members))
    else:
        people = (
            chosen.person_ids if chosen else [directory.resolve(p, region) for p in answer.people]
        )
        if not people:
            raise NotAllowedError('Say who it\'s with, like "with Sam and Raj".')
        changed = replace(draft, participants=tuple(dict.fromkeys([draft.added_by, *people])))
    mark_answered(turn, prompt, answer)
    if draft.image_ref is None:
        turn.reply(present(turn, save(turn, draft, replace(changed, state=DraftState.REVIEWING))))
        return
    save(turn, draft, replace(changed, state=DraftState.PARSING))
    turn.to_parse.append(draft.id)


def finish_parse(
    turn: Turn, draft: BillDraft, parsed: ParsedReceipt, matched: MatchedLines
) -> None:
    """The read receipt becomes the draft's working copy and the summary is shown."""
    if draft.image_ref is None or draft.image_mime_type is None:
        raise ValueError("only a photo draft is parsed")
    receipt = Receipt(
        turn.ids.new_id(),
        draft.image_ref,
        draft.image_mime_type,
        parsed.merchant,
        parsed.purchased_at,
        matched.lines,
        parsed.tax_cents,
        parsed.other_adjustments_cents,
        parsed.total_cents,
        parsed.warnings,
    )
    turn.uow.receipts.add(receipt)
    remember_matches(turn.uow, matched)
    reviewing = replace(
        draft,
        receipt_id=receipt.id,
        description=parsed.merchant or "Receipt",
        purchased_at=parsed.purchased_at,
        lines=matched.lines,
        tax_cents=parsed.tax_cents,
        other_adjustments_cents=parsed.other_adjustments_cents,
        total_cents=parsed.total_cents,
        state=DraftState.REVIEWING,
    )
    saved = save(turn, draft, reviewing)
    warning = _duplicate_warning(turn, saved)
    turn.reply("\n".join([*parsed.warnings, *warning, present(turn, saved)]))


def parse_failed(turn: Turn, draft: BillDraft) -> None:
    finish(turn, draft, DraftState.CANCELLED)
    turn.reply("Couldn't read that receipt, try another photo.")
    start_next(turn, draft)


def _duplicate_warning(turn: Turn, draft: BillDraft) -> list[str]:
    """A same-total bill or open draft in the same place within a few days (C11)."""
    uow = turn.uow
    bills = uow.bills.for_context(draft.context)
    reversed_ids = {b.reverses_id for b in bills if b.reverses_id}
    candidates = [
        DuplicateCandidate(
            b.id, False, b.context, b.total_cents, b.purchased_at, frozenset(b.participants)
        )
        for b in bills
        if b.reverses_id is None and b.id not in reversed_ids
    ]
    candidates += [
        DuplicateCandidate(
            d.id, True, d.context, d.total_cents, d.purchased_at, frozenset(d.participants)
        )
        for d in uow.drafts.for_conversation(draft.conversation, (*ACTIVE, DraftState.QUEUED))
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
        return []
    other = uow.drafts.get(found.id) if found.is_draft else uow.bills.get(found.id)
    who = name_for(uow, None, other.added_by) if other else "someone"
    payload = DuplicateWarningPayload(
        None if found.is_draft else found.id, found.id if found.is_draft else None
    )
    open_prompt(turn, draft.id, PromptKind.DUPLICATE_WARNING, payload, draft.added_by)
    total = money(found.total_cents, turn.settings.currency)
    return [f"Looks like {who} already added this ({total}). Keep it anyway? Say yes, or cancel."]
