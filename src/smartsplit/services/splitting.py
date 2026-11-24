"""Splitting a draft: working lines + overrides + rules → shares and questions (SPEC 10.4).

Pure: given the draft and the candidate rules, the same split comes out every time, which is
what lets a review resume exactly after a restart.
"""

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from smartsplit.domain.model import BillDraft, Rule
from smartsplit.domain.values import EqualSplit, Override, Weighted
from smartsplit.engine import (
    ItemInput,
    ResolvedRule,
    SplitResult,
    TaxedLine,
    fold_item_tax,
    propagate_discount_overrides,
    resolve_rules,
    split_receipt,
)


@dataclass(frozen=True, slots=True)
class DraftSplit:
    result: SplitResult
    resolved: tuple[ResolvedRule, ...]
    lines_total_cents: int
    """Lines + tax + other adjustments: what the shares add up to."""
    difference_cents: int
    """Receipt total minus `lines_total_cents`; the adder fixes a line or accepts it (C5)."""

    @property
    def fingerprint(self) -> str:
        """Short and stable for the same shares: what a summary's reference remembers."""
        shares = ";".join(f"{p}={c}" for p, c in sorted(self.result.shares.items()))
        return hashlib.sha256(shares.encode()).hexdigest()[:16]


def compute_split(draft: BillDraft, rules: Sequence[Rule]) -> DraftSplit:
    """Run the engine on the draft as it stands now."""
    participants = list(draft.participants)
    overrides = effective_overrides(draft)
    items = [
        ItemInput(line.id, line.name, line.amount_cents, line.canonical) for line in draft.lines
    ]
    folded, leftover_tax = fold_item_tax(
        [TaxedLine(item, line.taxed) for item, line in zip(items, draft.lines, strict=True)],
        draft.tax_cents,
    )
    adjustments = leftover_tax + draft.other_adjustments_cents
    resolved = resolve_rules(rules, participants, draft.context, draft.added_by)
    result = split_receipt(
        folded,
        participants,
        [r.input for r in resolved],
        adjustments,
        {line_id: _engine_override(o) for line_id, o in overrides},
    )
    lines_total = (
        sum(line.amount_cents for line in draft.lines)
        + draft.tax_cents
        + draft.other_adjustments_cents
    )
    return DraftSplit(result, resolved, lines_total, draft.total_cents - lines_total)


def effective_overrides(draft: BillDraft) -> tuple[tuple[str, Override], ...]:
    """The draft's overrides, limited to current participants and existing lines, plus "X owes
    all of it" on every other line, plus linked discounts following their line."""
    participants = set(draft.participants)
    line_ids = {line.id for line in draft.lines}
    kept: list[tuple[str, Override]] = []
    for line_id, override in draft.overrides:
        trimmed = _trim(override, participants)
        if line_id in line_ids and trimmed is not None:
            kept.append((line_id, trimmed))
    if draft.owes_all_id in participants and draft.owes_all_id is not None:
        covered = {line_id for line_id, _ in kept}
        kept += [
            (line.id, EqualSplit((draft.owes_all_id,)))
            for line in draft.lines
            if line.id not in covered
        ]
    return propagate_discount_overrides(draft.lines, kept)


def _trim(override: Override, participants: set[str]) -> Override | None:
    """Drop people who are no longer in the bill (e.g. moved out); None if nobody is left."""
    match override:
        case EqualSplit(people):
            left = tuple(p for p in people if p in participants)
            return EqualSplit(left) if left else None
        case Weighted(weights):
            kept = tuple(w for w in weights if w.person_id in participants)
            return Weighted(kept) if kept else None


def _engine_override(override: Override) -> Sequence[str] | Mapping[str, int]:
    match override:
        case EqualSplit(people):
            return list(people)
        case Weighted(weights):
            return {w.person_id: w.weight for w in weights}
