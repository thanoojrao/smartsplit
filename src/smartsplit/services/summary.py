"""What a draft looks like in chat: the short summary and the numbered details (SPEC 10.4)."""

from collections.abc import Sequence

from smartsplit.domain import normalize_item_name
from smartsplit.domain.enums import QuestionReason, RuleKind
from smartsplit.domain.model import BillDraft, LineItem
from smartsplit.domain.prompts import EngineQuestionPayload, Prompt
from smartsplit.domain.values import Everywhere, GroupScope, NotesScope
from smartsplit.engine import ResolvedRule
from smartsplit.ports.repository import UnitOfWork
from smartsplit.services.splitting import DraftSplit
from smartsplit.services.text import join_names, money, name_for

MATCHES_SHOWN = 3
"""New item matches listed in a summary; a long receipt would otherwise list every line."""


class Renderer:
    """Renders for one viewer (None in a group chat, where display names are used)."""

    def __init__(self, uow: UnitOfWork, viewer_id: str | None, currency: str) -> None:
        self._uow = uow
        self._viewer = viewer_id
        self._currency = currency

    def name(self, person_id: str) -> str:
        return name_for(self._uow, self._viewer, person_id)

    def money(self, cents: int) -> str:
        return money(cents, self._currency)

    def _new_matches(self, draft: BillDraft) -> list[str]:
        matched = [
            f"{x.name} → {x.canonical}" for x in draft.lines if x.match_is_new and x.canonical
        ]
        if not matched:
            return []
        shown = "; ".join(matched[:MATCHES_SHOWN])
        more = len(matched) - MATCHES_SHOWN
        tail = f" (and {more} more)" if more > 0 else ""
        return [f"Read as: {shown}{tail}. Say if one is wrong."]

    def summary(
        self,
        draft: BillDraft,
        split: DraftSplit,
        asked: Sequence[Prompt],
        min_confidence: float,
        only_member: bool = False,
        *,
        new_matches: bool = True,
    ) -> str:
        """Totals, who was skipped, new matches (the first time the draft is shown, a few at
        most: they are for spotting a wrong one, F11), unclear lines, the difference, a
        possible duplicate, and the questions being asked (worded by line)."""
        title = draft.description or "This bill"
        lines = [
            f"{title}, {self.money(split.lines_total_cents)}, paid by {self.name(draft.payer_id)}."
        ]
        lines += [
            f"{self.name(person)}: {self.money(cents)}"
            for person, cents in split.result.shares.items()
        ]
        lines += self._skipped(draft, split.resolved, split)
        if new_matches:
            lines += self._new_matches(draft)
        lines += [
            f"Couldn't read line {line.position} clearly: {line.name} "
            f"{self.money(line.amount_cents)}?"
            for line in draft.lines
            if line.confidence < min_confidence
        ]
        if split.difference_cents:
            lines.append(
                f"The lines add up to {self.money(split.lines_total_cents)} but the total says "
                f"{self.money(draft.total_cents)}. Fix a line, or keep the difference as a tip."
            )
        if draft.possible_duplicate_of is not None:
            lines.append(self._duplicate(draft))
        if only_member:
            lines.append("You're the only one here so far: ask the others to join.")
        lines += self.questions(draft, asked)
        lines.append('Say "yes" to save it, or "details" to see every line.')
        return "\n".join(lines)

    def details(self, draft: BillDraft, split: DraftSplit) -> str:
        """The numbered list; lines can then be referred to by number or name."""
        who = {a.item_id: a.member_ids for a in split.result.assignments}
        rows = [
            f"{line.position}. {line.name} {self.money(line.amount_cents)}: "
            f"{join_names([self.name(p) for p in who.get(line.id, ())])}"
            for line in draft.lines
        ]
        if draft.tax_cents:
            rows.append(f"Tax {self.money(draft.tax_cents)}")
        if draft.other_adjustments_cents:
            rows.append(f"Tip, charges and discounts {self.money(draft.other_adjustments_cents)}")
        return "\n".join(rows)

    def questions(self, draft: BillDraft, asked: Sequence[Prompt]) -> list[str]:
        """ "Line 4, chips: is Sam in?" for each question being asked."""
        by_id = {line.id: line for line in draft.lines}
        texts: list[str] = []
        for prompt in asked:
            payload = prompt.payload
            if not isinstance(payload, EngineQuestionPayload) or payload.line_id not in by_id:
                continue
            line = by_id[payload.line_id]
            where = f"Line {line.position}, {line.name}"
            if payload.reason is QuestionReason.SOFT_RULE and payload.member_id:
                texts.append(f"{where}: is {self.name(payload.member_id)} in?")
            else:
                texts.append(f"{where}: who is it for? Rules leave nobody for it.")
        return texts

    def _duplicate(self, draft: BillDraft) -> str:
        found = draft.possible_duplicate_of
        adder: str | None = None
        if found is not None and found.bill_id is not None:
            bill = self._uow.bills.get(found.bill_id)
            adder = bill.added_by if bill else None
        elif found is not None and found.draft_id is not None:
            other = self._uow.drafts.get(found.draft_id)
            adder = other.added_by if other else None
        who = self.name(adder) if adder else "someone"
        return f"Looks like {who} already added this. Keep it anyway?"

    def _skipped(
        self, draft: BillDraft, resolved: Sequence[ResolvedRule], split: DraftSplit
    ) -> list[str]:
        """Who a rule kept off a line, with the reason only for group rules and own notes; a
        line an `only` rule gives to some people says whose it is."""
        who = {a.item_id: set(a.member_ids) for a in split.result.assignments}
        notes: list[str] = []
        for rule in resolved:
            lines = _lines_with_key(draft.lines, rule.input.item_key)
            if rule.input.kind is RuleKind.EXCLUDE:
                notes += [
                    f"{self.name(rule.input.member_id)} skipped: {line.name}{self._why(rule)}"
                    for line in lines
                    if rule.input.member_id not in who.get(line.id, set())
                ]
            elif rule.input.kind is RuleKind.ONLY:
                notes += [
                    f"{line.name} is {self.name(rule.input.member_id)}'s{self._why(rule)}"
                    for line in lines
                    if who.get(line.id)
                    and rule.input.member_id in who[line.id]
                    and len(who[line.id]) < len(draft.participants)
                ]
        return notes

    def _why(self, rule: ResolvedRule) -> str:
        match rule.rule.scope:
            case GroupScope():
                return " (group rule)"
            case NotesScope(owner_id) if owner_id == self._viewer:
                return " (your note)"
            case Everywhere() | NotesScope():
                return ""


def _lines_with_key(lines: Sequence[LineItem], key: str) -> list[LineItem]:
    return [line for line in lines if (line.canonical or normalize_item_name(line.name)) == key]
