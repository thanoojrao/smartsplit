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
from smartsplit.ports.system import IdGenerator
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


def lines_from_receipt(ids: IdGenerator, parsed: ParsedReceipt) -> tuple[LineItem, ...]:
    """Domain lines with ids; the parser's discount index becomes a line id."""
    line_ids = [ids.new_id() for _ in parsed.lines]
    return tuple(
        LineItem(
            id=line_ids[n],
            position=n + 1,
            name=line.name,
            quantity=line.quantity,
            amount_cents=line.amount_cents,
            taxed=line.taxed,
            confidence=line.confidence,
            canonical=None,
            discount_for=line_ids[line.discount_for_index]
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
    """Keep the engine's questions as prompts and return the batch being asked.

    New questions become pending, and ones that no longer apply are dropped. A question whose
    line someone answered stays in its batch (an answer only changes that line's assignment,
    and the latest answer wins), so its number doesn't move. Up to N are asked at once; when
    every question in the batch has an answer, the batch closes and the next one opens.
    """
    uow = turn.uow
    wanted = [(q.item_id, q.member_id, q.reason) for q in split.result.questions]
    answered_lines = {line_id for line_id, _ in draft.overrides}
    live: list[Prompt] = []
    seen: set[tuple[object, ...]] = set()
    for prompt in uow.prompts.for_draft(draft.id):
        payload = prompt.payload
        if prompt.kind is not PromptKind.ENGINE_QUESTION or not isinstance(
            payload, EngineQuestionPayload
        ):
            continue
        key = (payload.line_id, payload.member_id, payload.reason)
        seen.add(key)
        if prompt.status not in (PromptStatus.PENDING, PromptStatus.OPEN):
            continue
        if key in wanted or _still_asked(draft, payload, answered_lines):
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
    batch = [p for p in live if p.status is PromptStatus.OPEN]
    if batch and not all(p.answers for p in batch):
        return batch
    for prompt in batch:
        uow.prompts.update(replace(prompt, status=PromptStatus.ANSWERED))
    waiting = [p for p in live if p.status is PromptStatus.PENDING]
    opened = [
        replace(p, status=PromptStatus.OPEN) for p in waiting[: turn.settings.questions_per_message]
    ]
    for prompt in opened:
        uow.prompts.update(prompt)
    return opened


def _still_asked(draft: BillDraft, payload: EngineQuestionPayload, answered: set[str]) -> bool:
    """An answer on the line keeps its question (the engine stops asking once a line has an
    override), as long as the line and the person are still in the bill."""
    line_ids = {line.id for line in draft.lines}
    person_in = payload.member_id is None or payload.member_id in draft.participants
    return payload.line_id in answered and payload.line_id in line_ids and person_in
