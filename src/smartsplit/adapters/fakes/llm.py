"""Fake model-backed ports for tests and the demo."""

import json
from collections.abc import Mapping, Sequence

from smartsplit.domain import normalize_item_name
from smartsplit.ports.llm import CountCall, NotAReceipt, ParsedReceipt, ReceiptUnreadableError
from smartsplit.services.receipt_output import read_model_output

DEMO_ITEMS = {
    "2% MLK GAL": "milk",
    "OAT MLK 1L": "milk",
    "Whey Protein Powder 1kg": "protein powder",
    "PROTEIN POWDER REFUND": "protein powder",
}
"""What the offline demo's stand-in "model" knows about the recorded receipts' names."""


class FakeCanonicalizer:
    """Answers from a fixed table (normalized name → key); unknown names are new items.

    Records every call, so tests can check the model is only asked when nothing else matched.
    """

    def __init__(self, answers: Mapping[str, str] | None = None) -> None:
        self._answers = {normalize_item_name(k): v for k, v in (answers or {}).items()}
        self.calls: list[str] = []

    def canonicalize(
        self, name: str, known_keys: Sequence[str], timeout_seconds: float, count_call: CountCall
    ) -> str:
        count_call()
        self.calls.append(name)
        normalized = normalize_item_name(name)
        return self._answers.get(normalized, normalized)


class FakeReceiptParser:
    """Reads "images" that are recorded model output (`tests/fixtures/receipts/*.json`).

    The bytes go through the same validation as the real parser, so tests and the demo see
    exactly what a recorded model answer would produce (`{"is_receipt": false}` is a photo
    that isn't a receipt). Anything that isn't JSON is unreadable, like a blurry photo.
    """

    def __init__(self, max_lines: int) -> None:
        self._max_lines = max_lines
        self.calls = 0

    def parse(
        self,
        image: bytes,
        mime_type: str,
        currency: str,
        timeout_seconds: float,
        count_call: CountCall,
    ) -> ParsedReceipt | NotAReceipt:
        count_call()
        self.calls += 1
        try:
            recorded = json.loads(image.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ReceiptUnreadableError("not a recorded receipt") from error
        return read_model_output(recorded, currency, self._max_lines)
