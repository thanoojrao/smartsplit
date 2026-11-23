"""Review edits and answers on a draft (SPEC 10.4, use cases C5-C6, G2-G6).

Changes arrive as tool arguments; `person` turns a person reference into an id (a handle
during a turn, the stored id when a pending action is recomputed). Nothing is written here:
the caller stores the changed draft with `drafting.change`.
"""

from collections.abc import Callable, Sequence
from dataclasses import replace

from smartsplit.domain import normalize_item_name
from smartsplit.domain.enums import MatchHow
from smartsplit.domain.model import BillDraft, ItemAlias, LineItem
from smartsplit.domain.tools import (
    AddLine,
    AddPeople,
    AssignLine,
    BillChange,
    DraftChange,
    ExactPart,
    NotThisItem,
    RemoveLine,
    RemovePeople,
    SetLineAmount,
    SetPayer,
    SetTotal,
    UnassignLine,
)
from smartsplit.domain.values import EqualSplit, GroupContext, Override, Weight, Weighted
from smartsplit.engine import amounts_to_weights
from smartsplit.services.drafting import line_at, manual_line, split_of
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.handles import line_number
from smartsplit.services.money_args import parse_money
from smartsplit.services.scopes import local_scope_for
from smartsplit.services.speaker import current_member_ids
from smartsplit.services.turn import Turn

MAX_WEIGHT = 1000
"""Weights are small whole numbers ("2 for Sam, 1 for Raj", "70/30")."""

type PersonOf = Callable[[str], str]
"""A person reference → a person id."""


def apply_change(turn: Turn, draft: BillDraft, change: DraftChange, person: PersonOf) -> BillDraft:
    """The draft after one review edit (not yet stored)."""
    match change:
        case SetLineAmount() | RemoveLine() | AddLine() | SetTotal():
            return _line_edit(turn, draft, change)
        case NotThisItem(line, item_said):
            return _not_this_item(turn, draft, line_at(draft, line_number(line)), item_said)
        case AssignLine() | UnassignLine():
            return _assignment(turn, draft, change, person)
        case AddPeople() | RemovePeople() | SetPayer():
            return _people(turn, draft, change, person)


def _line_edit(
    turn: Turn, draft: BillDraft, change: SetLineAmount | RemoveLine | AddLine | SetTotal
) -> BillDraft:
    limit = turn.settings.max_amount_cents
    match change:
        case SetLineAmount(line, amount):  # a person read it now: no longer flagged as unclear
            target = line_at(draft, line_number(line))
            cents = parse_money(amount, limit, allow_negative=target.amount_cents < 0)
            return _replace_line(draft, replace(target, amount_cents=cents, confidence=1.0))
        case RemoveLine(line):
            target = line_at(draft, line_number(line))
            return replace(
                draft,
                lines=tuple(x for x in draft.lines if x.id != target.id),
                overrides=tuple(o for o in draft.overrides if o[0] != target.id),
            )
        case AddLine(name, amount):
            cents = parse_money(amount, limit, allow_negative=True)
            position = max((x.position for x in draft.lines), default=0) + 1
            return replace(draft, lines=(*draft.lines, manual_line(turn, name, cents, position)))
        case SetTotal(amount):
            return replace(draft, total_cents=parse_money(amount, limit))


def map_people[C: BillChange](change: C, person: PersonOf) -> C:
    """The same change with every person reference mapped (handles → ids for storing)."""
    match change:
        case AssignLine(_, people, weights, exact):
            return replace(
                change,
                people=tuple(person(p) for p in people),
                weights=tuple(replace(w, person=person(w.person)) for w in weights),
                exact=tuple(replace(e, person=person(e.person)) for e in exact),
            )
        case UnassignLine(_, people) | AddPeople(people) | RemovePeople(people):
            return replace(change, people=tuple(person(p) for p in people))
        case SetPayer(said):
            return replace(change, person=person(said))
        case _:
            return change


def _replace_line(draft: BillDraft, line: LineItem) -> BillDraft:
    return replace(draft, lines=tuple(line if x.id == line.id else x for x in draft.lines))


