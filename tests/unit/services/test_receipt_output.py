"""Validating parser output into a ParsedReceipt (SPEC section 7), via recorded fixtures."""

import json
from datetime import date
from pathlib import Path

import pytest

from smartsplit.adapters.fakes.llm import FakeReceiptParser
from smartsplit.ports.llm import ParsedLine, ReceiptUnreadableError
from smartsplit.services.receipt_output import receipt_from_model_output

FIXTURES = Path(__file__).parents[2] / "fixtures" / "receipts"


def recorded(name: str) -> object:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def parse(name: str, currency: str = "INR") -> object:
    return FakeReceiptParser(max_lines=150).parse(
        (FIXTURES / f"{name}.json").read_bytes(), "image/jpeg", currency
    )


def test_a_clean_receipt_becomes_typed_lines_in_integer_cents() -> None:
    receipt = receipt_from_model_output(recorded("grocery_taxed_mix"), "INR", 150)

    assert receipt.merchant == "Nature's Basket"
    assert receipt.purchased_at == date(2026, 11, 20)
    assert receipt.lines[0] == ParsedLine("2% MLK GAL", 2, 12000, False, 0.95, None)
    assert [line.taxed for line in receipt.lines] == [False, False, True, True]
    assert (receipt.tax_cents, receipt.other_adjustments_cents, receipt.total_cents) == (
        9600,
        0,
        122100,
    )
    assert receipt.warnings == ()


def test_tip_and_service_are_other_adjustments() -> None:
    receipt = receipt_from_model_output(recorded("restaurant_tip"), "INR", 150)

    assert receipt.other_adjustments_cents == 17800
    assert all(line.taxed is None for line in receipt.lines)
    assert receipt.warnings == ()


def test_a_linked_discount_keeps_its_link() -> None:
    receipt = receipt_from_model_output(recorded("milk_discount_linked"), "INR", 150)

    assert receipt.lines[1].discount_for_index == 0
    assert receipt.lines[3].discount_for_index is None


def test_an_unlinked_refund_is_an_ordinary_negative_line() -> None:
    # Matched by name later (Checkpoint A decision), so Sam's protein powder rule applies.
    receipt = receipt_from_model_output(recorded("protein_refund"), "INR", 150)

    assert receipt.lines[2] == ParsedLine("PROTEIN POWDER REFUND", 1, -250000, None, 0.9, None)
    assert receipt.warnings == ()


def test_a_total_that_does_not_add_up_is_a_warning_not_a_fix() -> None:
    receipt = receipt_from_model_output(recorded("total_mismatch"), "INR", 150)

    assert receipt.total_cents == 57000
    assert receipt.warnings == ("Lines, tax and extras add up to 56000, but the total says 57000.",)


def test_a_receipt_in_another_currency_gets_a_warning() -> None:
    # C14: nothing is converted.
    receipt = receipt_from_model_output(recorded("usd_receipt"), "INR", 150)

    assert receipt.currency == "USD"
    assert receipt.warnings == ("This receipt looks like USD, not INR. Nothing was converted.",)
    assert receipt.total_cents == 1170


@pytest.mark.parametrize(
    "name",
    ["invalid_quantity_zero", "invalid_fractional_cents", "invalid_total_zero"],
)
def test_invalid_output_is_unreadable(name: str) -> None:
    with pytest.raises(ReceiptUnreadableError):
        receipt_from_model_output(recorded(name), "INR", 150)


def base() -> dict[str, object]:
    return {
        "merchant": "  Shop\x00 ",
        "purchased_at": "yesterday",
        "currency": None,
        "lines": [
            {
                "name": "Thing",
                "quantity": 1,
                "amount_cents": 100,
                "taxed": None,
                "confidence": 1.7,
                "discount_for_index": 0,
            }
        ],
        "tax_cents": 0,
        "other_adjustments_cents": 0,
        "total_cents": 100,
    }


def test_soft_problems_are_fixed_quietly() -> None:
    receipt = receipt_from_model_output(base(), "INR", 150)

    assert receipt.merchant == "Shop"  # NUL dropped, trimmed
    assert receipt.purchased_at is None  # not a date
    assert receipt.lines[0].confidence == 1.0  # clamped
    assert receipt.lines[0].discount_for_index is None  # a line can't discount itself


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "   "),
        ("name", 5),
        ("quantity", True),
        ("amount_cents", "100"),
        ("taxed", "yes"),
        ("confidence", "high"),
        ("confidence", float("nan")),
    ],
)
def test_bad_line_fields_are_unreadable(field: str, value: object) -> None:
    data = base()
    lines = data["lines"]
    assert isinstance(lines, list)
    lines[0][field] = value

    with pytest.raises(ReceiptUnreadableError):
        receipt_from_model_output(data, "INR", 150)


@pytest.mark.parametrize("data", [[], {"lines": "x"}, {"lines": [7]}])
def test_wrong_shapes_are_unreadable(data: object) -> None:
    with pytest.raises(ReceiptUnreadableError):
        receipt_from_model_output(data, "INR", 150)


def test_too_many_lines_is_unreadable() -> None:
    with pytest.raises(ReceiptUnreadableError):
        receipt_from_model_output(recorded("grocery_taxed_mix"), "INR", 3)


def test_the_fake_parser_reads_recorded_output_and_refuses_photos() -> None:
    parser = FakeReceiptParser(max_lines=150)

    assert parse("restaurant_tip") == receipt_from_model_output(
        recorded("restaurant_tip"), "INR", 150
    )
    with pytest.raises(ReceiptUnreadableError):
        parser.parse(b"\xff\xd8\xff not json", "image/jpeg", "INR")
    assert parser.calls == 1
