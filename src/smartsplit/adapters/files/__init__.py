"""Filesystem ImageStore (SPEC section 12.4)."""

import mimetypes
import uuid
from datetime import datetime
from pathlib import Path


class FileImageStore:
    """Images as files named `<uuid hex><ext>` in one directory; the file name is the image_ref."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def save(self, data: bytes, mime_type: str) -> str:
        extension = mimetypes.guess_extension(mime_type) or ".bin"
        image_ref = f"{uuid.uuid4().hex}{extension}"
        self._path(image_ref).write_bytes(data)
        return image_ref

    def load(self, image_ref: str) -> bytes:
        path = self._path(image_ref)
        if not path.is_file():
            raise KeyError(image_ref)
        return path.read_bytes()

    def prune(self, older_than: datetime) -> int:
        cutoff = older_than.timestamp()
        old = [p for p in self._directory.iterdir() if p.is_file() and p.stat().st_mtime < cutoff]
        for path in old:
            path.unlink()
        return len(old)

    def _path(self, image_ref: str) -> Path:
        """Refuse refs that could escape the image directory."""
        if Path(image_ref).name != image_ref or image_ref.startswith("."):
            raise KeyError(image_ref)
        return self._directory / image_ref
