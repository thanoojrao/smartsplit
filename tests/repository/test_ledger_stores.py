"""Bills, settlements and the notification outbox."""

from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import Engine

from smartsplit.adapters.db.repository import SqlRepository
from smartsplit.domain.enums import NotificationKind
from smartsplit.domain.prompts import Notification
from smartsplit.domain.values import GroupContext, PersonalContext
from smartsplit.ports.repository import Repository
from tests.repository.builders import at, bill, notification, person, settlement

FLAT, GOA = GroupContext("g1"), GroupContext("g2")


def test_bills_by_context_and_participant(repo: Repository) -> None:
    with repo.unit_of_work() as uow:
        uow.bills.add(bill("b2", FLAT, minutes=2))
        uow.bills.add(bill("b1", FLAT, minutes=1))
        uow.bills.add(bill("b3", GOA, minutes=3, participants=("sam", "priya")))
        uow.bills.add(replace(bill("b4", PersonalContext(), minutes=4), reverses_id="b3"))

    with repo.unit_of_work() as uow:
        assert uow.bills.get("b1") == bill("b1", FLAT, minutes=1)
        assert [b.id for b in uow.bills.for_context(FLAT)] == ["b1", "b2"]
        assert [b.id for b in uow.bills.for_context(PersonalContext())] == ["b4"]
        assert [b.id for b in uow.bills.for_participant("raj")] == ["b1", "b2", "b4"]
        assert [b.id for b in uow.bills.for_participant("priya")] == ["b3"]
        assert uow.bills.get("nope") is None


def test_settlements_by_context_and_payment(repo: Repository) -> None:
    with repo.unit_of_work() as uow:
        uow.settlements.add(settlement("s2", FLAT, minutes=2))
        uow.settlements.add(settlement("s1", GOA, minutes=1))
        uow.settlements.add(settlement("s3", PersonalContext(), payment="p2", minutes=3))

    with repo.unit_of_work() as uow:
        assert uow.settlements.for_context(FLAT) == (settlement("s2", FLAT, minutes=2),)
        assert [s.id for s in uow.settlements.for_context(PersonalContext())] == ["s3"]
        assert {s.id for s in uow.settlements.for_payment("p1")} == {"s1", "s2"}


def _setup_people(repo: Repository) -> None:
    with repo.unit_of_work() as uow:
        uow.people.add(person("raj"))
        uow.people.add(person("new", used_bot=False))
        uow.people.add(person("quiet", notify=False))


def _claim(repo: Repository, minutes: int, cap: int = 5, limit: int = 100) -> list[str]:
    with repo.unit_of_work() as uow:
        claimed = uow.notifications.claim_due(at(minutes), limit, cap, day_start=at(0))
    return [n.id for n in claimed]


def test_claim_marks_due_notifications_sent_oldest_first(repo: Repository) -> None:
    _setup_people(repo)
    with repo.unit_of_work() as uow:
        uow.notifications.add(notification("n2", "raj", minutes=2))
        uow.notifications.add(notification("n1", "raj", minutes=1))

    with repo.unit_of_work() as uow:
        claimed = uow.notifications.claim_due(at(10), 100, 5, day_start=at(0))
    assert [n.id for n in claimed] == ["n1", "n2"]
    assert all(n.sent_at == at(10) for n in claimed)
    assert _claim(repo, 11) == []


def test_claim_holds_non_users_and_opted_out_except_requested_replies(repo: Repository) -> None:
    _setup_people(repo)
    with repo.unit_of_work() as uow:
        uow.notifications.add(notification("held1", "new", minutes=1))
        uow.notifications.add(notification("held2", "quiet", minutes=2))
        uow.notifications.add(
            notification("reply", "quiet", kind=NotificationKind.REQUESTED_REPLY, minutes=3)
        )
        uow.notifications.add(
            notification("reply2", "new", kind=NotificationKind.REQUESTED_REPLY, minutes=4)
        )

    assert _claim(repo, 10) == ["reply", "reply2"]

    with repo.unit_of_work() as uow:
        new = uow.people.get("new")
        assert new is not None
        uow.people.update(replace(new, has_used_bot=True))
    assert _claim(repo, 11) == ["held1"]


def test_claim_respects_the_daily_cap_and_the_limit(repo: Repository) -> None:
    _setup_people(repo)
    with repo.unit_of_work() as uow:
        uow.notifications.add(notification("old", "raj", minutes=-60, sent_at=at(-30)))
        uow.notifications.add(notification("today", "raj", minutes=0, sent_at=at(1)))
        uow.notifications.add(
            notification(
                "reply", "raj", kind=NotificationKind.REQUESTED_REPLY, minutes=0, sent_at=at(1)
            )
        )
        for n in range(4):
            uow.notifications.add(notification(f"n{n}", "raj", minutes=2 + n))

    # Cap 3: one counted send today ("old" was before day_start, the reply doesn't count).
    assert _claim(repo, 10, cap=3, limit=1) == ["n0"]
    assert _claim(repo, 11, cap=3) == ["n1"]
    assert _claim(repo, 12, cap=10) == ["n2", "n3"]


def test_claimed_notifications_keep_their_fields(repo: Repository) -> None:
    _setup_people(repo)
    original: Notification = replace(notification("n1", "raj"), payment_id="p1")
    with repo.unit_of_work() as uow:
        uow.notifications.add(original)

    with repo.unit_of_work() as uow:
        (claimed,) = uow.notifications.claim_due(at(5), 10, 5, day_start=at(5) - timedelta(days=1))
    assert claimed == replace(original, sent_at=at(5))


def test_a_capped_backlog_does_not_starve_other_people(repo: Repository) -> None:
    _setup_people(repo)
    with repo.unit_of_work() as uow:
        uow.people.add(person("priya"))
        uow.notifications.add(notification("sent", "raj", minutes=0, sent_at=at(1)))
        for n in range(3):
            uow.notifications.add(notification(f"raj{n}", "raj", minutes=2 + n))
        uow.notifications.add(notification("priya", "priya", minutes=9))

    assert _claim(repo, 10, cap=1, limit=2) == ["priya"]


@pytest.mark.db
def test_concurrent_claims_skip_each_others_rows(clean_pg: Engine) -> None:
    repo = SqlRepository(clean_pg)
    _setup_people(repo)
    with repo.unit_of_work() as uow:
        for n in range(4):
            uow.notifications.add(notification(f"n{n}", "raj", minutes=n))

    with repo.unit_of_work() as first:
        first_ids = [n.id for n in first.notifications.claim_due(at(10), 2, 10, at(0))]
        with repo.unit_of_work() as second:
            second_ids = [n.id for n in second.notifications.claim_due(at(10), 10, 10, at(0))]

    assert first_ids == ["n0", "n1"]
    assert second_ids == ["n2", "n3"]
    assert _claim(repo, 11) == []
