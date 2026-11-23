"""Amounts in commands are positive integer cents below the maximum (SPEC 8, 12.3)."""

import re

import pytest

from smartsplit.domain.commands import AddManualBill, Command, Edit, RecordPayment, StartSplit
from smartsplit.domain.edits import AddLine, AssignLine, SetTotal
from smartsplit.domain.values import ExactAmount
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
