"""Turning a model's receipt JSON into a validated ParsedReceipt (SPEC section 7).

The model's output is untrusted data: everything is checked, nothing is trusted to be the right
type. Shared by the Anthropic adapter (which retries once on invalid output) and the fakes.
"""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date
from math import isfinite

from smartsplit.ports.llm import ParsedLine, ParsedReceipt, ReceiptUnreadableError

RECEIPT_SCHEMA: Mapping[str, object] = {
    "type": "object",
    "properties": {
        "merchant": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "purchased_at": {
            "anyOf": [{"type": "string", "format": "date"}, {"type": "null"}],
            "description": "Purchase date as YYYY-MM-DD, or null if not printed.",
        },
        "currency": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "description": "ISO 4217 code of the receipt's currency, or null if unclear.",
        },
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "quantity": {"type": "integer"},
                    "amount_cents": {
                        "type": "integer",
                        "description": "Line total in the smallest currency unit; negative "
                        "for discounts and refunds.",
                    },
                    "taxed": {
                        "anyOf": [{"type": "boolean"}, {"type": "null"}],
                        "description": "Whether the receipt marks this line as taxed; null if "
                        "it doesn't say.",
                    },
                    "confidence": {"type": "number", "description": "0 to 1."},
                    "discount_for_index": {
                        "anyOf": [{"type": "integer"}, {"type": "null"}],
                        "description": "For a discount line: 0-based index of the line it "
                        "reduces, if clear; otherwise null.",
                    },
                },
                "required": [
                    "name",
                    "quantity",
                    "amount_cents",
                    "taxed",
                    "confidence",
                    "discount_for_index",
                ],
                "additionalProperties": False,
            },
        },
        "tax_cents": {"type": "integer"},
        "other_adjustments_cents": {
            "type": "integer",
            "description": "Tip + service charges - receipt-level discounts.",
        },
        "total_cents": {"type": "integer"},
    },
    "required": [
        "merchant",
        "purchased_at",
        "currency",
        "lines",
        "tax_cents",
        "other_adjustments_cents",
        "total_cents",
    ],
    "additionalProperties": False,
}
"""The JSON shape the parser asks the model for (structured output)."""


def receipt_from_model_output(data: object, install_currency: str, max_lines: int) -> ParsedReceipt:
    """Validate the model's JSON into a ParsedReceipt, or raise ReceiptUnreadableError.

    Hard failures: wrong types, non-integer cents, quantity < 1, empty names, more than
    `max_lines` lines, total ≤ 0. Soft fixes: confidence is clamped to 0-1, an impossible
    discount link or date becomes None, NUL characters are dropped (Postgres can't store them).
    A total that doesn't add up, or a foreign currency, becomes a warning, never a fix.
    """
    record = _mapping(data)
    lines = _list(record.get("lines"))
    if len(lines) > max_lines:
        raise ReceiptUnreadableError(f"more than {max_lines} lines")
    parsed_lines = tuple(_line(raw, index, len(lines)) for index, raw in enumerate(lines))
    tax = _cents(record.get("tax_cents"))
    other = _cents(record.get("other_adjustments_cents"))
    total = _cents(record.get("total_cents"))
    if total <= 0:
        raise ReceiptUnreadableError("total must be positive")
    currency = _optional_text(record.get("currency"))
    receipt = ParsedReceipt(
        merchant=_optional_text(record.get("merchant")),
        purchased_at=_optional_date(record.get("purchased_at")),
        lines=parsed_lines,
        tax_cents=tax,
        other_adjustments_cents=other,
        total_cents=total,
        currency=currency.upper() if currency else None,
        warnings=(),
    )
    return _with_warnings(receipt, install_currency)


def _with_warnings(receipt: ParsedReceipt, install_currency: str) -> ParsedReceipt:
    warnings: list[str] = []
    added = sum(line.amount_cents for line in receipt.lines)
    added += receipt.tax_cents + receipt.other_adjustments_cents
    if added != receipt.total_cents:
        warnings.append(
            f"Lines, tax and extras add up to {added}, but the total says {receipt.total_cents}."
        )
    if receipt.currency and receipt.currency != install_currency:
        warnings.append(
            f"This receipt looks like {receipt.currency}, not {install_currency}. "
            "Nothing was converted."
        )
    return replace(receipt, warnings=tuple(warnings))


def _line(raw: object, index: int, count: int) -> ParsedLine:
    record = _mapping(raw)
    name = _optional_text(record.get("name"))
    if not name:
        raise ReceiptUnreadableError("a line has no name")
    quantity = _integer(record.get("quantity"))
    if quantity < 1:
        raise ReceiptUnreadableError("quantity must be at least 1")
    taxed = record.get("taxed")
    if taxed is not None and not isinstance(taxed, bool):
        raise ReceiptUnreadableError("taxed must be true, false or null")
    link = record.get("discount_for_index")
    valid_link = (
        link
        if isinstance(link, int)
        and not isinstance(link, bool)
        and 0 <= link < count
        and link != index
        else None
    )
    return ParsedLine(
        name=name,
        quantity=quantity,
        amount_cents=_cents(record.get("amount_cents")),
        taxed=taxed,
        confidence=_confidence(record.get("confidence")),
        discount_for_index=valid_link,
    )


def _mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ReceiptUnreadableError("expected an object")
    return value


def _list(value: object) -> Sequence[object]:
    if not isinstance(value, list):
        raise ReceiptUnreadableError("expected a list of lines")
    return value


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReceiptUnreadableError("expected a whole number")
    return value


def _cents(value: object) -> int:
    """Money must arrive as integer cents; 12.5 is refused, never rounded (SPEC section 3)."""
    return _integer(value)


def _confidence(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not isfinite(value):
        raise ReceiptUnreadableError("confidence must be a number")
    return min(max(float(value), 0.0), 1.0)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ReceiptUnreadableError("expected text")
    cleaned = value.replace("\x00", "").strip()
    return cleaned or None


def _optional_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
