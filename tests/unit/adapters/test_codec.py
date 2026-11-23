"""The tagged JSON codec round-trips every nested shape the Postgres adapter stores."""

import json
from datetime import UTC, date, datetime
from typing import Literal

import pytest

from smartsplit.domain.codec import Json, decode, encode
from smartsplit.domain.commands import (
    AddManualBill,
    AnswerPrompt,
    Command,
    DeleteBill,
    Edit,
    ShowHistory,
)
from smartsplit.domain.edits import AcceptDifference, AssignLine, UnassignLine
from smartsplit.domain.enums import MatchHow, QuestionReason
from smartsplit.domain.model import LineItem
from smartsplit.domain.prompts import (
    BillChangeEffect,
    ConfirmActionPayload,
    EngineQuestionPayload,
    PromptPayload,
)
from smartsplit.domain.values import (
    EqualSplit,
    ExactAmount,
    LastBill,
    NumberedBill,
    Override,
    Weight,
    Weighted,
)

COMMANDS: list[Command] = [
    Edit(AssignLine("wine", weights=(("Sam", 2), ("Raj", 1)))),
    Edit(UnassignLine(None, ("Raj",)), target=NumberedBill(2), reason="he was away"),
    Edit(AcceptDifference(), target=LastBill()),
    AddManualBill(
        "rent", 30000, exact=(ExactAmount("Sam", 12000),), purchased_on=date(2026, 11, 1)
    ),
    AnswerPrompt(yes=True, choice=2, people=("Sam", "Raj")),
    DeleteBill(NumberedBill(1)),
    ShowHistory(period="this_month"),
    ShowHistory(),
]


def round_trip(value: object, hint: object) -> object:
    return decode(json.loads(json.dumps(encode(value))), hint)


@pytest.mark.parametrize("command", COMMANDS)
def test_commands_round_trip_through_the_union(command: Command) -> None:
    assert round_trip(command, Command) == command


def test_prompt_payloads_round_trip() -> None:
    payload = ConfirmActionPayload(DeleteBill(LastBill(), "dup"), BillChangeEffect("b1", None), 7)

    assert round_trip(payload, PromptPayload) == payload
    question = EngineQuestionPayload("l1", None, QuestionReason.NO_ELIGIBLE_MEMBERS)
    assert round_trip(question, PromptPayload) == question


def test_overrides_and_line_items_round_trip() -> None:
    overrides = (("l1", EqualSplit(("a", "b"))), ("l2", Weighted((Weight("a", 2),))))
    lines = (
        LineItem("l1", 1, "Milk", 2, 600, None, 1.0, "milk", None, MatchHow.FUZZY, True),
        LineItem("l2", 2, "Off", 1, -60, True, 0.5, None, "l1", MatchHow.NONE, False),
    )

    assert round_trip(overrides, tuple[tuple[str, Override], ...]) == overrides
    decoded = decode(json.loads(json.dumps(encode(lines))), tuple[LineItem, ...])
    assert decoded == lines
    assert isinstance(decoded[0].confidence, float)


def test_datetimes_keep_their_timezone() -> None:
    moment = datetime(2026, 11, 1, 12, 30, tzinfo=UTC)

    assert round_trip(moment, datetime) == moment


@pytest.mark.parametrize(
    ("data", "hint"),
    [
        ({"type": "Nope"}, Override),
        ({"type": "EqualSplit", "people": "a"}, EqualSplit),
        ("x", int),
        (None, int),
        ([1, 2], tuple[int, int, int]),
        ("maybe", Literal["this_month", "last_month"] | None),
        (1, type(None)),
    ],
)
def test_malformed_data_is_rejected(data: Json, hint: object) -> None:
    with pytest.raises(ValueError):
        decode(data, hint)


def test_fields_added_later_with_defaults_still_decode() -> None:
    stored_before: Json = {"type": "ShowHistory", "period": None}

    assert decode(stored_before, Command) == ShowHistory()
    with pytest.raises(ValueError):
        decode({"type": "DeleteBill"}, Command)


def test_unknown_types_are_refused() -> None:
    with pytest.raises(TypeError):
        encode(object())
    with pytest.raises(TypeError):
        decode(1, list[int])
