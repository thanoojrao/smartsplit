"""Small value records, scopes, contexts and references (CONTRACTS section 1.2)."""

from dataclasses import dataclass

Cents = int
"""Money is always integer cents of the install currency (SPEC section 3)."""


@dataclass(frozen=True, slots=True)
class Share:
    person_id: str
    cents: Cents


@dataclass(frozen=True, slots=True)
class Weight:
    """One person's relative share of a line; `weight` is a positive integer."""

    person_id: str
    weight: int


@dataclass(frozen=True, slots=True)
class ConversationKey:
    """One chat: the (channel, ref) pair is globally unique."""

    channel: str
    ref: str


@dataclass(frozen=True, slots=True)
class Everywhere:
    """A person's own rule, applying to every bill they are in."""


@dataclass(frozen=True, slots=True)
class GroupScope:
    group_id: str


@dataclass(frozen=True, slots=True)
class NotesScope:
    """An adder's notes: applies only to personal splits that person adds."""

    owner_id: str


type RuleScope = Everywhere | GroupScope | NotesScope
type LocalScope = GroupScope | NotesScope
"""Where item aliases and answer observations live."""


@dataclass(frozen=True, slots=True)
class GroupContext:
    group_id: str


@dataclass(frozen=True, slots=True)
class PersonalContext:
    """Personal splits: no group; the people are the bill's participants."""


type Context = GroupContext | PersonalContext


@dataclass(frozen=True, slots=True)
class EqualSplit:
    people: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Weighted:
    weights: tuple[Weight, ...]


type Override = EqualSplit | Weighted
"""Who shares a line, from answers or edits. Exact amounts become `Weighted`."""
