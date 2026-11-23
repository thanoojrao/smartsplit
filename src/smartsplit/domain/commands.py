"""The structured commands the interpreter returns (CONTRACTS section 1.7, SPEC section 8).

People are `PersonRef`s, names as said: the model never supplies ids.
"""

from dataclasses import dataclass
from datetime import date
from typing import Literal

from smartsplit.domain.edits import EditOp
from smartsplit.domain.enums import RuleKind
from smartsplit.domain.values import BillRef, Cents, ExactAmount, PersonRef


@dataclass(frozen=True, slots=True)
class StartSplit:
    people: tuple[PersonRef, ...] = ()
    everyone: bool = False
    excluding: tuple[PersonRef, ...] = ()
    payer: PersonRef | None = None
    owes_all: PersonRef | None = None


@dataclass(frozen=True, slots=True)
class AddManualBill:
    description: str
    amount: Cents
    people: tuple[PersonRef, ...] = ()
    everyone: bool = False
    excluding: tuple[PersonRef, ...] = ()
    payer: PersonRef | None = None
    owes_all: PersonRef | None = None
    exact: tuple[ExactAmount, ...] = ()
    purchased_on: date | None = None


@dataclass(frozen=True, slots=True)
class AnswerPrompt:
    """An answer; which prompt it answers (or whether "yes" confirms) is decided by services."""

    prompt_id: str | None = None
    yes: bool | None = None
    choice: int | None = None
    people: tuple[PersonRef, ...] = ()
    excluding: tuple[PersonRef, ...] = ()
    text: str | None = None


@dataclass(frozen=True, slots=True)
class Edit:
    """An edit of the active draft (`target` None) or of a saved bill."""

    op: EditOp
    target: BillRef | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ConfirmDraft:
    pass


@dataclass(frozen=True, slots=True)
class CancelDraft:
    pass


@dataclass(frozen=True, slots=True)
class Acknowledge:
    """ "ok" to a notification; needs no reply."""


@dataclass(frozen=True, slots=True)
class FileIntoGroup:
    group_name: str


@dataclass(frozen=True, slots=True)
class DeleteBill:
    target: BillRef
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class NotMine:
    target: BillRef | None = None


@dataclass(frozen=True, slots=True)
class ShowBillDetails:
    target: BillRef | None = None


@dataclass(frozen=True, slots=True)
class AddPerson:
    """In a group chat this adds a member. Contact cards arrive as attachments."""

    name: str
    phone: str | None = None


@dataclass(frozen=True, slots=True)
class JoinGroup:
    pass


@dataclass(frozen=True, slots=True)
class MemberLeft:
    """`person` None means the speaker."""

    person: PersonRef | None = None


@dataclass(frozen=True, slots=True)
class SetNickname:
    person: PersonRef
    nickname: str


@dataclass(frozen=True, slots=True)
class CorrectNumber:
    person: PersonRef
    phone: str


@dataclass(frozen=True, slots=True)
class AddRule:
    """`subject` None means the speaker."""

    item: str
    kind: RuleKind
    subject: PersonRef | None = None


@dataclass(frozen=True, slots=True)
class DeleteRule:
    item: str
    subject: PersonRef | None = None


@dataclass(frozen=True, slots=True)
class ListRules:
    subject: PersonRef | None = None


@dataclass(frozen=True, slots=True)
class ShowBalances:
    with_person: PersonRef | None = None
    group_name: str | None = None


@dataclass(frozen=True, slots=True)
class RecordPayment:
    """One of `payer` and `payee` is the speaker (None)."""

    amount: Cents
    payer: PersonRef | None = None
    payee: PersonRef | None = None
    context_name: str | None = None


@dataclass(frozen=True, slots=True)
class NotReceived:
    pass


@dataclass(frozen=True, slots=True)
class UndoPayment:
    pass


@dataclass(frozen=True, slots=True)
class SquareUp:
    with_person: PersonRef


@dataclass(frozen=True, slots=True)
class Remind:
    person: PersonRef


@dataclass(frozen=True, slots=True)
class ShowHistory:
    period: Literal["this_month", "last_month"] | None = None
    last_n: int | None = None


@dataclass(frozen=True, slots=True)
class Notifications:
    on: bool


@dataclass(frozen=True, slots=True)
class Help:
    pass


@dataclass(frozen=True, slots=True)
class Unknown:
    text: str


type Command = (
    StartSplit
    | AddManualBill
    | AnswerPrompt
    | Edit
    | ConfirmDraft
    | CancelDraft
    | Acknowledge
    | FileIntoGroup
    | DeleteBill
    | NotMine
    | ShowBillDetails
    | AddPerson
    | JoinGroup
    | MemberLeft
    | SetNickname
    | CorrectNumber
    | AddRule
    | DeleteRule
    | ListRules
    | ShowBalances
    | RecordPayment
    | NotReceived
    | UndoPayment
    | SquareUp
    | Remind
    | ShowHistory
    | Notifications
    | Help
    | Unknown
)
