"""Starting, changing and showing bill drafts (SPEC section 10.4).

Every change goes through `change`, which bumps the draft's version (so a confirm can check
the adder saw the current split, SPEC 8.4) and writes only if nobody changed it meanwhile.
`present` re-splits, keeps the engine's questions as prompts and shows the short summary.
"""

from dataclasses import dataclass, replace
from datetime import date

from smartsplit.domain import normalize_item_name
from smartsplit.domain.enums import DraftState, MatchHow, PromptKind, PromptStatus
from smartsplit.domain.model import BillDraft, LineItem
from smartsplit.domain.prompts import ChatRef, EngineQuestionPayload, Prompt
from smartsplit.domain.values import Context, Override
from smartsplit.ports.repository import ACTIVE_DRAFT_STATES
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.splitting import DraftSplit, compute_split
from smartsplit.services.summary import Renderer
from smartsplit.services.turn import Turn


@dataclass(frozen=True, slots=True)
class Who:
    """Who a new bill is with and who paid, as resolved for the speaker."""

    participants: tuple[str, ...]
    payer_id: str
    owes_all_id: str | None


@dataclass(frozen=True, slots=True)
class Totals:
    tax_cents: int
    other_adjustments_cents: int
    total_cents: int


def active_draft_of(turn: Turn, adder_id: str) -> BillDraft | None:
    """The adder's draft under way in this chat (at most one, SPEC 4.5)."""
    drafts = turn.uow.drafts.for_conversation(turn.conversation.key, ACTIVE_DRAFT_STATES)
    return next((d for d in drafts if d.added_by == adder_id), None)


def queued_of(turn: Turn, adder_id: str) -> tuple[BillDraft, ...]:
    drafts = turn.uow.drafts.for_conversation(turn.conversation.key, (DraftState.QUEUED,))
    return tuple(d for d in drafts if d.added_by == adder_id)


def manual_line(turn: Turn, description: str, amount_cents: int, position: int) -> LineItem:
    return LineItem(
        turn.ids.new_id(),
        position,
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


def new_draft(
    turn: Turn,
    *,
    context: Context,
    who: Who,
    description: str,
    lines: tuple[LineItem, ...],
    totals: Totals,
    state: DraftState,
    purchased_at: date | None = None,
    receipt_id: str | None = None,
    overrides: tuple[tuple[str, Override], ...] = (),
    waiting_for: tuple[str, ...] = (),
) -> BillDraft:
    """Store a new draft at version 1, added by the speaker in this chat."""
    draft = BillDraft(
        id=turn.ids.new_id(),
        conversation=turn.conversation.key,
        context=context,
        added_by=turn.speaker.id,
        payer_id=who.payer_id,
        receipt_id=receipt_id,
        description=description,
        purchased_at=purchased_at,
        lines=lines,
        next_position=max((line.position for line in lines), default=0) + 1,
        tax_cents=totals.tax_cents,
        other_adjustments_cents=totals.other_adjustments_cents,
        total_cents=totals.total_cents,
        participants=who.participants,
        overrides=overrides,
        owes_all_id=who.owes_all_id,
        possible_duplicate_of=None,
        waiting_for=waiting_for,
        state=state,
        version=1,
        created_at=turn.now,
        last_activity_at=turn.now,
        reminded_at=None,
    )
    turn.uow.drafts.add(draft)
    turn.changed_drafts.add(draft.id)
    turn.acted = True
    return draft


def change(turn: Turn, before: BillDraft, after: BillDraft) -> BillDraft:
    """Write a change as the next version, if the draft is still the one that was read."""
    changed = replace(after, version=before.version + 1, last_activity_at=turn.now)
    turn.uow.drafts.update(changed, expected_version=before.version)
    turn.changed_drafts.add(changed.id)
    turn.acted = True
    return changed


def line_at(draft: BillDraft, number: int) -> LineItem:
    """The line people see as `number`; numbers never shift within a draft."""
    found = next((line for line in draft.lines if line.position == number), None)
    if found is None:
        raise NotAllowedError(f"There's no line {number} in the {draft.description} bill.")
    return found


def split_of(turn: Turn, draft: BillDraft) -> DraftSplit:
    return compute_split(draft, turn.uow.rules.for_subjects(draft.participants))


def renderer_for(turn: Turn) -> Renderer:
    return Renderer(turn.uow, turn.viewer, turn.settings.currency)


def present(turn: Turn, draft: BillDraft) -> None:
    """Re-split, keep the questions, and show the short summary in the draft's chat."""
    split = split_of(turn, draft)
    questions = sync_questions(turn, draft, split)
    asked = [q for q in questions if not q.answers][: turn.settings.questions_shown]
    text = renderer_for(turn).summary(
        draft, split, asked, turn.settings.min_line_confidence, _single_member(turn, draft)
    )
    refs = (
        ChatRef("draft", draft.id, draft.version),
        *(ChatRef("question", q.id) for q in asked),
    )
    chat = turn.uow.conversations.get(draft.conversation) or turn.conversation
    turn.post(chat, text, refs)


def _single_member(turn: Turn, draft: BillDraft) -> bool:
    """A group with only one member so far: the summary suggests asking others to join."""
    return len(draft.participants) == 1 and turn.in_group


def open_questions(turn: Turn, draft: BillDraft) -> list[Prompt]:
    return [
        p
        for p in turn.uow.prompts.for_draft(draft.id)
        if p.kind is PromptKind.ENGINE_QUESTION and p.status is PromptStatus.OPEN
    ]


def sync_questions(turn: Turn, draft: BillDraft, split: DraftSplit) -> list[Prompt]:
    """Keep the engine's questions as open prompts and return them, oldest first.

    A question the engine no longer asks (its line was answered or edited, or the person left)
    is dropped; a new one is opened. Answered questions stay answered.
    """
    wanted = [(q.item_id, q.member_id, q.reason) for q in split.result.questions]
    seen: set[tuple[object, ...]] = set()
    still_open: list[Prompt] = []
    for prompt in turn.uow.prompts.for_draft(draft.id):
        payload = prompt.payload
        if not isinstance(payload, EngineQuestionPayload):
            continue
        key = (payload.line_id, payload.member_id, payload.reason)
        seen.add(key)
        if prompt.status is not PromptStatus.OPEN:
            continue
        if key in wanted:
            still_open.append(prompt)
        else:
            turn.uow.prompts.update(replace(prompt, status=PromptStatus.DROPPED))
    for line_id, member_id, reason in wanted:
        if (line_id, member_id, reason) in seen:
            continue
        prompt = Prompt(
            turn.ids.new_id(),
            draft.conversation,
            draft.id,
            PromptKind.ENGINE_QUESTION,
            EngineQuestionPayload(line_id, member_id, reason),
            PromptStatus.OPEN,
            None,
            turn.speaker.id,
            turn.now,
            None,
            (),
        )
        turn.uow.prompts.add(prompt)
        still_open.append(prompt)
    return still_open


def drop_prompts(turn: Turn, draft: BillDraft) -> None:
    """A finished draft asks nothing any more."""
    for prompt in turn.uow.prompts.for_draft(draft.id):
        if prompt.status is PromptStatus.OPEN:
            turn.uow.prompts.update(replace(prompt, status=PromptStatus.DROPPED))
