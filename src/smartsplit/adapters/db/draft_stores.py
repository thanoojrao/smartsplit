"""Postgres stores for receipts, drafts, prompts and processed messages."""

from collections.abc import Collection, Sequence
from datetime import datetime

from sqlalchemy import Row, insert, select, update

from smartsplit.adapters.db import tables as t
from smartsplit.adapters.db.base import Store, require_one
from smartsplit.adapters.db.mapping import context_from, context_group_id, key_from
from smartsplit.domain.codec import decode, encode
from smartsplit.domain.enums import (
    DraftState,
    PromptKind,
    PromptStatus,
)
from smartsplit.domain.messages import OutboundMessage
from smartsplit.domain.model import BillDraft, LineItem, Receipt
from smartsplit.domain.prompts import (
    ProcessedMessage,
    Prompt,
    PromptAnswer,
    PromptPayload,
)
from smartsplit.domain.values import Context, ConversationKey, Override
from smartsplit.ports.errors import StaleDraftError
from smartsplit.ports.repository import IDLE_DRAFT_STATES, OPEN_DRAFT_STATES


class ReceiptStore(Store):
    def get(self, receipt_id: str) -> Receipt | None:
        row = self._execute(select(t.receipts).where(t.receipts.c.id == receipt_id)).first()
        if row is None:
            return None
        m = row._mapping
        return Receipt(
            m["id"],
            m["image_ref"],
            m["mime_type"],
            m["merchant"],
            m["purchased_at"],
            decode(m["line_items"], tuple[LineItem, ...]),
            m["tax_cents"],
            m["other_adjustments_cents"],
            m["total_cents"],
            tuple(m["warnings"]),
        )

    def add(self, receipt: Receipt) -> None:
        self._execute(
            insert(t.receipts).values(
                id=receipt.id,
                image_ref=receipt.image_ref,
                mime_type=receipt.mime_type,
                merchant=receipt.merchant,
                purchased_at=receipt.purchased_at,
                line_items=encode(receipt.line_items),
                tax_cents=receipt.tax_cents,
                other_adjustments_cents=receipt.other_adjustments_cents,
                total_cents=receipt.total_cents,
                warnings=list(receipt.warnings),
            )
        )


def _draft(row: Row[tuple[object, ...]]) -> BillDraft:
    m = row._mapping
    return BillDraft(
        id=m["id"],
        conversation=key_from(m["channel"], m["ref"]),
        context=context_from(m["context_group_id"]),
        added_by=m["added_by"],
        payer_id=m["payer_id"],
        receipt_id=m["receipt_id"],
        image_ref=m["image_ref"],
        image_mime_type=m["image_mime_type"],
        description=m["description"],
        purchased_at=m["purchased_at"],
        lines=decode(m["lines"], tuple[LineItem, ...]),
        tax_cents=m["tax_cents"],
        other_adjustments_cents=m["other_adjustments_cents"],
        total_cents=m["total_cents"],
        accepted_difference_cents=m["accepted_difference_cents"],
        participants=tuple(m["participants"]),
        overrides=decode(m["overrides"], tuple[tuple[str, Override], ...]),
        owes_all_id=m["owes_all_id"],
        state=DraftState(m["state"]),
        created_at=m["created_at"],
        last_activity_at=m["last_activity_at"],
        reminded_at=m["reminded_at"],
    )


def _draft_values(draft: BillDraft) -> dict[str, object]:
    return {
        "id": draft.id,
        "channel": draft.conversation.channel,
        "ref": draft.conversation.ref,
        "context_group_id": context_group_id(draft.context),
        "added_by": draft.added_by,
        "payer_id": draft.payer_id,
        "receipt_id": draft.receipt_id,
        "image_ref": draft.image_ref,
        "image_mime_type": draft.image_mime_type,
        "description": draft.description,
        "purchased_at": draft.purchased_at,
        "lines": encode(draft.lines),
        "tax_cents": draft.tax_cents,
        "other_adjustments_cents": draft.other_adjustments_cents,
        "total_cents": draft.total_cents,
        "accepted_difference_cents": draft.accepted_difference_cents,
        "participants": list(draft.participants),
        "overrides": encode(draft.overrides),
        "owes_all_id": draft.owes_all_id,
        "state": draft.state.value,
        "created_at": draft.created_at,
        "last_activity_at": draft.last_activity_at,
        "reminded_at": draft.reminded_at,
    }


