"""Whether a saved bill still counts, and the version a pending change to it was made at."""

from smartsplit.domain.model import Bill
from smartsplit.domain.values import PersonalContext
from smartsplit.ports.repository import UnitOfWork


def is_live(uow: UnitOfWork, bill: Bill) -> bool:
    """Neither a reversal nor reversed."""
    if bill.reverses_id is not None:
        return False
    return not any(b.reverses_id == bill.id for b in uow.bills.for_context(bill.context))


def bill_version(uow: UnitOfWork, bill_id: str) -> int:
    """Grows with every bill written among the same people: in the bill's group, or for a
    personal bill between exactly its participants, so other people's personal bills don't
    make a pending change stale."""
    bill = uow.bills.get(bill_id)
    if bill is None:
        return -1
    if not isinstance(bill.context, PersonalContext):
        return len(uow.bills.for_context(bill.context))
    people = frozenset(bill.participants)
    return sum(
        1
        for other in uow.bills.for_participant(bill.participants[0])
        if isinstance(other.context, PersonalContext) and frozenset(other.participants) == people
    )
