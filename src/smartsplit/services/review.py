"""Review edits and answers on the draft under review (SPEC 10.4, use cases C5-C6, G2-G6).

Every change is written with the draft's expected state, so a draft that expired or was saved
meanwhile isn't changed behind anyone's back (SPEC 12.2).
"""

from dataclasses import replace

from smartsplit.domain import normalize_item_name
from smartsplit.domain.commands import AnswerPrompt
from smartsplit.domain.edits import (
    AcceptDifference,
    AddLine,
    AddParticipants,
    AssignLine,
    EditOp,
    NotThisItem,
    RemoveLine,
    RemoveParticipants,
    SetLineAmount,
    SetPayer,
    SetTotal,
    UnassignLine,
)
from smartsplit.domain.enums import MatchHow, QuestionReason
from smartsplit.domain.model import BillDraft, ItemAlias, LineItem
from smartsplit.domain.prompts import EngineQuestionPayload, Prompt
from smartsplit.domain.values import EqualSplit, GroupContext, LineRef, Override, Weight, Weighted
from smartsplit.services.drafting import exact_override, manual_line, split_of
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.names import Directory
from smartsplit.services.prompting import record_answer
from smartsplit.services.scopes import local_scope_for
from smartsplit.services.speaker import current_member_ids
from smartsplit.services.turn import Turn


def save(turn: Turn, before: BillDraft, after: BillDraft) -> BillDraft:
    """Write the change if the draft is still in the state it was read in."""
    changed = replace(after, last_activity_at=turn.now)
    turn.uow.drafts.update(changed, expected_state=before.state)
    return changed


def apply_edit(turn: Turn, draft: BillDraft, op: EditOp, directory: Directory) -> BillDraft:
    """Apply one review edit and return the changed draft (not yet presented)."""
    match op:
        case SetLineAmount() | RemoveLine() | AddLine() | SetTotal() | AcceptDifference():
            return _line_edit(turn, draft, op)
        case NotThisItem(line, item_said):
            return _not_this_item(turn, draft, find_line(draft, line), item_said)
        case AssignLine() | UnassignLine():
            return _assignment_edit(turn, draft, op, directory)
        case AddParticipants() | RemoveParticipants() | SetPayer():
            return _people_edit(turn, draft, op, directory)


def _line_edit(
    turn: Turn,
    draft: BillDraft,
    op: SetLineAmount | RemoveLine | AddLine | SetTotal | AcceptDifference,
) -> BillDraft:
    match op:
        case SetLineAmount(line, amount):  # a person read it now: no longer flagged as unclear
            target = find_line(draft, line)
            lines = tuple(
                replace(x, amount_cents=amount, confidence=1.0) if x.id == target.id else x
                for x in draft.lines
            )
            return replace(draft, lines=lines)
        case RemoveLine(line):
            target = find_line(draft, line)
            return replace(
                draft,
                lines=tuple(x for x in draft.lines if x.id != target.id),
                overrides=tuple(o for o in draft.overrides if o[0] != target.id),
            )
        case AddLine(name, amount):
            added = replace(manual_line(turn, name, amount), position=len(draft.lines) + 1)
            return replace(draft, lines=(*draft.lines, added))
        case SetTotal(amount):
            return replace(draft, total_cents=amount, accepted_difference_cents=0)
        case AcceptDifference():
            difference = split_of(turn, draft).difference_cents
            return replace(
                draft, accepted_difference_cents=draft.accepted_difference_cents + difference
            )


def _assignment_edit(
    turn: Turn, draft: BillDraft, op: AssignLine | UnassignLine, directory: Directory
) -> BillDraft:
    region = turn.settings.default_region
    match op:
        case AssignLine(line, people, weights, exact):
            target = find_line(draft, line)
            if weights:
                override: Override = Weighted(
                    tuple(Weight(directory.resolve(n, region), w) for n, w in weights)
                )
            elif exact:
                override = exact_override(
                    directory, region, target.amount_cents, exact, draft.participants
                )
            else:
                override = EqualSplit(tuple(directory.resolve(p, region) for p in people))
            _check_in_bill(draft, override)
            return with_override(draft, target.id, override)
        case UnassignLine(line, people):
            removed = {directory.resolve(p, region) for p in people}
            targets = [find_line(draft, line)] if line is not None else list(draft.lines)
            for target in targets:
                draft = _without(turn, draft, target, removed)
            return draft


def _people_edit(
    turn: Turn,
    draft: BillDraft,
    op: AddParticipants | RemoveParticipants | SetPayer,
    directory: Directory,
) -> BillDraft:
    region = turn.settings.default_region
    match op:
        case AddParticipants(people) | RemoveParticipants(people):
            return _participants(turn, draft, op, [directory.resolve(p, region) for p in people])
        case SetPayer(person):
            if not isinstance(draft.context, GroupContext):
                raise NotAllowedError("In your own splits you're always the one who paid.")
            payer = directory.resolve(person, region)
            if payer not in current_member_ids(turn.uow, draft.context.group_id):
                raise NotAllowedError("The payer has to be a current member of this group.")
            return replace(draft, payer_id=payer, participants=_with(draft.participants, payer))


