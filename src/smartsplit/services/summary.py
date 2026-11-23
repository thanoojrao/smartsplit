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

    def summary(
        self,
        draft: BillDraft,
        split: DraftSplit,
        open_prompts: Sequence[Prompt],
        min_confidence: float,
    ) -> str:
        """Totals, who was skipped, new matches, unclear lines, the difference, questions."""
        title = draft.description or "This bill"
        lines = [
            f"{title}, {self.money(split.lines_total_cents)}, paid by {self.name(draft.payer_id)}."
        ]
        lines += [
            f"{self.name(person)}: {self.money(cents)}"
            for person, cents in split.result.shares.items()
        ]
        lines += self._skipped(draft, split.resolved, split)
        lines += [
            f"New match: {line.name} → {line.canonical}?"
            for line in draft.lines
            if line.match_is_new and line.canonical
        ]
        lines += [
            f"Couldn't read line {n} clearly: {line.name} {self.money(line.amount_cents)}?"
            for n, line in enumerate(draft.lines, 1)
            if line.confidence < min_confidence
        ]
        if split.difference_cents:
            lines.append(
                f"The lines add up to {self.money(split.lines_total_cents)} but the total says "
                f'{self.money(draft.total_cents)}. Fix a line, or say "accept the difference".'
            )
        lines += self.questions(draft, open_prompts)
        lines.append('Say "yes" to save it, or "details" to see every line.')
        return "\n".join(lines)

    def details(self, draft: BillDraft, split: DraftSplit) -> str:
        """The numbered list; lines can then be referred to by number or name."""
        who = {a.item_id: a.member_ids for a in split.result.assignments}
        rows = [
            f"{n}. {line.name} {self.money(line.amount_cents)}: "
            f"{join_names([self.name(p) for p in who.get(line.id, ())])}"
            for n, line in enumerate(draft.lines, 1)
        ]
        if draft.tax_cents:
            rows.append(f"Tax {self.money(draft.tax_cents)}")
        extras = draft.other_adjustments_cents + draft.accepted_difference_cents
        if extras:
            rows.append(f"Tip, charges and discounts {self.money(extras)}")
        return "\n".join(rows)

    def questions(self, draft: BillDraft, batch: Sequence[Prompt]) -> list[str]:
        """The batch's questions still unanswered, numbered by their place in the batch, so
        "2 no" means the same question to everyone who saw it."""
        by_id = {line.id: line for line in draft.lines}
        asked: list[str] = []
        for n, prompt in enumerate(batch, 1):
            payload = prompt.payload
            if not isinstance(payload, EngineQuestionPayload) or payload.line_id not in by_id:
                continue
            if prompt.answers:
                continue
            line = by_id[payload.line_id]
            what = f"{line.name} ({self.money(line.amount_cents)})"
            if payload.reason is QuestionReason.SOFT_RULE and payload.member_id:
                asked.append(f"{n}) Does {self.name(payload.member_id)} share the {what}?")
            else:
                asked.append(f"{n}) Who shares the {what}? Rules leave nobody for it.")
        return asked

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
