"""Pure domain types shared by every layer. Imports nothing from smartsplit outside domain.

The submodules hold the CONTRACTS section 1 types; the most used names are re-exported here.
"""

from smartsplit.domain.enums import QuestionReason, RuleKind
from smartsplit.domain.values import Cents, Weight

__all__ = ["Cents", "QuestionReason", "RuleKind", "Weight", "normalize_item_name"]


def normalize_item_name(name: str) -> str:
    """Lowercase, trim and collapse whitespace so receipt names compare reliably."""
    return " ".join(name.lower().split())
