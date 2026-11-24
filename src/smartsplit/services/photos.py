"""Photos read on arrival (SPEC 7, 10.4).

A photo is read before the turn, outside the conversation lock, and the outcome is stored at
once as a `PhotoRead` (with its `Receipt`) in its own transaction keyed by (chat, message). A
retry of the same message, or a turn that rolls back, reuses it, so a photo is never read
twice and a photo sent on its own can be picked up by the sender's next message.
"""

from dataclasses import dataclass
from datetime import datetime

from smartsplit.domain.enums import MatchHow, PhotoOutcome
from smartsplit.domain.messages import ImageAttachment
from smartsplit.domain.model import LineItem, PhotoRead, Receipt
from smartsplit.domain.values import ConversationKey
from smartsplit.ports.errors import DuplicateKeyError
from smartsplit.ports.images import ImageStore
from smartsplit.ports.llm import NotAReceipt, ParsedReceipt, ReceiptParser, ReceiptUnreadableError
from smartsplit.ports.repository import Repository
from smartsplit.ports.system import IdGenerator
from smartsplit.services.usage import Meter


@dataclass(frozen=True, slots=True)
class PhotoReader:
    repository: Repository
    images: ImageStore
    parser: ReceiptParser
    ids: IdGenerator
    currency: str

    def read(
        self,
        key: ConversationKey,
        message_id: str,
        sender_id: str,
        image: ImageAttachment,
        *,
        now: datetime,
        meter: Meter,
        timeout_seconds: float,
    ) -> PhotoRead:
        """The stored read of this message's photo, reading it now if it is new.

        Raises LlmUnavailableError (nothing is stored then, so a retry reads it again).
        """
        with self.repository.unit_of_work() as uow:
            done = uow.photos.get(key, message_id)
        if done is not None:
            return done
        image_ref = self.images.save(image.data, image.mime_type)
        try:
            parsed = self.parser.parse(
                image.data, image.mime_type, self.currency, timeout_seconds, meter.count
            )
        except ReceiptUnreadableError:
            parsed = None
        return self._store(
            key,
            message_id,
            sender_id=sender_id,
            image_ref=image_ref,
            mime_type=image.mime_type,
            parsed=parsed,
            now=now,
        )

    def _store(
        self,
        key: ConversationKey,
        message_id: str,
        *,
        sender_id: str,
        image_ref: str,
        mime_type: str,
        parsed: ParsedReceipt | NotAReceipt | None,
        now: datetime,
    ) -> PhotoRead:
        receipt = (
            receipt_from(self.ids, image_ref, mime_type, parsed)
            if isinstance(parsed, ParsedReceipt)
            else None
        )
        outcome = (
            PhotoOutcome.RECEIPT
            if receipt
            else PhotoOutcome.NOT_A_RECEIPT
            if isinstance(parsed, NotAReceipt)
            else PhotoOutcome.UNREADABLE
        )
        receipt_id = receipt.id if receipt else None
        photo = PhotoRead(key, message_id, sender_id, outcome, receipt_id, None, now)
        try:
            with self.repository.unit_of_work() as uow:
                if receipt is not None:
                    uow.receipts.add(receipt)
                uow.photos.add(photo)
        except DuplicateKeyError:  # the same message, read at the same time by a retry
            with self.repository.unit_of_work() as uow:
                stored = uow.photos.get(key, message_id)
            if stored is None:
                raise
            return stored
        return photo


def receipt_from(
    ids: IdGenerator, image_ref: str, mime_type: str, parsed: ParsedReceipt
) -> Receipt:
    """The immutable parse record; the parser's discount index becomes a line id, and lines
    get their item keys only when a draft uses them (matching depends on where it's filed)."""
    line_ids = [ids.new_id() for _ in parsed.lines]
    lines = tuple(
        LineItem(
            id=line_ids[n],
            position=n + 1,
            name=line.name,
            quantity=line.quantity,
            amount_cents=line.amount_cents,
            taxed=line.taxed,
            confidence=line.confidence,
            canonical=None,
            discount_for=line_ids[line.discount_for_index]
            if line.discount_for_index is not None
            else None,
            match_how=MatchHow.NONE,
            match_is_new=False,
        )
        for n, line in enumerate(parsed.lines)
    )
    return Receipt(
        ids.new_id(),
        image_ref,
        mime_type,
        parsed.merchant,
        parsed.purchased_at,
        lines,
        parsed.tax_cents,
        parsed.other_adjustments_cents,
        parsed.total_cents,
        parsed.warnings,
    )
