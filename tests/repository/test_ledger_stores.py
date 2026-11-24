"""Bills, settlements and the notification outbox."""

import threading
from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import Engine

from smartsplit.adapters.db.repository import SqlRepository
from smartsplit.domain.enums import NotificationKind
from smartsplit.domain.prompts import Notification
from smartsplit.domain.values import GroupContext, PersonalContext
from smartsplit.ports.errors import MissingReferenceError
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


def test_claim_holds_non_users_and_the_opted_out(repo: Repository) -> None:
    _setup_people(repo)
    with repo.unit_of_work() as uow:
        uow.notifications.add(notification("held1", "new", minutes=1))
        uow.notifications.add(notification("held2", "quiet", minutes=2))

    assert _claim(repo, 10) == []

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
        for n in range(4):
            uow.notifications.add(notification(f"n{n}", "raj", minutes=2 + n))

    # Cap 3: one send today ("old" was before day_start).
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


def test_a_notification_sent_exactly_at_day_start_counts_toward_the_cap(repo: Repository) -> None:
    _setup_people(repo)
    with repo.unit_of_work() as uow:
        uow.notifications.add(notification("edge", "raj", minutes=-5, sent_at=at(0)))
        uow.notifications.add(notification("n1", "raj", minutes=1))

    assert _claim(repo, 10, cap=1) == []


def test_a_notification_needs_its_recipient(repo: Repository) -> None:
    with pytest.raises(MissingReferenceError), repo.unit_of_work() as uow:
        uow.notifications.add(notification("n1", "ghost"))


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
def test_overlapping_claims_respect_the_daily_cap(clean_pg: Engine) -> None:
    # Checkpoint A must-fix: one recipient, 6 unsent, cap 2, two overlapping claims → 2 in total.
    repo = SqlRepository(clean_pg)
    _setup_people(repo)
    with repo.unit_of_work() as uow:
        for n in range(6):
            uow.notifications.add(notification(f"n{n}", "raj", minutes=n))
    second: list[str] = []

    def claim_again() -> None:
        with repo.unit_of_work() as uow:
            second.extend(n.id for n in uow.notifications.claim_due(at(10), 10, 2, at(0)))

    with repo.unit_of_work() as uow:
        first = [n.id for n in uow.notifications.claim_due(at(10), 2, 2, at(0))]
        worker = threading.Thread(target=claim_again)
        worker.start()
        worker.join(timeout=0.5)
        assert worker.is_alive()  # waiting for the first claim to commit
    worker.join()

    assert first == ["n0", "n1"]
    assert second == []


def test_settlements_of_a_person_in_every_context(repo: Repository) -> None:
    with repo.unit_of_work() as uow:
        uow.settlements.add(settlement("s2", FLAT, minutes=2))
        uow.settlements.add(settlement("s1", GOA, minutes=1))
        uow.settlements.add(
            replace(settlement("s3", PersonalContext(), minutes=3), from_id="sam", to_id="priya")
        )

    with repo.unit_of_work() as uow:
        assert [s.id for s in uow.settlements.for_person("raj")] == ["s1", "s2"]
        assert [s.id for s in uow.settlements.for_person("sam")] == ["s1", "s2", "s3"]
        assert uow.settlements.for_person("nobody") == ()


def test_whether_a_notification_was_caused_since(repo: Repository) -> None:
    _setup_people(repo)
    reminder = NotificationKind.REMINDER
    with repo.unit_of_work() as uow:
        uow.notifications.add(notification("n1", "raj", kind=reminder, minutes=10))

    with repo.unit_of_work() as uow:
        assert uow.notifications.exists_since("sam", "raj", reminder, at(10))
        assert not uow.notifications.exists_since("sam", "raj", reminder, at(11))
        assert not uow.notifications.exists_since("raj", "raj", reminder, at(0))
        assert not uow.notifications.exists_since("sam", "raj", NotificationKind.BILL_ADDED, at(0))


def test_what_is_held_for_someone_who_hasnt_used_the_bot(repo: Repository) -> None:
    # SPEC 10.3: their first message can mention it
    _setup_people(repo)
    with repo.unit_of_work() as uow:
        uow.notifications.add(notification("n2", "new", minutes=2))
        uow.notifications.add(notification("n1", "new", minutes=1))
        uow.notifications.add(notification("other", "raj", minutes=1))
    _claim(repo, 5)
    with repo.unit_of_work() as uow:
        assert [n.id for n in uow.notifications.unsent_for("new")] == ["n1", "n2"]
        assert uow.notifications.unsent_for("raj") == ()
