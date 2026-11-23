"""Small value records, scopes, contexts and references (CONTRACTS section 1.2)."""

from dataclasses import dataclass

Cents = int
"""Money is always integer cents of the install currency (SPEC section 3)."""

PersonRef = str
"""A name or number as someone said it; services resolve it to a person."""


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
class ExactAmount:
    """"Sam's part was 100", before the name is resolved."""

    person: PersonRef
    cents: Cents


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


@dataclass(frozen=True, slots=True)
class LastBill:
    """The speaker's own last bill in this chat."""


@dataclass(frozen=True, slots=True)
class NumberedBill:
    """A bill from the numbered list last shown in this chat."""

    n: int


@dataclass(frozen=True, slots=True)
class NamedBill:
    text: str


type BillRef = LastBill | NumberedBill | NamedBill
type LineRef = int | str
"""A line number in the shown list, or a name."""
