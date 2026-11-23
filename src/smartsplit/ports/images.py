"""Receipt image storage (SPEC section 12.4)."""

from datetime import datetime
from typing import Protocol


class ImageStore(Protocol):
    def save(self, data: bytes, mime_type: str) -> str:
        """Store an image and return its `image_ref`, so a queued draft can reload it later."""
        ...

    def load(self, image_ref: str) -> bytes:
        """Raise KeyError if the image is gone (e.g. pruned)."""
        ...

    def prune(self, older_than: datetime) -> int:
        """Delete images stored before `older_than`; returns how many were deleted."""
        ...
