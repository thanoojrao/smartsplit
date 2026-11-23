"""Starting and refreshing bill drafts (SPEC section 10.4).

A draft keeps a working copy of the receipt. Every change re-runs the split, syncs the
engine's questions into prompts (up to N asked at once, the rest pending) and re-renders.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date

from smartsplit.domain import normalize_item_name
from smartsplit.domain.enums import DraftState, MatchHow, PromptKind, PromptStatus
from smartsplit.domain.model import BillDraft, LineItem
from smartsplit.domain.prompts import EngineQuestionPayload, Prompt
from smartsplit.domain.values import Context, ExactAmount, GroupContext, Override, Weighted
from smartsplit.engine import amounts_to_weights
from smartsplit.ports.llm import ParsedReceipt
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.names import Directory
from smartsplit.services.speaker import current_member_ids
from smartsplit.services.splitting import DraftSplit, compute_split
from smartsplit.services.summary import Renderer
from smartsplit.services.turn import Turn

ACTIVE = (DraftState.AWAITING_PEOPLE, DraftState.PARSING, DraftState.REVIEWING)


@dataclass(frozen=True, slots=True)
class Who:
    """Who a new bill is with and who paid, as resolved for the speaker."""

    participants: tuple[str, ...]
    payer_id: str
    owes_all_id: str | None


def active_draft(turn: Turn) -> BillDraft | None:
    drafts = turn.uow.drafts.for_conversation(turn.conversation.key, ACTIVE)
    return drafts[0] if drafts else None


def who_for_group(
    turn: Turn,
    directory: Directory,
    *,
    people: Sequence[str],
    everyone: bool,
    excluding: Sequence[str],
    payer: str | None,
    owes_all: str | None,
) -> Who:
    """All current members by default, or the subset named; only current members (P1)."""
    group_id = turn.conversation.group_id or ""
    members = current_member_ids(turn.uow, group_id)
    region = turn.settings.default_region
    chosen = (
        [directory.resolve(name, region) for name in people] if people and not everyone else members
    )
    left_out = {directory.resolve(name, region) for name in excluding}
    participants = tuple(m for m in members if m in chosen and m not in left_out)
    outsiders = [p for p in chosen if p not in members]
    if outsiders:
        raise NotAllowedError("Only current members of this group can be in its bills.")
    payer_id = directory.resolve(payer, region) if payer else turn.speaker.id
    if payer_id not in members:
        raise NotAllowedError("The payer has to be a current member of this group.")
    owes_all_id = directory.resolve(owes_all, region) if owes_all else None
    if not participants:
        raise NotAllowedError("That leaves nobody in the bill.")
    return Who(participants, payer_id, owes_all_id)


def who_for_personal(
    turn: Turn,
    directory: Directory,
    *,
    people: Sequence[str],
    payer: str | None,
    owes_all: str | None,
) -> Who:
    """The speaker plus the people named; the speaker always pays in a personal split (P5)."""
    region = turn.settings.default_region
    if payer and directory.resolve(payer, region) != turn.speaker.id:
        raise NotAllowedError("In your own splits you're always the one who paid.")
    named = [directory.resolve(name, region) for name in people]
    participants = tuple(dict.fromkeys([turn.speaker.id, *named]))
    owes_all_id = directory.resolve(owes_all, region) if owes_all else None
    return Who(participants, turn.speaker.id, owes_all_id)


def lines_from_receipt(turn: Turn, parsed: ParsedReceipt) -> tuple[LineItem, ...]:
    """Domain lines with ids; the parser's discount index becomes a line id."""
    ids = [turn.ids.new_id() for _ in parsed.lines]
    return tuple(
        LineItem(
            id=ids[n],
            position=n + 1,
            name=line.name,
            quantity=line.quantity,
            amount_cents=line.amount_cents,
            taxed=line.taxed,
            confidence=line.confidence,
            canonical=None,
            discount_for=ids[line.discount_for_index]
            if line.discount_for_index is not None
            else None,
            match_how=MatchHow.NONE,
            match_is_new=False,
        )
        for n, line in enumerate(parsed.lines)
    )


def manual_line(turn: Turn, description: str, amount_cents: int) -> LineItem:
    return LineItem(
        turn.ids.new_id(),
        1,
        description,
        1,
        amount_cents,
        None,
        1.0,
        normalize_item_name(description),
        None,
        MatchHow.EXACT,
        False,
    )


