"""In-memory stores for receipts, drafts, prompts, bills, payments and the outbox."""

from collections.abc import Collection
from dataclasses import replace
from datetime import datetime

from smartsplit.adapters.fakes.base import insert, replace_existing
from smartsplit.adapters.fakes.people_stores import PeopleStore
from smartsplit.domain.enums import DraftState, NotificationKind, PromptStatus
from smartsplit.domain.model import (
    Bill,
    BillDraft,
    Receipt,
    Settlement,
)
from smartsplit.domain.prompts import Notification, ProcessedMessage, Prompt
from smartsplit.domain.values import Context, ConversationKey
from smartsplit.ports.repository import IDLE_DRAFT_STATES, StaleDraftError


class ReceiptStore:
    def __init__(self) -> None:
        self.records: dict[str, Receipt] = {}

    def get(self, receipt_id: str) -> Receipt | None:
        return self.records.get(receipt_id)

    def add(self, receipt: Receipt) -> None:
        insert(self.records, receipt.id, receipt)


class DraftStore:
    def __init__(self) -> None:
        self.records: dict[str, BillDraft] = {}

    def get(self, draft_id: str) -> BillDraft | None:
        return self.records.get(draft_id)

    def add(self, draft: BillDraft) -> None:
        insert(self.records, draft.id, draft)

    def update(self, draft: BillDraft, expected_state: DraftState) -> None:
        current = self.records.get(draft.id)
        if current is None:
            raise KeyError(draft.id)
        if current.state is not expected_state:
            raise StaleDraftError(draft.id)
        self.records[draft.id] = draft

    def for_conversation(
        self, key: ConversationKey, states: Collection[DraftState]
    ) -> tuple[BillDraft, ...]:
        mine = [d for d in self.records.values() if d.conversation == key and d.state in states]
        return tuple(sorted(mine, key=lambda d: d.created_at))

    def due_for_reminder_or_expiry(self, idle_since: datetime) -> tuple[BillDraft, ...]:
        due = [
            d
            for d in self.records.values()
            if d.state in IDLE_DRAFT_STATES and d.last_activity_at <= idle_since
        ]
        return tuple(sorted(due, key=lambda d: d.created_at))


class PromptStore:
    def __init__(self) -> None:
        self.records: dict[str, Prompt] = {}

    def get(self, prompt_id: str) -> Prompt | None:
        return self.records.get(prompt_id)

    def add(self, prompt: Prompt) -> None:
        insert(self.records, prompt.id, prompt)

    def update(self, prompt: Prompt) -> None:
        replace_existing(self.records, prompt.id, prompt)

    def for_conversation(
        self, key: ConversationKey, statuses: Collection[PromptStatus]
    ) -> tuple[Prompt, ...]:
        mine = [p for p in self.records.values() if p.conversation == key and p.status in statuses]
        return tuple(sorted(mine, key=lambda p: p.created_at))

    def for_draft(self, draft_id: str) -> tuple[Prompt, ...]:
        mine = [p for p in self.records.values() if p.draft_id == draft_id]
        return tuple(sorted(mine, key=lambda p: p.created_at))


class BillStore:
    def __init__(self) -> None:
        self.records: dict[str, Bill] = {}

    def get(self, bill_id: str) -> Bill | None:
        return self.records.get(bill_id)

    def add(self, bill: Bill) -> None:
        insert(self.records, bill.id, bill)

    def for_context(self, context: Context) -> tuple[Bill, ...]:
        mine = [b for b in self.records.values() if b.context == context]
        return tuple(sorted(mine, key=lambda b: b.created_at))

    def for_participant(self, person_id: str) -> tuple[Bill, ...]:
        mine = [b for b in self.records.values() if person_id in b.participants]
        return tuple(sorted(mine, key=lambda b: b.created_at))


class SettlementStore:
    def __init__(self) -> None:
        self.records: dict[str, Settlement] = {}

    def add(self, settlement: Settlement) -> None:
        insert(self.records, settlement.id, settlement)

    def for_context(self, context: Context) -> tuple[Settlement, ...]:
        mine = [s for s in self.records.values() if s.context == context]
        return tuple(sorted(mine, key=lambda s: s.created_at))

    def for_payment(self, payment_id: str) -> tuple[Settlement, ...]:
        return tuple(s for s in self.records.values() if s.payment_id == payment_id)


class NotificationStore:
    def __init__(self, people: PeopleStore) -> None:
        self.records: dict[str, Notification] = {}
        self._people = people

    def add(self, notification: Notification) -> None:
        insert(self.records, notification.id, notification)

    def claim_due(
        self, now: datetime, limit: int, per_person_daily_cap: int, day_start: datetime
    ) -> tuple[Notification, ...]:
        """Same batch semantics as Postgres: take up to `limit` deliverable rows, then drop
        any that would push a person past the cap within this batch."""
        sent_today: dict[str, int] = {}
        for n in self.records.values():
            if n.sent_at is not None and n.sent_at >= day_start and _counts_toward_cap(n):
                sent_today[n.recipient_id] = sent_today.get(n.recipient_id, 0) + 1
        unsent = sorted(
            (n for n in self.records.values() if n.sent_at is None), key=lambda n: n.created_at
        )
        batch = [n for n in unsent if self._deliverable(n, sent_today, per_person_daily_cap)]
        claimed: list[Notification] = []
        for n in batch[:limit]:
            if _counts_toward_cap(n):
                count = sent_today.get(n.recipient_id, 0)
                if count >= per_person_daily_cap:
                    continue
                sent_today[n.recipient_id] = count + 1
            sent = replace(n, sent_at=now)
            self.records[n.id] = sent
            claimed.append(sent)
        return tuple(claimed)

    def _deliverable(self, n: Notification, sent_today: dict[str, int], cap: int) -> bool:
        if not _counts_toward_cap(n):
            return True
        person = self._people.get(n.recipient_id)
        return (
            person is not None
            and person.has_used_bot
            and person.notifications_enabled
            and sent_today.get(n.recipient_id, 0) < cap
        )


def _counts_toward_cap(notification: Notification) -> bool:
    return notification.kind is not NotificationKind.REQUESTED_REPLY


class ProcessedStore:
    def __init__(self) -> None:
        self.records: dict[tuple[ConversationKey, str], ProcessedMessage] = {}

    def get(self, key: ConversationKey, message_id: str) -> ProcessedMessage | None:
        return self.records.get((key, message_id))

    def add(self, processed: ProcessedMessage) -> None:
        insert(self.records, (processed.key, processed.message_id), processed)
