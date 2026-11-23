"""Small bills and settlements for ledger tests."""

from datetime import UTC, date, datetime, timedelta

from smartsplit.domain.enums import SettlementKind
from smartsplit.domain.model import Bill, Settlement
from smartsplit.domain.values import Context, ConversationKey, GroupContext, PersonalContext, Share
from smartsplit.ledger import ContextLedger

T0 = datetime(2026, 11, 1, tzinfo=UTC)
FLAT, TRIP, PERSONAL = GroupContext("flat"), GroupContext("trip"), PersonalContext()
_counter = iter(range(1_000_000))


def bill(
    context: Context,
    payer: str,
    shares: dict[str, int],
    *,
    minutes: int = 0,
    reverses: str | None = None,
) -> Bill:
    return Bill(
        id=f"b{next(_counter)}",
        context=context,
        origin=ConversationKey("cli", "x"),
        receipt_id=None,
        payer_id=payer,
        added_by=payer,
        description="bill",
        purchased_at=date(2026, 11, 1),
        participants=tuple(shares),
        lines=(),
        tax_cents=0,
        other_adjustments_cents=0,
        total_cents=sum(shares.values()),
        shares=tuple(Share(p, c) for p, c in shares.items()),
        reverses_id=reverses,
        replaces_id=None,
        edit_reason=None,
        created_at=T0 + timedelta(minutes=minutes),
    )


def paid(context: Context, from_id: str, to_id: str, cents: int) -> Settlement:
    return Settlement(
        f"s{next(_counter)}",
        "p",
        context,
        from_id,
        to_id,
        cents,
        SettlementKind.PAYMENT,
        from_id,
        None,
        T0,
    )


def ledger(
    context: Context,
    order: tuple[str, ...],
    bills: list[Bill],
    settlements: list[Settlement] | None = None,
) -> ContextLedger:
    return ContextLedger(context, order, tuple(bills), tuple(settlements or ()))
