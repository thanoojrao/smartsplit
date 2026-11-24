"""Photo reads, the chat transcript, usage counted on its own, and savepoints, on both
backends (SPEC 7, 8.6, 12.5; CONTRACTS 4)."""

from dataclasses import replace
from datetime import date

import pytest

from smartsplit.domain.enums import PhotoOutcome
from smartsplit.domain.messages import OutboundMessage
from smartsplit.domain.model import PhotoRead
from smartsplit.domain.prompts import ChatMessage, ChatRef, TickBatch
from smartsplit.domain.values import ConversationKey
from smartsplit.ports.errors import DuplicateKeyError
from smartsplit.ports.repository import Repository
from tests.repository.builders import CHAT, at

OTHER = ConversationKey("cli", "other")
DAY = date(2026, 11, 1)


def photo(
    message_id: str,
    minutes: int,
    *,
    sender: str = "sam",
    outcome: PhotoOutcome = PhotoOutcome.RECEIPT,
    used_by: str | None = None,
    chat: ConversationKey = CHAT,
) -> PhotoRead:
    receipt = "r1" if outcome is PhotoOutcome.RECEIPT else None
    return PhotoRead(chat, message_id, sender, outcome, receipt, used_by, at(minutes))


def test_photo_reads_are_stored_once_per_message(repo: Repository) -> None:
    with repo.unit_of_work() as uow:
        uow.photos.add(photo("m1", 0))
    with pytest.raises(DuplicateKeyError), repo.unit_of_work() as uow:
        uow.photos.add(photo("m1", 1))
    with repo.unit_of_work() as uow:
        assert uow.photos.get(CHAT, "m1") == photo("m1", 0)
        assert uow.photos.get(CHAT, "m2") is None


def test_the_latest_unused_receipt_photo_of_a_sender(repo: Repository) -> None:
    # SPEC 10.4: a photo sent on its own is picked up by the sender's next message
    with repo.unit_of_work() as uow:
        uow.photos.add(photo("old", 0))
        uow.photos.add(photo("newer", 5))
        uow.photos.add(photo("used", 6, used_by="d1"))
        uow.photos.add(photo("meme", 7, outcome=PhotoOutcome.NOT_A_RECEIPT))
        uow.photos.add(photo("raj", 8, sender="raj"))
        uow.photos.add(photo("elsewhere", 9, chat=OTHER))
    with repo.unit_of_work() as uow:
        assert uow.photos.latest_unused(CHAT, "sam", at(1)) == photo("newer", 5)
        assert uow.photos.latest_unused(CHAT, "sam", at(6)) is None
        uow.photos.update(replace(photo("newer", 5), used_by_draft_id="d2"))
    with repo.unit_of_work() as uow:
        assert uow.photos.latest_unused(CHAT, "sam", at(0)) == photo("old", 0)


def message(text: str, minutes: int, key: ConversationKey = CHAT) -> ChatMessage:
    return ChatMessage(key, 0, None, text, (ChatRef("draft", "d1", 3),), at(minutes))


def test_the_transcript_is_ordered_by_one_sequence(repo: Repository) -> None:
    with repo.unit_of_work() as uow:
        first = uow.chat.append(message("one", 0))
        other = uow.chat.append(message("elsewhere", 0, OTHER))
        second = uow.chat.append(replace(message("two", 0), sender_id="sam", refs=()))
    assert first.seq < other.seq < second.seq
    with repo.unit_of_work() as uow:
        assert uow.chat.recent(CHAT, 10) == (first, second)
        assert uow.chat.recent(CHAT, 1) == (second,)
        assert uow.chat.recent(CHAT, 0) == ()


