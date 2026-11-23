"""In-memory ImageStore."""

from datetime import datetime

from smartsplit.ports.system import Clock, IdGenerator


class InMemoryImageStore:
    def __init__(self, clock: Clock, ids: IdGenerator) -> None:
        self._clock = clock
        self._ids = ids
        self._images: dict[str, tuple[bytes, datetime]] = {}

    def save(self, data: bytes, mime_type: str) -> str:
        image_ref = self._ids.new_id()
        self._images[image_ref] = (data, self._clock.now())
        return image_ref

    def load(self, image_ref: str) -> bytes:
        return self._images[image_ref][0]

    def prune(self, older_than: datetime) -> int:
        old = [ref for ref, (_, saved_at) in self._images.items() if saved_at < older_than]
        for ref in old:
            del self._images[ref]
        return len(old)
