"""Receipts, drafts, prompts and processed messages."""

from dataclasses import replace
from datetime import date

import pytest
from sqlalchemy import Engine

from smartsplit.adapters.db.repository import SqlRepository
from smartsplit.domain.commands import AnswerPrompt, Edit, StartSplit
from smartsplit.domain.edits import AssignLine
from smartsplit.domain.enums import DraftState, PromptKind, PromptStatus, RuleKind
from smartsplit.domain.messages import OutboundMessage
from smartsplit.domain.model import Receipt
from smartsplit.domain.prompts import (
    ConfirmActionPayload,
    ProcessedMessage,
    PromptAnswer,
    RuleChangeEffect,
    WhichPersonPayload,
)
from smartsplit.domain.values import (
    ConversationKey,
    ExactAmount,
    GroupContext,
    GroupScope,
    PersonalContext,
)
from smartsplit.ports.errors import DuplicateKeyError, StaleDraftError
from smartsplit.ports.repository import Repository
from tests.repository.builders import CHAT, T0, at, draft, line, prompt, rule

OTHER = ConversationKey("cli", "other")
THIRD = ConversationKey("cli", "third")


def test_receipts_round_trip(repo: Repository) -> None:
    receipt = Receipt(
        "r1",
        "img.jpg",
        "image/jpeg",
        "Toit",
        date(2026, 11, 1),
        (line("l1", 1200, taxed=False), line("l2", -200, 2, discount_for="l1", confidence=0.4)),
        100,
        50,
        1150,
        ("total doesn't match",),
    )
    with repo.unit_of_work() as uow:
        uow.receipts.add(receipt)

    with repo.unit_of_work() as uow:
        assert uow.receipts.get("r1") == receipt
        assert uow.receipts.get("r2") is None


def test_drafts_round_trip_and_update(repo: Repository) -> None:
    with repo.unit_of_work() as uow:
        uow.drafts.add(draft("d1"))
        uow.drafts.add(
            replace(draft("d2", chat=OTHER), context=PersonalContext(), purchased_at=None)
        )
        uow.drafts.update(
            replace(draft("d1"), state=DraftState.SAVED, reminded_at=at(5)),
            expected_state=DraftState.REVIEWING,
        )

    with repo.unit_of_work() as uow:
        assert uow.drafts.get("d1") == replace(
            draft("d1"), state=DraftState.SAVED, reminded_at=at(5)
        )
        assert uow.drafts.get("d2") == replace(
            draft("d2", chat=OTHER), context=PersonalContext(), purchased_at=None
        )


def test_updating_a_missing_draft_raises(repo: Repository) -> None:
    with pytest.raises(KeyError), repo.unit_of_work() as uow:
        uow.drafts.update(draft("nope"), expected_state=DraftState.REVIEWING)


def test_a_draft_update_fails_if_its_state_changed_meanwhile(repo: Repository) -> None:
    # SPEC 12.2: e.g. tick expired the draft while a "yes" was being handled.
    with repo.unit_of_work() as uow:
        uow.drafts.add(draft("d1", state=DraftState.EXPIRED))

    with pytest.raises(StaleDraftError), repo.unit_of_work() as uow:
        uow.drafts.update(
            replace(draft("d1"), state=DraftState.SAVED), expected_state=DraftState.REVIEWING
        )

    with repo.unit_of_work() as uow:
        stored = uow.drafts.get("d1")
        assert stored is not None
        assert stored.state is DraftState.EXPIRED


def test_drafts_for_a_conversation_by_state(repo: Repository) -> None:
    with repo.unit_of_work() as uow:
        uow.drafts.add(draft("d2", state=DraftState.QUEUED, minutes=2))
        uow.drafts.add(draft("d1", minutes=1))
        uow.drafts.add(draft("d3", state=DraftState.QUEUED, minutes=3))
        uow.drafts.add(draft("d4", chat=OTHER))

    with repo.unit_of_work() as uow:
        queued = uow.drafts.for_conversation(CHAT, [DraftState.QUEUED])
        assert [d.id for d in queued] == ["d2", "d3"]
        both = uow.drafts.for_conversation(CHAT, [DraftState.QUEUED, DraftState.REVIEWING])
        assert [d.id for d in both] == ["d1", "d2", "d3"]


def test_a_chat_has_at_most_one_active_draft(repo: Repository) -> None:
    # SPEC 4.5: one draft per conversation is active; others wait as queued.
    with repo.unit_of_work() as uow:
        uow.drafts.add(draft("d1"))
        uow.drafts.add(draft("q1", state=DraftState.QUEUED, minutes=1))
        uow.drafts.add(draft("q2", state=DraftState.QUEUED, minutes=2))
        uow.drafts.add(draft("done", state=DraftState.SAVED))

    with pytest.raises(DuplicateKeyError), repo.unit_of_work() as uow:
        uow.drafts.add(draft("d2", state=DraftState.PARSING))
    with pytest.raises(DuplicateKeyError), repo.unit_of_work() as uow:
        uow.drafts.update(
            replace(draft("q1", minutes=1), state=DraftState.PARSING),
            expected_state=DraftState.QUEUED,
        )

    with repo.unit_of_work() as uow:
        uow.drafts.update(replace(draft("d1"), state=DraftState.SAVED), DraftState.REVIEWING)
        uow.drafts.update(
            replace(draft("q1", minutes=1), state=DraftState.PARSING), DraftState.QUEUED
        )


