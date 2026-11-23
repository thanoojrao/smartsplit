"""Small builders for repository tests: valid records with overridable fields."""

import zlib
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy.exc import IntegrityError

from smartsplit.domain.enums import (
    DraftState,
    MatchHow,
    NotificationKind,
    PromptKind,
    PromptStatus,
    QuestionReason,
    RuleKind,
    RuleSource,
    SettlementKind,
)
from smartsplit.domain.model import (
    Bill,
    BillDraft,
    BillLine,
    LineItem,
    Person,
    Rule,
    Settlement,
)
from smartsplit.domain.prompts import (
    EngineQuestionPayload,
    Notification,
    NotificationArgs,
    Prompt,
)
from smartsplit.domain.values import (
    Context,
    ConversationKey,
    EqualSplit,
    GroupContext,
    RuleScope,
    Share,
    Weight,
    Weighted,
)

DUPLICATE = (ValueError, IntegrityError)
"""Adding a duplicate key: the fake raises ValueError, Postgres an IntegrityError."""

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
CHAT = ConversationKey("cli", "flat-4b")


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def person(
    person_id: str, phone: str | None = None, *, used_bot: bool = True, notify: bool = True
) -> Person:
    number = phone or f"+9198765{zlib.crc32(person_id.encode()) % 100000:05}"
    return Person(person_id, person_id.title(), number, None, notify, used_bot, T0)


def line(line_id: str, cents: int, position: int = 1, **changes: Any) -> LineItem:
    base = LineItem(
        id=line_id,
        position=position,
        name=f"Line {line_id}",
        quantity=1,
        amount_cents=cents,
        taxed=None,
        confidence=0.95,
        canonical=None,
        discount_for=None,
        match_how=MatchHow.EXACT,
        match_is_new=False,
    )
    return replace(base, **changes)


def draft(
    draft_id: str, *, state: DraftState = DraftState.REVIEWING, minutes: int = 0
) -> BillDraft:
    return BillDraft(
        id=draft_id,
        conversation=CHAT,
        context=GroupContext("g1"),
        added_by="sam",
        payer_id="sam",
        receipt_id=None,
        image_ref="img.jpg",
        image_mime_type="image/jpeg",
        description="Groceries",
        purchased_at=date(2026, 11, 1),
        lines=(
            line("l1", 600, taxed=True, canonical="milk"),
            line("l2", -100, 2, discount_for="l1"),
        ),
        tax_cents=30,
        other_adjustments_cents=-5,
        total_cents=525,
        accepted_difference_cents=0,
        participants=("sam", "raj"),
        overrides=(
            ("l1", Weighted((Weight("sam", 2), Weight("raj", 1)))),
            ("l2", EqualSplit(("sam",))),
        ),
        owes_all_id=None,
        state=state,
        created_at=at(minutes),
        last_activity_at=at(minutes),
        reminded_at=None,
    )


def rule(
    rule_id: str,
    scope: RuleScope,
    *,
    subject: str = "raj",
    key: str = "milk",
    kind: RuleKind = RuleKind.EXCLUDE,
    minutes: int = 0,
) -> Rule:
    return Rule(rule_id, subject, key, kind, scope, "sam", RuleSource.STATED, at(minutes))


def bill(
    bill_id: str,
    context: Context,
    *,
    minutes: int = 0,
    participants: tuple[str, ...] = ("sam", "raj"),
) -> Bill:
    return Bill(
        id=bill_id,
        context=context,
        origin=CHAT,
        receipt_id=None,
        payer_id="sam",
        added_by="sam",
        description="Dinner",
        purchased_at=date(2026, 11, 1),
        participants=participants,
        lines=(
            BillLine(
                "bl1",
                1,
                "Pizza",
                "pizza",
                2,
                1000,
                True,
                None,
                (Weight("sam", 1), Weight("raj", 1)),
            ),
        ),
        tax_cents=0,
        other_adjustments_cents=0,
        total_cents=1000,
        shares=(Share("sam", 500), Share("raj", 500)),
        reverses_id=None,
        replaces_id=None,
        edit_reason=None,
        created_at=at(minutes),
    )


def settlement(
    settlement_id: str, context: Context, *, payment: str = "p1", minutes: int = 0
) -> Settlement:
    return Settlement(
        settlement_id,
        payment,
        context,
        "raj",
        "sam",
        500,
        SettlementKind.PAYMENT,
        "raj",
        None,
        at(minutes),
    )


def prompt(
    prompt_id: str,
    *,
    status: PromptStatus = PromptStatus.OPEN,
    minutes: int = 0,
    draft_id: str | None = "d1",
) -> Prompt:
    return Prompt(
        id=prompt_id,
        conversation=CHAT,
        draft_id=draft_id,
        kind=PromptKind.ENGINE_QUESTION,
        payload=EngineQuestionPayload("l1", "raj", QuestionReason.SOFT_RULE),
        status=status,
        asked_of=None,
        created_by="sam",
        created_at=at(minutes),
        answers=(),
    )


def notification(
    notification_id: str,
    recipient: str,
    *,
    kind: NotificationKind = NotificationKind.BILL_ADDED,
    minutes: int = 0,
    sent_at: datetime | None = None,
) -> Notification:
    return Notification(
        notification_id,
        recipient,
        "sam",
        kind,
        ("b1",),
        None,
        NotificationArgs(),
        at(minutes),
        sent_at,
    )
