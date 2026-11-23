"""Pure domain types shared by every layer. Imports nothing from smartsplit."""

from enum import StrEnum

from smartsplit.domain.model import Cents, Weight

__all__ = ["Cents", "QuestionReason", "RuleKind", "Weight", "normalize_item_name"]


class RuleKind(StrEnum):
    """How a member relates to an item key (SPEC section 5)."""

    EXCLUDE = "exclude"
    """Never charge this member for the item."""
    SOFT_EXCLUDE = "soft_exclude"
    """Member usually doesn't use it: include them, but ask."""
    ONLY = "only"
    """Item belongs only to the member(s) holding this rule."""


class QuestionReason(StrEnum):
    """Why the split engine wants a human to confirm an item."""

    SOFT_RULE = "soft_rule"
    NO_ELIGIBLE_MEMBERS = "no_eligible_members"


def normalize_item_name(name: str) -> str:
    """Lowercase, trim and collapse whitespace so receipt names compare reliably."""
    return " ".join(name.lower().split())
