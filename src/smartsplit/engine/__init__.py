"""Pure engine: splitting, tax, exact amounts, rule resolution, matching and learning.

The split engine's types and `split_receipt` are the FROZEN contract from SPEC section 5
(defined in `engine/split.py`, pinned by tests/acceptance/test_split_engine.py).
"""

from smartsplit.engine.duplicates import DuplicateCandidate, find_likely_duplicate
from smartsplit.engine.exact import amounts_to_weights
from smartsplit.engine.learning import learned_kind, observe
from smartsplit.engine.matching import Match, match_item
from smartsplit.engine.overrides import discount_links, propagate_discount_overrides
from smartsplit.engine.rules import ResolvedRule, resolve_rules
from smartsplit.engine.split import (
    Assignment,
    ItemInput,
    Question,
    RuleInput,
    SplitResult,
    split_receipt,
)
from smartsplit.engine.tax import TaxedLine, fold_item_tax

__all__ = [
    "Assignment",
    "DuplicateCandidate",
    "ItemInput",
    "Match",
    "Question",
    "ResolvedRule",
    "RuleInput",
    "SplitResult",
    "TaxedLine",
    "amounts_to_weights",
    "discount_links",
    "find_likely_duplicate",
    "fold_item_tax",
    "learned_kind",
    "match_item",
    "observe",
    "propagate_discount_overrides",
    "resolve_rules",
    "split_receipt",
]
