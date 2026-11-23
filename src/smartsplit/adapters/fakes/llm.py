"""Fake model-backed ports for tests and the demo."""

from collections.abc import Mapping, Sequence

from smartsplit.domain import normalize_item_name


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
