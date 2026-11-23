"""Postgres stores for bills, settlements and the notification outbox."""

from dataclasses import replace
from datetime import datetime

from sqlalchemy import ColumnElement, Row, and_, func, insert, or_, select, update

from smartsplit.adapters.db import tables as t
from smartsplit.adapters.db.base import Store
from smartsplit.adapters.db.codec import decode, encode
from smartsplit.adapters.db.mapping import context_from, context_group_id, key_from
from smartsplit.domain.enums import (
    NotificationKind,
    SettlementKind,
)
from smartsplit.domain.model import Bill, BillLine, Settlement
from smartsplit.domain.prompts import (
    Notification,
    NotificationArgs,
)
from smartsplit.domain.values import Context, Share


def _context_is(column: ColumnElement[str | None], context: Context) -> ColumnElement[bool]:
    group_id = context_group_id(context)
    return column.is_(None) if group_id is None else column == group_id


def _bill(row: Row[tuple[object, ...]]) -> Bill:
    m = row._mapping
    return Bill(
        id=m["id"],
        context=context_from(m["context_group_id"]),
        origin=key_from(m["origin_channel"], m["origin_ref"]),
        receipt_id=m["receipt_id"],
        payer_id=m["payer_id"],
        added_by=m["added_by"],
        description=m["description"],
        purchased_at=m["purchased_at"],
        participants=tuple(m["participants"]),
        lines=decode(m["lines"], tuple[BillLine, ...]),
        tax_cents=m["tax_cents"],
        other_adjustments_cents=m["other_adjustments_cents"],
        total_cents=m["total_cents"],
        shares=decode(m["shares"], tuple[Share, ...]),
        reverses_id=m["reverses_id"],
        replaces_id=m["replaces_id"],
        edit_reason=m["edit_reason"],
        created_at=m["created_at"],
    )


class BillStore(Store):
    def get(self, bill_id: str) -> Bill | None:
        row = self._db.execute(select(t.bills).where(t.bills.c.id == bill_id)).first()
        return _bill(row) if row else None

    def add(self, bill: Bill) -> None:
        self._db.execute(
            insert(t.bills).values(
                id=bill.id,
                context_group_id=context_group_id(bill.context),
                origin_channel=bill.origin.channel,
                origin_ref=bill.origin.ref,
                receipt_id=bill.receipt_id,
                payer_id=bill.payer_id,
                added_by=bill.added_by,
                description=bill.description,
                purchased_at=bill.purchased_at,
                participants=list(bill.participants),
                lines=encode(bill.lines),
                tax_cents=bill.tax_cents,
                other_adjustments_cents=bill.other_adjustments_cents,
                total_cents=bill.total_cents,
                shares=encode(bill.shares),
                reverses_id=bill.reverses_id,
                replaces_id=bill.replaces_id,
                edit_reason=bill.edit_reason,
                created_at=bill.created_at,
            )
        )

    def for_context(self, context: Context) -> tuple[Bill, ...]:
        c = t.bills.c
        rows = self._db.execute(
            select(t.bills)
            .where(_context_is(c.context_group_id, context))
            .order_by(c.created_at, c.seq)
        )
        return tuple(_bill(r) for r in rows)

    def for_participant(self, person_id: str) -> tuple[Bill, ...]:
        c = t.bills.c
        rows = self._db.execute(
            select(t.bills)
            .where(c.participants.contains([person_id]))
            .order_by(c.created_at, c.seq)
        )
        return tuple(_bill(r) for r in rows)


def _settlement(row: Row[tuple[object, ...]]) -> Settlement:
    m = row._mapping
    return Settlement(
        m["id"],
        m["payment_id"],
        context_from(m["context_group_id"]),
        m["from_id"],
        m["to_id"],
        m["amount_cents"],
        SettlementKind(m["kind"]),
        m["recorded_by"],
        m["reverses_id"],
        m["created_at"],
    )


