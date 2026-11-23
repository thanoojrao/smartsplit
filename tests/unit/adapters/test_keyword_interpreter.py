"""The keyword interpreter: the phrases from USE_CASES map to the right commands (SPEC 8)."""

from datetime import date

import pytest

from smartsplit.adapters.fakes.interpreter import KeywordInterpreter, cents, line_ref, names
from smartsplit.adapters.fakes.llm import FakeCanonicalizer
from smartsplit.domain.commands import (
    Acknowledge,
    AddManualBill,
    AddPerson,
    AddRule,
    AnswerPrompt,
    CancelDraft,
    Command,
    ConfirmDraft,
    CorrectNumber,
    DeleteBill,
    DeleteRule,
    Edit,
    FileIntoGroup,
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
    ShowBillDetails,
    ShowHistory,
    SquareUp,
    StartSplit,
    UndoPayment,
    Unknown,
)
from smartsplit.domain.edits import (
    AcceptDifference,
    AddLine,
    AssignLine,
    NotThisItem,
    RemoveLine,
    SetLineAmount,
    SetPayer,
    SetTotal,
    UnassignLine,
)
from smartsplit.domain.enums import ConversationKind, RuleKind
from smartsplit.domain.values import ExactAmount, LastBill, NumberedBill
from smartsplit.ports.llm import InterpretContext


def context(*, reviewing: bool = False) -> InterpretContext:
    return InterpretContext(
        conversation_kind=ConversationKind.GROUP,
        conversation_name="Flat 4B",
        today=date(2026, 11, 23),
        speaker_id="me",
        nameable=(),
        group_member_names=("Sam", "Raj"),
        group_names=("Flat 4B",),
        open_prompts=(),
        draft_lines=("1. Milk 60.00",) if reviewing else (),
    )


CASES: list[tuple[str, Command]] = [
    ("yes", AnswerPrompt(yes=True)),
    ("Nope", AnswerPrompt(yes=False)),
    ("2", AnswerPrompt(choice=2)),
    ("ok", Acknowledge()),
    ("help", Help()),
    ("stop", Notifications(on=False)),
    ("start", Notifications(on=True)),
    ("cancel", CancelDraft()),
    ("looks good", ConfirmDraft()),
    ("join", JoinGroup()),
    ("not received", NotReceived()),
    ("undo last payment", UndoPayment()),
    ("square up with Sam", SquareUp("Sam")),
    ("remind Raj", Remind("Raj")),
    ("not mine", NotMine()),
    ("details", ShowBillDetails()),
    ("details 2", ShowBillDetails(NumberedBill(2))),
    ("delete last bill because it was a duplicate", DeleteBill(LastBill(), "it was a duplicate")),
    ("add to Flat 4B", FileIntoGroup("Flat 4B")),
    ("what did I spend this month?", ShowHistory(period="this_month")),
    ("what did I spend last month", ShowHistory(period="last_month")),
    ("show last 5 bills", ShowHistory(last_n=5)),
    ("balances", ShowBalances()),
    ("balances in Goa trip", ShowBalances(group_name="Goa trip")),
    ("what do I owe Sam?", ShowBalances(with_person="Sam")),
    ("paid Sam 500", RecordPayment(50000, payee="Sam")),
    (
        "Raj paid me ₹1,200.50 for the trip",
        RecordPayment(120050, payer="Raj", context_name="the trip"),
    ),
    ("rules about me", ListRules(None)),
    ("rules about Raj", ListRules("Raj")),
    ("I don't drink milk", AddRule("milk", RuleKind.EXCLUDE, None)),
    ("Raj doesn't drink milk", AddRule("milk", RuleKind.EXCLUDE, "Raj")),
    ("don't add milk to Raj", AddRule("milk", RuleKind.EXCLUDE, "Raj")),
    ("Sam usually doesn't eat chips", AddRule("chips", RuleKind.SOFT_EXCLUDE, "Sam")),
    ("Sam never shares dessert", AddRule("dessert", RuleKind.EXCLUDE, "Sam")),
    ("protein powder is Sam's", AddRule("protein powder", RuleKind.ONLY, "Sam")),
    ("Raj drinks milk now", DeleteRule("milk", "Raj")),
    ("Raj moved out", MemberLeft("Raj")),
    ("I moved out", MemberLeft(None)),
    ("call Samuel Sam", SetNickname("Samuel", "Sam")),
    ("Priya's number is 98765 43210", CorrectNumber("Priya", "98765 43210")),
    ("add Priya +91 98765-43210", AddPerson("Priya", "+91 98765-43210")),
    ("add Priya", AddPerson("Priya")),
    ("line 4 is 120", Edit(SetLineAmount(4, 12000))),
    ("remove the bag", Edit(RemoveLine("bag"))),
    ("remove line 2", Edit(RemoveLine(2))),
    ("add water 40", Edit(AddLine("water", 4000))),
    ("total is 1840", Edit(SetTotal(184000))),
    ("accept the difference", Edit(AcceptDifference())),
    ("that's not milk", Edit(NotThisItem("milk"))),
    ("that's not milk, it's oat milk", Edit(NotThisItem("milk", "oat milk"))),
    ("Raj had none of the wine", Edit(UnassignLine("wine", ("Raj",)))),
    (
        "2 for Sam, 1 for Raj on the yogurt",
        Edit(AssignLine("yogurt", weights=(("Sam", 2), ("Raj", 1)))),
    ),
    (
        "Sam's part of line 3 was 100",
        Edit(AssignLine(3, exact=(ExactAmount("Sam", 10000),))),
    ),
    ("split this", StartSplit()),
    ("split with Sam and Raj", StartSplit(people=("Sam", "Raj"))),
    ("split with me and Priya, Sam paid", StartSplit(people=("me", "Priya"), payer="Sam")),
    ("split with everyone except Raj", StartSplit(everyone=True, excluding=("Raj",))),
    ("split this, Raj owes all of it", StartSplit(owes_all="Raj")),
    ("Sam paid", StartSplit(payer="Sam")),
    ("rent 30000 with Sam and Raj", AddManualBill("rent", 3000000, people=("Sam", "Raj"))),
    (
        "rent 30000: Sam 12000, me 9000, Raj 9000",
        AddManualBill(
            "rent",
            3000000,
            people=("Sam", "me", "Raj"),
            exact=(
                ExactAmount("Sam", 1200000),
                ExactAmount("me", 900000),
                ExactAmount("Raj", 900000),
            ),
        ),
    ),
    ("lol who took my charger", Unknown("lol who took my charger")),
]


@pytest.mark.parametrize(("text", "expected"), CASES)
def test_phrases(text: str, expected: Command) -> None:
    assert KeywordInterpreter().interpret(text, context()) == expected


def test_sam_paid_during_review_changes_the_payer() -> None:
    assert KeywordInterpreter().interpret("Sam paid", context(reviewing=True)) == Edit(
        SetPayer("Sam")
    )


def test_helpers() -> None:
    assert cents("1,200.50") == 120050
    assert names("Sam, Raj and Priya") == ("Sam", "Raj", "Priya")
    assert line_ref("line 4") == 4
    assert line_ref("the wine") == "wine"
    with pytest.raises(ValueError):
        cents("lots")


def test_canonicalize_uses_the_table() -> None:
    interpreter = KeywordInterpreter(FakeCanonicalizer({"2% MLK GAL": "milk"}))

    assert interpreter.canonicalize("2% mlk  gal", ["milk"]) == "milk"
    assert interpreter.canonicalize("Dragon Fruit", ["milk"]) == "dragon fruit"
