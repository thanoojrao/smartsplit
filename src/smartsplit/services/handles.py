"""Short per-turn handles that stand for things, so no id reaches the model (SPEC 8.2).

`P2` a person, `B3` a saved bill, `D1` a draft, `Q1` an open question, `A1` a pending action,
`G1` a group, `T1` a payment. They are numbered per turn in the order they are issued; line
handles (`L4`) are the line numbers people see, so they are parsed, not issued.
"""

import re
from dataclasses import dataclass, field

from smartsplit.domain.prompts import RefKind
from smartsplit.services.errors import NotAllowedError

PREFIX: dict[RefKind, str] = {
    "person": "P",
    "bill": "B",
    "draft": "D",
    "line": "L",
    "question": "Q",
    "action": "A",
    "group": "G",
    "payment": "T",
}
_KIND = {prefix: kind for kind, prefix in PREFIX.items()}
HANDLE = re.compile(r"\b([PBDLQAGT])(\d{1,4})\b")
SELF = "me"


@dataclass(slots=True)
class Handles:
    """The turn's handle ↔ id map; `label`s are how a handle reads in the reply."""

    speaker_id: str = ""
    _ids: dict[str, str] = field(default_factory=dict)
    _by_id: dict[tuple[RefKind, str], str] = field(default_factory=dict)
    _labels: dict[str, str] = field(default_factory=dict)

    def issue(self, kind: RefKind, item_id: str, label: str) -> str:
        """The handle for this thing, reusing the one already issued this turn."""
        existing = self._by_id.get((kind, item_id))
        if existing is not None:
            return existing
        prefix = PREFIX[kind]
        handle = f"{prefix}{sum(1 for h in self._ids if h.startswith(prefix)) + 1}"
        self._ids[handle] = item_id
        self._by_id[(kind, item_id)] = handle
        self._labels[handle] = label
        return handle

    def resolve(self, handle: str, *kinds: RefKind) -> str:
        """The id behind a handle of one of these kinds; anything else is refused."""
        cleaned = handle.strip()
        if cleaned.casefold() == SELF and "person" in kinds and self.speaker_id:
            return self.speaker_id
        item_id = self._ids.get(cleaned.upper())
        if item_id is None or _KIND[cleaned.upper()[0]] not in kinds:
            wanted = " or ".join(PREFIX[k] for k in kinds)
            raise NotAllowedError(f"{handle} isn't a {wanted} handle from this conversation.")
        return item_id

    def kind_of(self, handle: str) -> RefKind | None:
        """The kind of an issued handle, or None."""
        cleaned = handle.strip().upper()
        return _KIND[cleaned[0]] if cleaned in self._ids else None

    def label(self, handle: str) -> str | None:
        return self._labels.get(handle.upper())


def line_number(handle: str) -> int:
    """ "L4" (or "4") → 4: the line number people see."""
    cleaned = handle.strip().upper().removeprefix("L")
    if not cleaned.isdigit() or int(cleaned) < 1:
        raise NotAllowedError(f"{handle} isn't a line number.")
    return int(cleaned)
