"""Handles, money arguments, reply clean-up and argument completion (SPEC 8.2, 8.3, 8.5)."""

import pytest

from smartsplit.domain.prompts import RefKind
from smartsplit.domain.tools import EditDraft, ListBills, StartReceipt
from smartsplit.services.errors import NotAllowedError
from smartsplit.services.handles import Handles, line_number
from smartsplit.services.money_args import parse_money
from smartsplit.services.reply_text import clean_reply
from smartsplit.services.tools.catalog import ALL_TOOLS, TOOL_SPECS
from smartsplit.services.tools.schema import complete
from smartsplit.services.transcript import compact


def test_handles_are_numbered_per_kind_and_reused() -> None:
    handles = Handles(speaker_id="me-id")
    assert handles.issue("person", "id-sam", "Sam") == "P1"
    assert handles.issue("person", "id-raj", "Raj") == "P2"
    assert handles.issue("draft", "d-1", "Toit") == "D1"
    assert handles.issue("person", "id-sam", "Sam") == "P1"
    assert handles.resolve("p2", "person") == "id-raj"
    assert handles.resolve("me", "person") == "me-id"
    assert handles.kind_of("D1") == "draft" and handles.kind_of("D9") is None
    assert handles.label("P1") == "Sam"


@pytest.mark.parametrize(
    ("handle", "kind"), [("P9", "person"), ("D1", "person"), ("x", "person"), ("me", "draft")]
)
def test_only_issued_handles_of_the_right_kind_resolve(handle: str, kind: RefKind) -> None:
    handles = Handles(speaker_id="me-id")
    handles.issue("draft", "d-1", "Toit")
    with pytest.raises(NotAllowedError):
        handles.resolve(handle, kind)


def test_line_handles_are_the_numbers_people_see() -> None:
    assert line_number("L4") == 4 and line_number("12") == 12
    for bad in ("L0", "Lx", "line four"):
        with pytest.raises(NotAllowedError):
            line_number(bad)


@pytest.mark.parametrize(
    ("text", "cents"), [("800", 80000), ("12.5", 1250), ("12.50", 1250), (" 0.05 ", 5)]
)
def test_money_strings_become_cents(text: str, cents: int) -> None:
    assert parse_money(text, 10**8) == cents


@pytest.mark.parametrize("bad", [12.5, 800, "12.505", "1,200", "₹800", "0", "-5", "", "1e3"])
def test_anything_else_is_refused_never_rounded(bad: object) -> None:
    with pytest.raises(NotAllowedError):
        parse_money(bad, 10**8)


def test_negative_amounts_only_where_allowed_and_a_ceiling() -> None:
    assert parse_money("-40", 10**8, allow_negative=True) == -4000
    with pytest.raises(NotAllowedError, match="too large"):
        parse_money("1000000.01", 10**8)


def test_reply_cleanup() -> None:
    handles = Handles()
    handles.issue("person", "id-sam", "Sam")
    handles.issue("bill", "b-1", "Toit")
    text = "# Hi\n**P1** owes for B1 and L4.\n- one\n`code` [link](https://x.y) P7"
    assert clean_reply(text, handles) == (
        "Hi\n*Sam* owes for Toit and line 4.\n• one\ncode link (https://x.y) P7"
    )


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("call +91 98765 43210", "call +91•••••43210"),
        ("call 9876543210", "call •••••43210"),
        ("on 2026-11-21", "on 2026-11-21"),
        ("₹1,200.00 and 1200000", "₹1,200.00 and 1200000"),
        ("+12 3456 7890", "+•••••67890"),
    ],
)
def test_numbers_are_masked_but_dates_and_amounts_are_not(text: str, shown: str) -> None:
    assert clean_reply(text, Handles()) == shown


def test_missing_optional_fields_are_filled_and_variants_completed() -> None:
    assert complete({}, StartReceipt) == {
        "type": "StartReceipt",
        "people": [],
        "everyone_except": [],
        "payer": None,
        "owes_all": None,
        "unknown_names": [],
    }
    filled = complete(
        {"draft": "D1", "change": {"type": "AssignLine", "line": "L2", "people": ["P1"]}},
        EditDraft,
    )
    assert isinstance(filled, dict)
    assert filled["change"] == {
        "type": "AssignLine",
        "line": "L2",
        "people": ["P1"],
        "weights": [],
        "exact": [],
    }
    assert complete({"draft": "D1", "change": {"type": "Nope"}}, EditDraft) == {
        "type": "EditDraft",
        "draft": "D1",
        "change": {"type": "Nope"},
    }
    listed = complete({"period": "this_month"}, ListBills)
    assert isinstance(listed, dict) and listed["last_n"] is None


def test_the_tool_list_is_fixed_and_every_tool_has_a_schema() -> None:
    assert len(ALL_TOOLS) == len({t.name for t in ALL_TOOLS}) == len(TOOL_SPECS)
    for spec in TOOL_SPECS:
        assert spec.input_schema["type"] == "object"
        assert spec.description


def test_long_blocks_are_stored_as_their_first_lines() -> None:
    assert compact("a\nb\nc") == "a\nb\nc"
    assert compact("a\nb\nc\nd\ne") == "a\nb\nc\n… (2 more lines)"


def test_only_pick_person_claims_to_answer_which_sam() -> None:
    # L5: a set_nickname call would leave the stored "Which Sam?" question open
    by_name = {spec.name: spec.description.lower() for spec in TOOL_SPECS}
    assert "which sam" not in by_name["set_nickname"]
    assert "which sam" in by_name["pick_person"]
