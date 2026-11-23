"""The codec's output survives a real Postgres JSONB column, not just JSON text."""

import json

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st
from sqlalchemy import Engine, Text, bindparam, cast, select
from sqlalchemy.dialects.postgresql import JSONB

from smartsplit.adapters.db.codec import decode, encode
from smartsplit.domain.model import LineItem
from tests.strategies import RECEIPT_LINES, STORED_SHAPES, of_shape


@pytest.mark.db
@given(data=st.data(), shape=st.sampled_from(STORED_SHAPES))
def test_stored_shapes_round_trip_through_jsonb(
    pg_engine: Engine, data: st.DataObject, shape: object
) -> None:
    value = data.draw(of_shape(shape))
    encoded = encode(value)
    # Postgres can't store NUL in text or JSONB; inbound text is cleaned first (follow-up, M5/M7).
    assume("\\u0000" not in json.dumps(encoded))

    with pg_engine.connect() as connection:
        as_jsonb = cast(bindparam("doc", json.dumps(encoded), type_=Text), JSONB)
        stored = connection.execute(select(as_jsonb)).scalar_one()

    assert decode(stored, shape) == value


@pytest.mark.db
@given(lines=RECEIPT_LINES)
def test_receipt_lines_round_trip_through_jsonb(
    pg_engine: Engine, lines: tuple[LineItem, ...]
) -> None:
    encoded = encode(lines)
    assume("\\u0000" not in json.dumps(encoded))

    with pg_engine.connect() as connection:
        as_jsonb = cast(bindparam("doc", json.dumps(encoded), type_=Text), JSONB)
        stored = connection.execute(select(as_jsonb)).scalar_one()

    assert decode(stored, tuple[LineItem, ...]) == lines
