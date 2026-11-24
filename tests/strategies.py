"""Hypothesis strategies for the shapes stored as JSON (codec round-trip tests)."""

from datetime import UTC, datetime, timedelta, timezone
from typing import cast

from hypothesis import strategies as st

from smartsplit.domain.enums import MatchHow
from smartsplit.domain.messages import OutboundMessage
from smartsplit.domain.model import Bill, LineItem
from smartsplit.domain.prompts import ChatRef, NotificationArgs, Prompt, PromptPayload
from smartsplit.domain.tools import EditDraft, PendingArgs
from smartsplit.domain.values import Override

ZONES = st.sampled_from(
    [UTC, timezone(timedelta(hours=5, minutes=30)), timezone(-timedelta(hours=8))]
)
st.register_type_strategy(datetime, st.datetimes(timezones=ZONES))
"""Global on purpose, for the whole test session: every datetime in the domain is timezone-
aware, so `from_type` must never produce a naive one; mixed zones must keep their instant."""

STORED_SHAPES: list[object] = [
    PendingArgs,
    EditDraft,
    tuple[ChatRef, ...],
    PromptPayload,
    Prompt,
    tuple[tuple[str, Override], ...],
    NotificationArgs,
    tuple[OutboundMessage, ...],
    Bill,
]

RECEIPT_LINES = st.lists(
    st.builds(
        LineItem,
        confidence=st.floats(min_value=0, max_value=1),
        match_how=st.sampled_from(MatchHow),
    ),
    max_size=4,
).map(tuple)


def of_shape(shape: object) -> st.SearchStrategy[object]:
    """Unions and aliases are valid type expressions for Hypothesis, but not `type[...]` to mypy."""
    return st.from_type(cast("type[object]", shape))
