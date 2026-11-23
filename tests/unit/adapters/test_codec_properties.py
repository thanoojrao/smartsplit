"""Property tests: every stored shape survives encode → JSON text → decode unchanged."""

import json

from hypothesis import given
from hypothesis import strategies as st

from smartsplit.adapters.db.codec import decode, encode
from smartsplit.domain.model import LineItem
from tests.strategies import RECEIPT_LINES, STORED_SHAPES, of_shape


def round_trip(value: object, hint: object) -> object:
    return decode(json.loads(json.dumps(encode(value))), hint)


@given(data=st.data(), shape=st.sampled_from(STORED_SHAPES))
def test_stored_shapes_round_trip(data: st.DataObject, shape: object) -> None:
    value = data.draw(of_shape(shape))

    assert round_trip(value, shape) == value


@given(lines=RECEIPT_LINES)
def test_receipt_lines_round_trip(lines: tuple[LineItem, ...]) -> None:
    assert round_trip(lines, tuple[LineItem, ...]) == lines
