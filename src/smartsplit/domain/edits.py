"""Edit operations on a draft or a saved bill (CONTRACTS section 1.7, SPEC section 10.4)."""

from dataclasses import dataclass

from smartsplit.domain.values import Cents, ExactAmount, LineRef, PersonRef


@dataclass(frozen=True, slots=True)
class SetLineAmount:
    line: LineRef
    amount: Cents


@dataclass(frozen=True, slots=True)
class RemoveLine:
    line: LineRef


@dataclass(frozen=True, slots=True)
class AddLine:
    name: str
    amount: Cents


@dataclass(frozen=True, slots=True)
class SetTotal:
    amount: Cents


@dataclass(frozen=True, slots=True)
class AssignLine:
    line: LineRef
    people: tuple[PersonRef, ...] = ()
    weights: tuple[tuple[PersonRef, int], ...] = ()
    exact: tuple[ExactAmount, ...] = ()


@dataclass(frozen=True, slots=True)
class UnassignLine:
    """ "Raj had none of the wine"; `line` None means every line."""

    line: LineRef | None
    people: tuple[PersonRef, ...]


@dataclass(frozen=True, slots=True)
class AddParticipants:
    people: tuple[PersonRef, ...]


@dataclass(frozen=True, slots=True)
class RemoveParticipants:
    people: tuple[PersonRef, ...]


@dataclass(frozen=True, slots=True)
class AcceptDifference:
    """Accept the gap between lines and total as an adjustment shared like tip."""


@dataclass(frozen=True, slots=True)
class NotThisItem:
    """ "That's not milk": `item_said` is the item named instead, if any."""

    line: LineRef
    item_said: str | None = None


@dataclass(frozen=True, slots=True)
class SetPayer:
    person: PersonRef


type EditOp = (
    SetLineAmount
    | RemoveLine
    | AddLine
    | SetTotal
    | AssignLine
    | UnassignLine
    | AddParticipants
    | RemoveParticipants
    | AcceptDifference
    | NotThisItem
    | SetPayer
)