class DraftStore(Store):
    def get(self, draft_id: str) -> BillDraft | None:
        row = self._execute(select(t.drafts).where(t.drafts.c.id == draft_id)).first()
        return _draft(row) if row else None

    def add(self, draft: BillDraft) -> None:
        self._execute(insert(t.drafts).values(_draft_values(draft)))

    def update(self, draft: BillDraft, expected_state: DraftState) -> None:
        c = t.drafts.c
        changed = self._execute(
            update(t.drafts)
            .where(c.id == draft.id, c.state == expected_state.value)
            .values(_draft_values(draft))
        ).rowcount
        if changed == 1:
            return
        if self.get(draft.id) is None:
            raise KeyError(draft.id)
        raise StaleDraftError(draft.id)

    def for_conversation(
        self, key: ConversationKey, states: Collection[DraftState]
    ) -> tuple[BillDraft, ...]:
        c = t.drafts.c
        rows = self._execute(
            select(t.drafts)
            .where(
                c.channel == key.channel,
                c.ref == key.ref,
                c.state.in_([state.value for state in states]),
            )
            .order_by(c.created_at, c.seq)
        )
        return tuple(_draft(r) for r in rows)

    def open_in_context(self, context: Context) -> tuple[BillDraft, ...]:
        c = t.drafts.c
        group_id = context_group_id(context)
        rows = self._execute(
            select(t.drafts)
            .where(
                c.context_group_id.is_(None)
                if group_id is None
                else c.context_group_id == group_id,
                c.state.in_([state.value for state in OPEN_DRAFT_STATES]),
            )
            .order_by(c.created_at, c.seq)
        )
        return tuple(_draft(r) for r in rows)

    def due_for_reminder_or_expiry(self, idle_since: datetime) -> tuple[BillDraft, ...]:
        c = t.drafts.c
        rows = self._execute(
            select(t.drafts)
            .where(
                c.state.in_([state.value for state in IDLE_DRAFT_STATES]),
                c.last_activity_at <= idle_since,
            )
            .order_by(c.created_at, c.seq)
        )
        return tuple(_draft(r) for r in rows)


def _prompt(row: Row[tuple[object, ...]]) -> Prompt:
    m = row._mapping
    return Prompt(
        id=m["id"],
        conversation=key_from(m["channel"], m["ref"]),
        draft_id=m["draft_id"],
        kind=PromptKind(m["kind"]),
        payload=decode(m["payload"], PromptPayload),
        status=PromptStatus(m["status"]),
        asked_of=m["asked_of"],
        created_by=m["created_by"],
        created_at=m["created_at"],
        answers=decode(m["answers"], tuple[PromptAnswer, ...]),
    )


def _prompt_values(prompt: Prompt) -> dict[str, object]:
    return {
        "id": prompt.id,
        "channel": prompt.conversation.channel,
        "ref": prompt.conversation.ref,
        "draft_id": prompt.draft_id,
        "kind": prompt.kind.value,
        "payload": encode(prompt.payload),
        "status": prompt.status.value,
        "asked_of": prompt.asked_of,
        "created_by": prompt.created_by,
        "created_at": prompt.created_at,
        "answers": encode(prompt.answers),
    }


class PromptStore(Store):
    def get(self, prompt_id: str) -> Prompt | None:
        row = self._execute(select(t.prompts).where(t.prompts.c.id == prompt_id)).first()
        return _prompt(row) if row else None

    def add(self, prompt: Prompt) -> None:
        self._execute(insert(t.prompts).values(_prompt_values(prompt)))

    def update(self, prompt: Prompt) -> None:
        require_one(
            self._execute(
                update(t.prompts).where(t.prompts.c.id == prompt.id).values(_prompt_values(prompt))
            ).rowcount
        )

    def for_conversation(
        self, key: ConversationKey, statuses: Collection[PromptStatus]
    ) -> tuple[Prompt, ...]:
        c = t.prompts.c
        rows = self._execute(
            select(t.prompts)
            .where(
                c.channel == key.channel,
                c.ref == key.ref,
                c.status.in_([status.value for status in statuses]),
            )
            .order_by(c.created_at, c.seq)
        )
        return tuple(_prompt(r) for r in rows)

    def for_draft(self, draft_id: str) -> tuple[Prompt, ...]:
        c = t.prompts.c
        rows = self._execute(
            select(t.prompts).where(c.draft_id == draft_id).order_by(c.created_at, c.seq)
        )
        return tuple(_prompt(r) for r in rows)


class ProcessedStore(Store):
    def get(self, key: ConversationKey, message_id: str) -> ProcessedMessage | None:
        c = t.processed_messages.c
        row = self._execute(
            select(c.replies, c.processed_at).where(
                c.channel == key.channel, c.ref == key.ref, c.message_id == message_id
            )
        ).first()
        if row is None:
            return None
        return ProcessedMessage(
            key, message_id, decode(row.replies, tuple[OutboundMessage, ...]), row.processed_at
        )

    def add_replies(
        self, key: ConversationKey, message_id: str, replies: Sequence[OutboundMessage]
    ) -> None:
        stored = self.get(key, message_id)
        if stored is None:
            raise KeyError((key, message_id))
        c = t.processed_messages.c
        self._execute(
            update(t.processed_messages)
            .where(c.channel == key.channel, c.ref == key.ref, c.message_id == message_id)
            .values(replies=encode((*stored.replies, *replies)))
        )

    def add(self, processed: ProcessedMessage) -> None:
        self._execute(
            insert(t.processed_messages).values(
                channel=processed.key.channel,
                ref=processed.key.ref,
                message_id=processed.message_id,
                replies=encode(processed.replies),
                processed_at=processed.processed_at,
            )
        )