class SettlementStore(Store):
    def add(self, settlement: Settlement) -> None:
        self._db.execute(
            insert(t.settlements).values(
                id=settlement.id,
                payment_id=settlement.payment_id,
                context_group_id=context_group_id(settlement.context),
                from_id=settlement.from_id,
                to_id=settlement.to_id,
                amount_cents=settlement.amount_cents,
                kind=settlement.kind.value,
                recorded_by=settlement.recorded_by,
                reverses_id=settlement.reverses_id,
                created_at=settlement.created_at,
            )
        )

    def for_context(self, context: Context) -> tuple[Settlement, ...]:
        c = t.settlements.c
        rows = self._db.execute(
            select(t.settlements)
            .where(_context_is(c.context_group_id, context))
            .order_by(c.created_at, c.seq)
        )
        return tuple(_settlement(r) for r in rows)

    def for_payment(self, payment_id: str) -> tuple[Settlement, ...]:
        c = t.settlements.c
        rows = self._db.execute(
            select(t.settlements).where(c.payment_id == payment_id).order_by(c.seq)
        )
        return tuple(_settlement(r) for r in rows)


def _notification(row: Row[tuple[object, ...]]) -> Notification:
    m = row._mapping
    return Notification(
        m["id"],
        m["recipient_id"],
        m["actor_id"],
        NotificationKind(m["kind"]),
        tuple(m["bill_ids"]),
        m["payment_id"],
        decode(m["text_args"], NotificationArgs),
        m["created_at"],
        m["sent_at"],
    )


CLAIM_LOCK_ID = 0x534D53_434C41494D
"""Advisory-lock id that serializes notification claims ("SMS" "CLAIM" in hex)."""


class NotificationStore(Store):
    def add(self, notification: Notification) -> None:
        self._db.execute(
            insert(t.notifications).values(
                id=notification.id,
                recipient_id=notification.recipient_id,
                actor_id=notification.actor_id,
                kind=notification.kind.value,
                bill_ids=list(notification.bill_ids),
                payment_id=notification.payment_id,
                text_args=encode(notification.text_args),
                created_at=notification.created_at,
                sent_at=notification.sent_at,
            )
        )

    def claim_due(
        self, now: datetime, limit: int, per_person_daily_cap: int, day_start: datetime
    ) -> tuple[Notification, ...]:
        """Claims run one at a time (a transaction-level advisory lock), so two ticks can't both
        count the same "sent today" and push a person past the cap. Held and capped recipients
        are filtered in SQL, so a backlog of held rows is never locked or scanned in Python."""
        self._db.execute(select(func.pg_advisory_xact_lock(CLAIM_LOCK_ID)))
        n, p = t.notifications.c, t.people.c
        reply = NotificationKind.REQUESTED_REPLY.value
        sent_today: dict[str, int] = dict(
            self._db.execute(
                select(n.recipient_id, func.count())
                .where(n.sent_at >= day_start, n.kind != reply)
                .group_by(n.recipient_id)
            ).all()
        )
        capped = [person for person, count in sent_today.items() if count >= per_person_daily_cap]
        deliverable = or_(
            n.kind == reply,
            and_(p.has_used_bot, p.notifications_enabled, n.recipient_id.not_in(capped)),
        )
        rows = self._db.execute(
            select(t.notifications)
            .join(t.people, p.id == n.recipient_id)
            .where(n.sent_at.is_(None), deliverable)
            .order_by(n.created_at, n.seq)
            .limit(limit)
            .with_for_update(of=t.notifications, skip_locked=True)
        ).all()
        claimed: list[Notification] = []
        for row in rows:
            notification = _notification(row)
            if notification.kind is not NotificationKind.REQUESTED_REPLY:
                count = sent_today.get(notification.recipient_id, 0)
                if count >= per_person_daily_cap:
                    continue
                sent_today[notification.recipient_id] = count + 1
            claimed.append(notification)
        if claimed:
            self._db.execute(
                update(t.notifications).where(n.id.in_([c.id for c in claimed])).values(sent_at=now)
            )
        return tuple(replace(c, sent_at=now) for c in claimed)
