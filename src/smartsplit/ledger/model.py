"""Ledger inputs and outputs (CONTRACTS section 3). Positive balance = is owed money."""

from dataclasses import dataclass

from smartsplit.domain.model import Bill, Settlement
from smartsplit.domain.values import Cents, Context


@dataclass(frozen=True, slots=True)
class ContextLedger:
    """Everything that moves money in one context (a group, or the personal splits).

    `member_order` breaks ties: for a group, every membership ever by position (leavers keep
    their place); for the personal context, people sorted by id.
    """

    context: Context
    member_order: tuple[str, ...]
    bills: tuple[Bill, ...]
    settlements: tuple[Settlement, ...]


@dataclass(frozen=True, slots=True)
class Transfer:
    """`from_id` pays `to_id`; `amount_cents` is always positive."""

    from_id: str
    to_id: str
    amount_cents: Cents


@dataclass(frozen=True, slots=True)
class Allocation:
    context: Context
    amount_cents: Cents


@dataclass(frozen=True, slots=True)
class OverallBalance:
    """`net_cents` > 0: `other_id` owes me. The breakdown has one entry per context that isn't 0."""

    other_id: str
    net_cents: Cents
    breakdown: tuple[tuple[Context, Cents], ...]