def _assignment(
    turn: Turn, draft: BillDraft, change: AssignLine | UnassignLine, person: PersonOf
) -> BillDraft:
    match change:
        case AssignLine(line, people, weights, exact):
            target = line_at(draft, line_number(line))
            if weights:
                if any(w.weight < 1 or w.weight > MAX_WEIGHT for w in weights):
                    raise NotAllowedError("Weights are whole numbers from 1 to 1000.")
                override: Override = Weighted(
                    tuple(Weight(person(w.person), w.weight) for w in weights)
                )
            elif exact:
                override = exact_override(
                    turn, target.amount_cents, exact, draft.participants, person
                )
            elif people:
                override = EqualSplit(tuple(dict.fromkeys(person(p) for p in people)))
            else:
                raise NotAllowedError("Say who shares that line.")
            _check_in_bill(draft, override)
            return with_override(draft, target.id, override)
        case UnassignLine(line, people):
            removed = {person(p) for p in people}
            targets = [line_at(draft, line_number(line))] if line is not None else list(draft.lines)
            for target in targets:
                draft = _without(turn, draft, target, removed)
            return draft


def exact_override(
    turn: Turn,
    line_cents: int,
    exact: Sequence[ExactPart],
    participants: Sequence[str],
    person: PersonOf,
) -> Override:
    """ "Sam 12000, me 9000": fixed people get their amount; the rest share what is left."""
    limit = turn.settings.max_amount_cents
    fixed = [(person(e.person), parse_money(e.amount, limit)) for e in exact]
    if len({p for p, _ in fixed}) != len(fixed):
        raise NotAllowedError("Each person can have one amount.")
    fixed_ids = {p for p, _ in fixed}
    if any(p not in participants for p in fixed_ids):
        raise NotAllowedError("Add them to the bill first.")
    others = [p for p in participants if p not in fixed_ids]
    try:
        return Weighted(amounts_to_weights(line_cents, fixed, others))
    except ValueError as error:
        raise NotAllowedError("Those amounts don't add up to the total.") from error


def _people(
    turn: Turn, draft: BillDraft, change: AddPeople | RemovePeople | SetPayer, person: PersonOf
) -> BillDraft:
    match change:
        case AddPeople(people):
            added = [person(p) for p in people]
            if isinstance(draft.context, GroupContext):
                members = current_member_ids(turn.uow, draft.context.group_id)
                if any(p not in members for p in added):
                    raise NotAllowedError("Only current members of this group can be in its bills.")
            return replace(draft, participants=tuple(dict.fromkeys([*draft.participants, *added])))
        case RemovePeople(people):
            removed = {person(p) for p in people}
            left = tuple(p for p in draft.participants if p not in removed)
            if draft.payer_id not in left or not left:
                raise NotAllowedError("The one who paid stays in the bill.")
            return replace(draft, participants=left)
        case SetPayer(said):
            if not isinstance(draft.context, GroupContext):
                raise NotAllowedError("In your own splits you're always the one who paid.")
            payer = person(said)
            if payer not in current_member_ids(turn.uow, draft.context.group_id):
                raise NotAllowedError("The payer has to be a current member of this group.")
            return replace(draft, payer_id=payer)


def _check_in_bill(draft: BillDraft, override: Override) -> None:
    if any(p not in draft.participants for p in people_of(override)):
        raise NotAllowedError("Add them to the bill first.")


def people_of(override: Override) -> tuple[str, ...]:
    if isinstance(override, EqualSplit):
        return override.people
    return tuple(w.person_id for w in override.weights)


def with_override(draft: BillDraft, line_id: str, override: Override) -> BillDraft:
    """The latest answer or edit for a line replaces any earlier one (P9)."""
    kept = tuple(o for o in draft.overrides if o[0] != line_id)
    return replace(draft, overrides=(*kept, (line_id, override)))


def current_assignees(turn: Turn, draft: BillDraft, line_id: str) -> tuple[str, ...]:
    split = split_of(turn, draft)
    return next(a.member_ids for a in split.result.assignments if a.item_id == line_id)


def _without(turn: Turn, draft: BillDraft, line: LineItem, removed: set[str]) -> BillDraft:
    """ "Raj had none of the wine": the others on the line share it."""
    left = tuple(p for p in current_assignees(turn, draft, line.id) if p not in removed)
    if not left:
        raise NotAllowedError(f"Someone has to share the {line.name}.")
    return with_override(draft, line.id, EqualSplit(left))


def _not_this_item(
    turn: Turn, draft: BillDraft, line: LineItem, item_said: str | None
) -> BillDraft:
    """ "That's not milk": forget the match here; the line becomes its own item or the one named
    (remembered for this place, P17)."""
    scope = local_scope_for(draft.context, draft.added_by)
    raw = normalize_item_name(line.name)
    key = normalize_item_name(item_said) if item_said else raw
    if not key:
        raise NotAllowedError("Which item is it, then?")
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
