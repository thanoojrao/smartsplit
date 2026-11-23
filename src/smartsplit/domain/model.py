"""Small value records shared by every layer (CONTRACTS section 1.2)."""

from dataclasses import dataclass

type Cents = int
"""Money is always integer cents of the install currency (SPEC section 3)."""


@dataclass(frozen=True, slots=True)
class Weight:
    """One person's relative share of a line; `weight` is a positive integer."""

    person_id: str
    weight: int
