"""Tool arguments: one frozen dataclass per agent tool (CONTRACTS section 1.7, SPEC 8.3).

The JSON schema the model sees is generated from these. While a turn runs, references are
handles issued for that turn (`P2`, `B3`, `D1`, `L4`, `Q1`, `A1`, `G1`, `T1`) or "me", and
amounts are `Money` strings in major units ("800", "12.50"). A pending action stores its
arguments with ids in place of handles, which is why they live in the domain.
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from smartsplit.domain.enums import RuleKind

type Handle = str
"""A per-turn reference such as "P2"; "me" means the speaker."""
type Money = str
"""A decimal string in major units; code parses it into cents."""


@dataclass(frozen=True, slots=True)
class ExactPart:
    """ "Sam's part was 100": before tax and tip (SPEC 5.2)."""

    person: Handle
    amount: Money


@dataclass(frozen=True, slots=True)
class WeightPart:
    """ "2 for Sam, 1 for Raj"."""

    person: Handle
    weight: int


@dataclass(frozen=True, slots=True)
class GetBalances:
    with_person: Handle | None
    group: Handle | None
    overall: bool


@dataclass(frozen=True, slots=True)
class GetBill:
    bill: Handle


@dataclass(frozen=True, slots=True)
class ListBills:
    last_n: int | None
    period: Literal["this_month", "last_month"] | None
    text: str | None
    person: Handle | None


@dataclass(frozen=True, slots=True)
class ListRules:
    about: Handle


@dataclass(frozen=True, slots=True)
class FindPerson:
    name: str


@dataclass(frozen=True, slots=True)
class StartReceipt:
    people: tuple[Handle, ...]
    everyone_except: tuple[Handle, ...]
    payer: Handle | None
    owes_all: Handle | None
    unknown_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AddManualBill:
    description: str
    amount: Money
    people: tuple[Handle, ...]
    everyone_except: tuple[Handle, ...]
    payer: Handle | None
    owes_all: Handle | None
    exact: tuple[ExactPart, ...]
    purchased_on: date | None
    unknown_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SetDraftPeople:
    draft: Handle
    people: tuple[Handle, ...]
    everyone_except: tuple[Handle, ...]
    group: Handle | None


@dataclass(frozen=True, slots=True)
class SetLineAmount:
    line: Handle
    amount: Money


@dataclass(frozen=True, slots=True)
class RemoveLine:
    line: Handle


@dataclass(frozen=True, slots=True)
class AddLine:
    name: str
    amount: Money


@dataclass(frozen=True, slots=True)
class SetTotal:
    amount: Money


@dataclass(frozen=True, slots=True)
class AssignLine:
    """Who shares a line: equally (`people`), by weights, or with exact parts."""

    line: Handle
    people: tuple[Handle, ...]
    weights: tuple[WeightPart, ...]
    exact: tuple[ExactPart, ...]


@dataclass(frozen=True, slots=True)
class UnassignLine:
    """ "Raj had none of the wine"; `line` None means every line."""

    line: Handle | None
    people: tuple[Handle, ...]


@dataclass(frozen=True, slots=True)
class AddPeople:
    people: tuple[Handle, ...]


@dataclass(frozen=True, slots=True)
class RemovePeople:
    people: tuple[Handle, ...]


@dataclass(frozen=True, slots=True)
class NotThisItem:
    """ "That's not milk"; `item_said` is the item named instead, if any."""

    line: Handle
    item_said: str | None


@dataclass(frozen=True, slots=True)
class SetPayer:
    person: Handle


type DraftChange = (
    SetLineAmount
    | RemoveLine
    | AddLine
    | SetTotal
    | AssignLine
    | UnassignLine
    | AddPeople
    | RemovePeople
    | NotThisItem
    | SetPayer
)


@dataclass(frozen=True, slots=True)
class EditDraft:
    draft: Handle
    change: DraftChange


@dataclass(frozen=True, slots=True)
class AnswerQuestion:
    """`included` for "is Sam in?"; `people` for "who's this for?"."""

    question: Handle
    included: bool | None
    people: tuple[Handle, ...]


@dataclass(frozen=True, slots=True)
class FileIntoGroup:
    draft: Handle
    group: Handle


@dataclass(frozen=True, slots=True)
class ConfirmDraft:
    draft: Handle
    keep_duplicate: bool
    accept_difference: bool


@dataclass(frozen=True, slots=True)
class CancelDraft:
    draft: Handle


@dataclass(frozen=True, slots=True)
class AddPerson:
    """A name with a number, this message's contact card, or a mention."""

    name: str
    phone: str | None
    use_contact: bool
    mention: Handle | None


@dataclass(frozen=True, slots=True)
class JoinGroup:
    pass


@dataclass(frozen=True, slots=True)
class MemberLeft:
    person: Handle


@dataclass(frozen=True, slots=True)
class SetNickname:
    person: Handle
    nickname: str


@dataclass(frozen=True, slots=True)
class CorrectNumber:
    person: Handle
    phone: str


@dataclass(frozen=True, slots=True)
class AddRule:
    subject: Handle
    item: str
    kind: RuleKind


@dataclass(frozen=True, slots=True)
class DeleteRule:
    subject: Handle
    item: str


@dataclass(frozen=True, slots=True)
class DeleteBill:
    pass


@dataclass(frozen=True, slots=True)
class NotMine:
    pass


type BillChange = DeleteBill | NotMine | DraftChange


@dataclass(frozen=True, slots=True)
class ChangeBill:
    bill: Handle
    change: BillChange
    reason: str | None


@dataclass(frozen=True, slots=True)
class RecordPayment:
    from_person: Handle
    to_person: Handle
    amount: Money
    group: Handle | None


@dataclass(frozen=True, slots=True)
class SquareUp:
    with_person: Handle


@dataclass(frozen=True, slots=True)
class NotReceived:
    payment: Handle | None


@dataclass(frozen=True, slots=True)
class UndoPayment:
    payment: Handle | None


@dataclass(frozen=True, slots=True)
class ConfirmPending:
    action: Handle


@dataclass(frozen=True, slots=True)
class DeclinePending:
    action: Handle


@dataclass(frozen=True, slots=True)
class Remind:
    person: Handle


@dataclass(frozen=True, slots=True)
class SetNotifications:
    on: bool


type PendingArgs = (
    ChangeBill | RecordPayment | SquareUp | NotReceived | UndoPayment | AddRule | DeleteRule
)
"""Tools whose effect may wait for a "yes" (SPEC 8.4), stored with ids for handles."""
