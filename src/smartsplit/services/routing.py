"""Commands that aren't about the draft under review: saved bills, money, people, rules,
balances and help. `dispatch` sends everything else here."""

from smartsplit.domain.commands import (
    Acknowledge,
    AddPerson,
    AddRule,
    Command,
    CorrectNumber,
    DeleteBill,
    DeleteRule,
    Edit,
    Help,
    JoinGroup,
    ListRules,
    MemberLeft,
    Notifications,
    NotMine,
    NotReceived,
    RecordPayment,
    Remind,
    SetNickname,
    ShowBalances,
    ShowHistory,
    SquareUp,
    UndoPayment,
    Unknown,
)
from smartsplit.domain.enums import DraftState
from smartsplit.domain.values import BillRef
from smartsplit.services.bill_changes import (
    bill_details,
    find_bill,
    propose_delete,
    propose_edit,
    propose_not_mine,
)
from smartsplit.services.drafting import active_draft, split_of
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.membership import (
    add_person,
    correct_number,
    join,
    member_left,
    set_nickname,
)
from smartsplit.services.names import Directory
from smartsplit.services.payments import (
    not_received,
    propose_payment,
    propose_square_up,
    undo_payment,
)
from smartsplit.services.personal import remind, set_notifications, show_history
from smartsplit.services.queries import show_balances
from smartsplit.services.rules_chat import add_rule, delete_rule, list_rules
from smartsplit.services.summary import Renderer
from smartsplit.services.text import HELP
from smartsplit.services.turn import Turn


def route(turn: Turn, command: Command, people: Directory) -> None:
    match command:
        case Edit(op, target, reason):
            bill = find_bill(turn, target)
            propose_edit(turn, command, bill, op, directory=people, reason=reason)
        case DeleteBill(target):
            propose_delete(turn, command, find_bill(turn, target))
        case NotMine(target):
            propose_not_mine(turn, command, find_bill(turn, target))
        case RecordPayment():
            propose_payment(turn, command, people)
        case NotReceived():
            not_received(turn)
        case UndoPayment():
            undo_payment(turn)
        case SquareUp():
            propose_square_up(turn, command, people)
        case Remind():
            remind(turn, command, people)
        case ShowHistory():
            show_history(turn, command)
        case Notifications(on):
            set_notifications(turn, on)
        case _:
            _people_and_rules(turn, command, people)


def details(turn: Turn, target: BillRef | None) -> None:
    """The draft under review, or a saved bill ("details 2" from the last list)."""
    draft = active_draft(turn)
    if target is None and draft is not None and draft.state is DraftState.REVIEWING:
        renderer = Renderer(
            turn.uow, None if turn.in_group else turn.speaker.id, turn.settings.currency
        )
        turn.reply(renderer.details(draft, split_of(turn, draft)))
        return
    try:
        bill = find_bill(turn, target)
    except NotAllowedError:
        if target is None:
            raise NotAllowedError("There's no bill under review here.") from None
        raise
    turn.reply(bill_details(turn, bill))


def _people_and_rules(turn: Turn, command: Command, people: Directory) -> None:
    region = turn.settings.default_region
    match command:
        case JoinGroup():
            join(turn)
        case AddPerson(name, phone):
            add_person(turn, name, phone)
        case MemberLeft(said):
            member_left(turn, people.resolve(said, region) if said else turn.speaker.id)
        case SetNickname(said, nickname):
            set_nickname(turn, people.resolve(said, region), nickname)
        case CorrectNumber(said, phone):
            correct_number(turn, people, said, phone)
        case _:
            _rules_and_questions(turn, command, people)


def _rules_and_questions(turn: Turn, command: Command, people: Directory) -> None:
    match command:
        case AddRule():
            add_rule(turn, command, people)
        case DeleteRule():
            delete_rule(turn, command, people)
        case ListRules(subject):
            list_rules(turn, subject, people)
        case ShowBalances():
            show_balances(turn, command, people)
        case Help():
            turn.reply(HELP)
        case Acknowledge():
            pass
        case Unknown() if not turn.in_group:
            turn.reply('Sorry, I didn\'t get that. Say "help" to see what I can do.')
        case Unknown():
            pass
