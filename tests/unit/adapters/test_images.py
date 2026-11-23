"""Filesystem and in-memory ImageStores (SPEC section 12.4)."""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from smartsplit.adapters.fakes.images import InMemoryImageStore
from smartsplit.adapters.fakes.system import FixedClock, SequentialIds
from smartsplit.adapters.files import FileImageStore

T0 = datetime(2026, 11, 1, tzinfo=UTC)


def test_file_store_saves_loads_and_names_by_type(tmp_path: Path) -> None:
    store = FileImageStore(tmp_path / "images")

    ref = store.save(b"jpeg bytes", "image/jpeg")

    assert ref.endswith(".jpg")
    assert store.load(ref) == b"jpeg bytes"
    assert store.save(b"x", "application/x-unknown").endswith(".bin")


@pytest.mark.parametrize("ref", ["missing.jpg", "../secret", "a/b.jpg", ".hidden"])
def test_file_store_refuses_missing_and_unsafe_refs(tmp_path: Path, ref: str) -> None:
    with pytest.raises(KeyError):
        FileImageStore(tmp_path).load(ref)


def test_file_store_prunes_old_images(tmp_path: Path) -> None:
    store = FileImageStore(tmp_path)
    old, new = store.save(b"old", "image/png"), store.save(b"new", "image/png")
    old_time = (T0 - timedelta(days=40)).timestamp()
    os.utime(tmp_path / old, (old_time, old_time))

    assert store.prune(older_than=T0 - timedelta(days=30)) == 1
    assert store.load(new) == b"new"
    with pytest.raises(KeyError):
        store.load(old)


def test_in_memory_store_saves_loads_and_prunes() -> None:
    clock = FixedClock(T0)
    store = InMemoryImageStore(clock, SequentialIds("img"))
    old = store.save(b"old", "image/png")
    clock.advance(timedelta(days=2))
    new = store.save(b"new", "image/png")

    assert store.prune(older_than=T0 + timedelta(days=1)) == 1
    assert store.load(new) == b"new"
    with pytest.raises(KeyError):
        store.load(old)
