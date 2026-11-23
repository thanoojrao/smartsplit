"""Pure engine: splitting, tax folding and amount → weight conversion (SPEC sections 5-6).

The split engine's types and `split_receipt` are the FROZEN contract from SPEC section 5
(defined in `engine/split.py`, pinned by tests/acceptance/test_split_engine.py).
"""

from smartsplit.engine.exact import amounts_to_weights
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
    "ItemInput",
    "Question",
    "RuleInput",
    "SplitResult",
    "TaxedLine",
    "amounts_to_weights",
    "fold_item_tax",
    "split_receipt",
]