def test_pruning_keeps_the_newest_and_age_limits_apply_to_every_chat(repo: Repository) -> None:
    # SPEC 8.6: at most N per chat; tick deletes messages older than the age limit
    with repo.unit_of_work() as uow:
        for n in range(5):
            uow.chat.append(message(f"m{n}", n))
        uow.chat.append(message("other", 0, OTHER))
        uow.chat.prune(CHAT, 3)
    with repo.unit_of_work() as uow:
        assert [m.text for m in uow.chat.recent(CHAT, 10)] == ["m2", "m3", "m4"]
        assert uow.chat.delete_older_than(at(3)) == 2
        assert [m.text for m in uow.chat.recent(CHAT, 10)] == ["m3", "m4"]
        assert uow.chat.recent(OTHER, 10) == ()
        uow.chat.prune(OTHER, 0)


def test_usage_counts_survive_a_rolled_back_unit_of_work(repo: Repository) -> None:
    # SPEC 12.5: failed turns count too
    with pytest.raises(RuntimeError), repo.unit_of_work():
        assert repo.count_usage("sam", DAY) == 1
        assert repo.count_usage("install", DAY) == 1
        raise RuntimeError("the turn failed")
    assert repo.count_usage("sam", DAY) == 2
    with repo.unit_of_work() as uow:
        usage = uow.llm_usage.get("sam", DAY)
        assert usage is not None and usage.calls == 2
        assert uow.llm_usage.get("install", DAY) is not None
        assert uow.llm_usage.get("raj", DAY) is None


def test_a_savepoint_undoes_only_its_own_writes(repo: Repository) -> None:
    with repo.unit_of_work() as uow:
        uow.chat.append(message("kept", 0))
        with pytest.raises(ValueError), uow.savepoint():
            uow.chat.append(message("undone", 1))
            raise ValueError("refused")
        with uow.savepoint():
            uow.chat.append(message("also kept", 2))
    with repo.unit_of_work() as uow:
        assert [m.text for m in uow.chat.recent(CHAT, 10)] == ["kept", "also kept"]


def batch(batch_id: str, minutes: int, *, acked: int | None = None) -> TickBatch:
    sent = (OutboundMessage(CHAT, None, f"hello from {batch_id}"),)
    return TickBatch(batch_id, sent, at(minutes), at(acked) if acked is not None else None)


def test_tick_batches_wait_for_their_ack(repo: Repository) -> None:
    # SPEC 10.8: an unacknowledged batch is returned again, same id
    with repo.unit_of_work() as uow:
        uow.tick_batches.add(batch("b1", 0))
        uow.tick_batches.add(batch("b2", 1))
        uow.tick_batches.add(batch("done", 2, acked=2))
    with repo.unit_of_work() as uow:
        assert uow.tick_batches.unacked_before(at(1)) == (batch("b1", 0),)
        assert uow.tick_batches.unacked_before(at(5)) == (batch("b1", 0), batch("b2", 1))
        assert uow.tick_batches.ack("b1", at(3))
        assert uow.tick_batches.ack("b1", at(4))  # a repeated ack is fine
        assert not uow.tick_batches.ack("nope", at(4))
    with repo.unit_of_work() as uow:
        assert uow.tick_batches.unacked_before(at(5)) == (batch("b2", 1),)
        uow.tick_batches.delete_acked_before(at(10))
    with repo.unit_of_work() as uow:
        assert not uow.tick_batches.ack("b1", at(11))
        assert not uow.tick_batches.ack("done", at(11))
        assert uow.tick_batches.unacked_before(at(10)) == (batch("b2", 1),)


def test_a_tick_batch_grows_as_each_step_commits(repo: Repository) -> None:
    # SPEC 10.8: what one step sent is in the batch even if a later step fails
    later = OutboundMessage(CHAT, "sam", "reminder")
    with repo.unit_of_work() as uow:
        uow.tick_batches.add(batch("b1", 0))
        uow.tick_batches.append("b1", [later])
        uow.tick_batches.append("b1", [])
    with pytest.raises(ValueError), repo.unit_of_work() as uow:
        uow.tick_batches.append("b1", [later])
        raise ValueError("the step failed")
    with repo.unit_of_work() as uow:
        stored = uow.tick_batches.get("b1")
        assert stored is not None
        assert stored.messages == (*batch("b1", 0).messages, later)
        assert uow.tick_batches.get("nope") is None
