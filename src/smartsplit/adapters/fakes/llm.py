"""Fake model-backed ports for tests and the demo."""

import json
from collections.abc import Mapping, Sequence

from smartsplit.domain import normalize_item_name
from smartsplit.ports.llm import ParsedReceipt, ReceiptUnreadableError
from smartsplit.services.receipt_output import receipt_from_model_output


class FakeCanonicalizer:
    """Answers from a fixed table (normalized name → key); unknown names are new items.

    Records every call, so tests can check the model is only asked when nothing else matched.
    """

    def __init__(self, answers: Mapping[str, str] | None = None) -> None:
        self._answers = {normalize_item_name(k): v for k, v in (answers or {}).items()}
        self.calls: list[str] = []

    def canonicalize(self, name: str, known_keys: Sequence[str]) -> str:
        self.calls.append(name)
        normalized = normalize_item_name(name)
        return self._answers.get(normalized, normalized)


class FakeReceiptParser:
    """Reads "images" that are recorded model output (`tests/fixtures/receipts/*.json`).

    The bytes go through the same validation as the real parser, so tests and the CLI demo
    see exactly what a recorded model answer would produce. Anything that isn't JSON is
    unreadable, like a blurry photo.
    """

    def __init__(self, max_lines: int) -> None:
        self._max_lines = max_lines
        self.calls = 0

    def parse(self, image: bytes, mime_type: str, currency: str) -> ParsedReceipt:
        self.calls += 1
        try:
            recorded = json.loads(image.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ReceiptUnreadableError("not a recorded receipt") from error
        return receipt_from_model_output(recorded, currency, self._max_lines)
