"""Amounts in commands are positive integer cents below the maximum (SPEC 8, 12.3)."""

import re

import pytest

from smartsplit.domain.commands import (
    AddManualBill,
    AnswerPrompt,
    Command,
    Edit,
    RecordPayment,
    ShowBillDetails,
    ShowHistory,
    StartSplit,
)
from smartsplit.domain.edits import AddLine, AssignLine, SetTotal
from smartsplit.domain.values import ExactAmount, NumberedBill
from smartsplit.services.command_checks import InvalidAmountError, check_amounts

MAX = 100_000_000


@pytest.mark.parametrize(
    "command",
    [
        RecordPayment(50000, payee="Sam"),
        AddManualBill("rent", 3000000, exact=(ExactAmount("Sam", 1200000),)),
        Edit(AssignLine(2, exact=(ExactAmount("Sam", 100),))),
        StartSplit(),
    ],
)
def test_sensible_amounts_pass(command: Command) -> None:
    assert check_amounts(command, MAX) == command


@pytest.mark.parametrize(
    "command",
    [
        RecordPayment(0, payee="Sam"),
        RecordPayment(-500, payee="Sam"),
        RecordPayment(MAX, payee="Sam"),
        AddManualBill("rent", 3000000, exact=(ExactAmount("Sam", -1),)),
        Edit(AddLine("water", 0)),
        Edit(SetTotal(MAX + 1)),
    ],
)
def test_zero_negative_or_huge_amounts_are_refused(command: Command) -> None:
    with pytest.raises(InvalidAmountError, match=re.escape("less than 1,000,000.00")):
        check_amounts(command, MAX)


@pytest.mark.parametrize(
    "command",
    [
        Edit(AssignLine(1, weights=(("Sam", 0), ("Raj", 1)))),
        Edit(AssignLine(1, weights=(("Sam", 5000),))),
        ShowHistory(last_n=0),
        ShowBillDetails(NumberedBill(-1)),
        AnswerPrompt(choice=0),
    ],
)
def test_weights_list_numbers_and_counts_must_be_sensible(command: Command) -> None:
    with pytest.raises(InvalidAmountError, match="between 1 and 1000"):
        check_amounts(command, MAX)


def test_sensible_counts_pass() -> None:
    command = Edit(AssignLine("wine", weights=(("Sam", 2), ("Raj", 1))))

    assert check_amounts(command, MAX) == command
    assert check_amounts(ShowHistory(last_n=5), MAX) == ShowHistory(last_n=5)
