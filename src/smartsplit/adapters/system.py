"""The real clock and id generator (the fakes live in `adapters.fakes.system`)."""

import uuid
from datetime import UTC, datetime


class SystemClock:
    """Timezone-aware UTC now; local days are worked out from settings where they matter."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class UuidIds:
    """Random ids: unique across processes, so two servers can share one database."""

    def new_id(self) -> str:
        return uuid.uuid4().hex