def test_drafts_due_for_reminder_or_expiry(repo: Repository) -> None:
    with repo.unit_of_work() as uow:
        uow.drafts.add(draft("idle", minutes=0))
        uow.drafts.add(draft("waiting", state=DraftState.AWAITING_PEOPLE, minutes=1, chat=OTHER))
        uow.drafts.add(draft("active", minutes=100, chat=ConversationKey("cli", "third")))
        uow.drafts.add(draft("queued", state=DraftState.QUEUED, minutes=0))
        uow.drafts.add(draft("done", state=DraftState.SAVED, minutes=0))

    with repo.unit_of_work() as uow:
        due = uow.drafts.due_for_reminder_or_expiry(idle_since=at(1))
        assert [d.id for d in due] == ["idle", "waiting"]


def test_prompts_with_typed_payloads_and_answers(repo: Repository) -> None:
    confirm = replace(
        prompt("p2", minutes=2),
        kind=PromptKind.CONFIRM_ACTION,
        payload=ConfirmActionPayload(
            Edit(AssignLine(2, exact=(ExactAmount("Sam", 100),)), reason="typo"),
            RuleChangeEffect(rule("r1", GroupScope("g1"), kind=RuleKind.ONLY), None),
            based_on_version=3,
        ),
        answers=(PromptAnswer("raj", AnswerPrompt(yes=True, people=("Sam",)), at(3)),),
    )
    which = replace(
        prompt("p3", minutes=3, draft_id=None),
        kind=PromptKind.WHICH_PERSON,
        payload=WhichPersonPayload("Sam", ("s1", "s2"), StartSplit(people=("Sam",))),
        asked_of="me",
    )
    with repo.unit_of_work() as uow:
        uow.prompts.add(prompt("p1", minutes=1))
        uow.prompts.add(confirm)
        uow.prompts.add(which)
        uow.prompts.update(replace(prompt("p1", minutes=1), status=PromptStatus.ANSWERED))

    with repo.unit_of_work() as uow:
        assert uow.prompts.get("p2") == confirm
        assert uow.prompts.get("p3") == which
        open_ones = uow.prompts.for_conversation(CHAT, [PromptStatus.OPEN])
        assert [p.id for p in open_ones] == ["p2", "p3"]
        assert [p.id for p in uow.prompts.for_draft("d1")] == ["p1", "p2"]
        assert uow.prompts.get("nope") is None


@pytest.mark.db
def test_a_draft_changed_by_another_connection_is_stale(clean_pg: Engine) -> None:
    repo = SqlRepository(clean_pg)
    with repo.unit_of_work() as uow:
        uow.drafts.add(draft("d1"))

    with pytest.raises(StaleDraftError), repo.unit_of_work() as handling_yes:
        seen = handling_yes.drafts.get("d1")
        assert seen is not None
        with repo.unit_of_work() as tick:
            tick.drafts.update(replace(seen, state=DraftState.EXPIRED), DraftState.REVIEWING)
        handling_yes.drafts.update(replace(seen, state=DraftState.SAVED), seen.state)


def test_a_message_is_processed_once(repo: Repository) -> None:
    with repo.unit_of_work() as uow:
        uow.processed.add(ProcessedMessage(CHAT, "m1", (), T0))

    with pytest.raises(DuplicateKeyError), repo.unit_of_work() as uow:
        uow.processed.add(ProcessedMessage(CHAT, "m1", (), T0))


def test_processed_messages_store_their_replies(repo: Repository) -> None:
    replies = (
        OutboundMessage(CHAT, None, "Saved. Raj owes ₹300."),
        OutboundMessage(ConversationKey("cli", "raj"), "raj", "Sam added Toit."),
    )
    with repo.unit_of_work() as uow:
        uow.processed.add(ProcessedMessage(CHAT, "m1", replies, T0))

    with repo.unit_of_work() as uow:
        assert uow.processed.get(CHAT, "m1") == ProcessedMessage(CHAT, "m1", replies, T0)
        assert uow.processed.get(CHAT, "m2") is None


def test_open_drafts_of_a_context_across_chats(repo: Repository) -> None:
    # A group draft can be under review in a personal chat (filed into the group).
    with repo.unit_of_work() as uow:
        uow.drafts.add(draft("d1", minutes=1))
        uow.drafts.add(draft("d2", chat=OTHER, minutes=2))
        uow.drafts.add(draft("d3", chat=OTHER, state=DraftState.QUEUED, minutes=3))
        uow.drafts.add(draft("d4", chat=THIRD, state=DraftState.SAVED, minutes=4))
        uow.drafts.add(replace(draft("d5", chat=THIRD, minutes=5), context=PersonalContext()))

    with repo.unit_of_work() as uow:
        assert [d.id for d in uow.drafts.open_in_context(GroupContext("g1"))] == ["d1", "d2", "d3"]
        assert [d.id for d in uow.drafts.open_in_context(PersonalContext())] == ["d5"]


def test_replies_can_be_added_to_a_processed_message(repo: Repository) -> None:
    first = OutboundMessage(CHAT, None, "Reading it.")
    later = OutboundMessage(CHAT, None, "Toit, ₹1,200.")
    with repo.unit_of_work() as uow:
        uow.processed.add(ProcessedMessage(CHAT, "m1", (first,), T0))
    with repo.unit_of_work() as uow:
        uow.processed.add_replies(CHAT, "m1", [later])

    with repo.unit_of_work() as uow:
        stored = uow.processed.get(CHAT, "m1")
        assert stored is not None
        assert stored.replies == (first, later)
    with pytest.raises(KeyError), repo.unit_of_work() as uow:
        uow.processed.add_replies(CHAT, "m2", [later])
