"""Learning rules from how saved bills were answered (SPEC section 6.5)."""

from collections.abc import Sequence

from smartsplit.domain.enums import AnswerOutcome, RuleKind, RuleSource
from smartsplit.domain.model import AnswerObservation, Rule

_STREAK = 2
"""How many consistent answers in a row teach a rule."""

_PROTECTED = frozenset({RuleKind.EXCLUDE, RuleKind.ONLY})


def observe(person_id: str, assignees: Sequence[str], *, weighted: bool) -> AnswerOutcome:
    """What one saved line shows about one person who was asked about it, or whose share was
    edited: left out, the only one, or included. A weighted split always counts as included."""
    if person_id not in assignees:
        return AnswerOutcome.EXCLUDED
    if len(assignees) == 1 and not weighted:
        return AnswerOutcome.SOLE_ASSIGNEE
    return AnswerOutcome.INCLUDED


def learned_kind(
    observations: Sequence[AnswerObservation], existing: Rule | None
) -> RuleKind | None:
    """The rule the last answers teach for one (scope, subject, item key), if any.

    Two `excluded` in a row teach `exclude`, two `sole_assignee` teach `only`. A stated
    `exclude` or `only` is never overridden; a stated `soft_exclude` can be ("usually" settled).
    `observations` are oldest first.
    """
    if existing and existing.source is RuleSource.STATED and existing.kind in _PROTECTED:
        return None
    recent = {o.outcome for o in observations[-_STREAK:]}
    if len(observations) < _STREAK or len(recent) != 1:
        return None
    match recent.pop():
        case AnswerOutcome.EXCLUDED:
            return RuleKind.EXCLUDE
        case AnswerOutcome.SOLE_ASSIGNEE:
            return RuleKind.ONLY
        case AnswerOutcome.INCLUDED:
            return None
