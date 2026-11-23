"""Fake clock and ids."""

from datetime import UTC, datetime, timedelta

import pytest

from smartsplit.adapters.fakes.system import FixedClock, SequentialIds


def test_fixed_clock_moves_only_when_told() -> None:
    clock = FixedClock(datetime(2026, 11, 1, tzinfo=UTC))
    clock.advance(timedelta(hours=25))

    assert clock.now() == datetime(2026, 11, 2, 1, tzinfo=UTC)


def test_fixed_clock_needs_an_aware_time() -> None:
    with pytest.raises(ValueError):
        FixedClock(datetime.fromisoformat("2026-11-01T00:00"))  # naive: no offset


def test_sequential_ids() -> None:
    ids = SequentialIds("b")

    assert [ids.new_id(), ids.new_id()] == ["b0001", "b0002"]
