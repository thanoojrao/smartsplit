"""The tagged JSON codec round-trips every nested shape the Postgres adapter stores."""

import json
from datetime import UTC, date, datetime
from typing import Literal

import pytest

from smartsplit.domain.codec import Json, decode, encode
from smartsplit.domain.enums import MatchHow, QuestionReason, RuleKind
from smartsplit.domain.model import LineItem
from smartsplit.domain.prompts import (
    BillChangeEffect,
    EngineQuestionPayload,
    NotificationArgs,
    PendingActionPayload,
    PromptPayload,
)
from smartsplit.domain.tools import (
    AddManualBill,
    AssignLine,
    ChangeBill,
    DeleteBill,
    EditDraft,
    ExactPart,
    ListBills,
    PendingArgs,
    UnassignLine,
    WeightPart,
)
from smartsplit.domain.values import EqualSplit, Override, Weight, Weighted

TOOL_ARGS: list[object] = [
    EditDraft("D1", AssignLine("L2", (), (WeightPart("P2", 2), WeightPart("P3", 1)), ())),
    EditDraft("D1", UnassignLine(None, ("P3",))),
    AddManualBill(
        "rent", "30000", (), (), None, None, (ExactPart("P2", "12000"),), date(2026, 11, 1), ()
    ),
    ListBills(None, "this_month", None, None),
]


def round_trip(value: object, hint: object) -> object:
    return decode(json.loads(json.dumps(encode(value))), hint)


@pytest.mark.parametrize("arguments", TOOL_ARGS)
def test_tool_arguments_round_trip(arguments: object) -> None:
    assert round_trip(arguments, type(arguments)) == arguments


def test_prompt_payloads_round_trip() -> None:
    args: PendingArgs = ChangeBill("b1", DeleteBill(), "dup")
    payload = PendingActionPayload("change_bill", args, BillChangeEffect("b1", None), 7, "m1")

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
    stored_before: Json = {"type": "NotificationArgs", "reason": "late"}

    assert decode(stored_before, NotificationArgs) == NotificationArgs("late", None)
    with pytest.raises(ValueError):
        decode({"type": "ChangeBill", "bill": "b1"}, PendingArgs)


def test_unknown_types_are_refused() -> None:
    with pytest.raises(TypeError):
        encode(object())
    with pytest.raises(TypeError):
        decode(1, list[int])


def test_enum_and_literal_values_ignore_case() -> None:
    # Model output doesn't guarantee the casing of enum values.
    assert decode("Soft_Exclude", RuleKind) is RuleKind.SOFT_EXCLUDE
    assert decode("This_Month", Literal["this_month", "last_month"] | None) == "this_month"
    with pytest.raises(ValueError):
        decode("sometimes", RuleKind)