def exact_override(
    directory: Directory,
    region: str,
    line_cents: int,
    exact: Sequence[ExactAmount],
    participants: Sequence[str],
) -> Override:
    """ "Sam 12000, me 9000": fixed people get their amount; the rest share what is left."""
    fixed = [(directory.resolve(e.person, region), e.cents) for e in exact]
    fixed_ids = {person for person, _ in fixed}
    others = [p for p in participants if p not in fixed_ids]
    try:
        return Weighted(amounts_to_weights(line_cents, fixed, others))
    except ValueError as error:
        raise NotAllowedError("Those amounts don't add up to the total.") from error


def new_draft(
    turn: Turn,
    *,
    context: Context,
    who: Who,
    description: str,
    lines: tuple[LineItem, ...],
    totals: tuple[int, int, int],
    state: DraftState,
    purchased_at: date | None = None,
    receipt_id: str | None = None,
    image: tuple[str, str] | None = None,
    overrides: tuple[tuple[str, Override], ...] = (),
) -> BillDraft:
    """Store a new draft; `totals` is (tax, other adjustments, total) in cents."""
    tax, other, total = totals
    draft = BillDraft(
        id=turn.ids.new_id(),
        conversation=turn.conversation.key,
        context=context,
        added_by=turn.speaker.id,
        payer_id=who.payer_id,
        receipt_id=receipt_id,
        image_ref=image[0] if image else None,
        image_mime_type=image[1] if image else None,
        description=description,
        purchased_at=purchased_at,
        lines=lines,
        tax_cents=tax,
        other_adjustments_cents=other,
        total_cents=total,
        accepted_difference_cents=0,
        participants=who.participants,
        overrides=overrides,
        owes_all_id=who.owes_all_id,
        state=state,
        created_at=turn.now,
        last_activity_at=turn.now,
        reminded_at=None,
    )
    turn.uow.drafts.add(draft)
    return draft


def split_of(turn: Turn, draft: BillDraft) -> DraftSplit:
    return compute_split(draft, turn.uow.rules.for_subjects(draft.participants))


def present(turn: Turn, draft: BillDraft) -> str:
    """Re-split, sync the questions into prompts, and render the short summary."""
    split = split_of(turn, draft)
    open_prompts = _sync_questions(turn, draft, split)
    viewer = None if isinstance(draft.context, GroupContext) and turn.in_group else turn.speaker.id
    renderer = Renderer(turn.uow, viewer, turn.settings.currency)
    return renderer.summary(draft, split, open_prompts, turn.settings.min_line_confidence)


def _sync_questions(turn: Turn, draft: BillDraft, split: DraftSplit) -> list[Prompt]:
    """New questions become pending prompts and vanished ones are dropped. Up to N are asked
    at once; the next batch opens only when the current one is answered (SPEC 10.4)."""
    uow = turn.uow
    wanted = [(q.item_id, q.member_id, q.reason) for q in split.result.questions]
    prompts = [p for p in uow.prompts.for_draft(draft.id) if p.kind is PromptKind.ENGINE_QUESTION]
    seen: set[tuple[object, ...]] = set()
    live: list[Prompt] = []
    for prompt in prompts:
        payload = prompt.payload
        if not isinstance(payload, EngineQuestionPayload):
            continue
        key = (payload.line_id, payload.member_id, payload.reason)
        seen.add(key)
        if prompt.status in (PromptStatus.PENDING, PromptStatus.OPEN):
            if key in wanted:
                live.append(prompt)
            else:
                uow.prompts.update(replace(prompt, status=PromptStatus.DROPPED))
    for line_id, member_id, reason in wanted:
        if (line_id, member_id, reason) not in seen:
            prompt = Prompt(
                turn.ids.new_id(),
                draft.conversation,
                draft.id,
                PromptKind.ENGINE_QUESTION,
                EngineQuestionPayload(line_id, member_id, reason),
                PromptStatus.PENDING,
                None,
                turn.speaker.id,
                turn.now,
                (),
            )
            uow.prompts.add(prompt)
            live.append(prompt)
    opened: list[Prompt] = []
    still_open = [p for p in live if p.status is PromptStatus.OPEN]
    if still_open:
        return still_open  # the next batch waits until this one is answered
    for prompt in live[: turn.settings.questions_per_message]:
        asked = replace(prompt, status=PromptStatus.OPEN)
        uow.prompts.update(asked)
        opened.append(asked)
    return opened