def _with(people: tuple[str, ...], person: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys([*people, person]))


def _check_in_bill(draft: BillDraft, override: Override) -> None:
    people = (
        override.people
        if isinstance(override, EqualSplit)
        else tuple(w.person_id for w in override.weights)
    )
    if any(p not in draft.participants for p in people):
        raise NotAllowedError("Add them to the bill first.")


def find_line(draft: BillDraft, ref: LineRef) -> LineItem:
    """By number in the shown list, or by name (exact, then partial)."""
    if isinstance(ref, int):
        if 1 <= ref <= len(draft.lines):
            return draft.lines[ref - 1]
        raise NotAllowedError(f"There's no line {ref}.")
    wanted = normalize_item_name(ref)
    exact = [x for x in draft.lines if wanted in (normalize_item_name(x.name), x.canonical)]
    partial = [x for x in draft.lines if wanted in normalize_item_name(x.name)]
    found = exact or partial
    if not found:
        raise NotAllowedError(f"I can't find a line called {ref}.")
    return found[0]


def with_override(draft: BillDraft, line_id: str, override: Override) -> BillDraft:
    """The latest answer or edit for a line replaces any earlier one (P9)."""
    kept = tuple(o for o in draft.overrides if o[0] != line_id)
    return replace(draft, overrides=(*kept, (line_id, override)))


def current_assignees(turn: Turn, draft: BillDraft, line_id: str) -> tuple[str, ...]:
    split = split_of(turn, draft)
    return next(a.member_ids for a in split.result.assignments if a.item_id == line_id)


def answer_question(
    turn: Turn, draft: BillDraft, prompt: Prompt, answer: AnswerPrompt, directory: Directory
) -> BillDraft:
    """An answer changes that line's current assignment; other questions stay open (G2), and
    the question stays in its batch so a later answer can replace it (G3)."""
    payload = prompt.payload
    if not isinstance(payload, EngineQuestionPayload):
        raise NotAllowedError("That isn't a question about a line.")
    line = next((x for x in draft.lines if x.id == payload.line_id), None)
    if line is None:
        raise NotAllowedError("That line is gone.")
    now_on = current_assignees(turn, draft, line.id)
    region = turn.settings.default_region
    if answer.people or answer.excluding:
        chosen = [directory.resolve(p, region) for p in answer.people] or list(draft.participants)
        out = {directory.resolve(p, region) for p in answer.excluding}
        people = tuple(p for p in draft.participants if p in chosen and p not in out)
    elif payload.reason is QuestionReason.SOFT_RULE and payload.member_id and answer.yes is False:
        people = tuple(p for p in now_on if p != payload.member_id)
    elif answer.yes is not None:
        people = now_on
    else:
        raise NotAllowedError('Answer "yes", "no", or say who shares it.')
    if not people:
        raise NotAllowedError("Someone has to share it.")
    record_answer(turn, prompt, answer)
    return with_override(draft, line.id, EqualSplit(people))


def _without(turn: Turn, draft: BillDraft, line: LineItem, removed: set[str]) -> BillDraft:
    """ "Raj had none of the wine": the others on the line share it."""
    left = tuple(p for p in current_assignees(turn, draft, line.id) if p not in removed)
    if not left:
        raise NotAllowedError(f"Someone has to share the {line.name}.")
    return with_override(draft, line.id, EqualSplit(left))


def _participants(turn: Turn, draft: BillDraft, op: EditOp, people: list[str]) -> BillDraft:
    if isinstance(op, AddParticipants):
        if isinstance(draft.context, GroupContext):
            members = current_member_ids(turn.uow, draft.context.group_id)
            if any(p not in members for p in people):
                raise NotAllowedError("Only current members of this group can be in its bills.")
        return replace(draft, participants=tuple(dict.fromkeys([*draft.participants, *people])))
    left = tuple(p for p in draft.participants if p not in people)
    if draft.payer_id not in left or not left:
        raise NotAllowedError("The one who paid stays in the bill.")
    return replace(draft, participants=left)


def _not_this_item(
    turn: Turn, draft: BillDraft, line: LineItem, item_said: str | None
) -> BillDraft:
    """ "That's not milk": forget the match here; the line becomes its own item or the one named
    (remembered for this place, P17)."""
    scope = local_scope_for(draft.context, draft.added_by)
    raw = normalize_item_name(line.name)
    key = normalize_item_name(item_said) if item_said else raw
    if item_said:
        turn.uow.aliases.put(ItemAlias(scope, raw, key))
    else:
        turn.uow.aliases.delete(scope, raw)
    turn.uow.items.ensure(key)
    lines = tuple(
        replace(x, canonical=key, match_how=MatchHow.ALIAS, match_is_new=False)
        if normalize_item_name(x.name) == raw
        else x
        for x in draft.lines
    )
    return replace(draft, lines=lines)
