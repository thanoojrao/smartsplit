"""Adding, reviewing and saving bills in a group chat (use cases C1-C15, G1-G7)."""

from datetime import timedelta

from smartsplit.domain.enums import DraftState
from smartsplit.domain.messages import ImageAttachment
from tests.integration.world import FLAT, PRIYA, RAJ, SAM, YOU, World, flat, receipt


def drafts(world: World) -> list[DraftState]:
    with world.repository.unit_of_work() as uow:
        conversation = uow.conversations.get(world.message(YOU, FLAT).conversation)
        assert conversation is not None
        return [d.state for d in uow.drafts.for_conversation(conversation.key, list(DraftState))]


def test_receipt_photo_is_split_among_current_members_and_saved() -> None:
    # C1, C15: summary, adder confirms, balances posted in the group only
    world = World()
    flat(world, YOU, SAM, RAJ)
    summary = world.say(YOU, FLAT, image=receipt("restaurant_tip"))
    assert "Toit, ₹2,047.00, paid by Thanoo." in summary
    assert "Thanoo: ₹682.34" in summary and "Raj: ₹682.33" in summary
    saved = world.say(YOU, FLAT, "yes")
    assert "Saved: Toit, ₹2,047.00." in saved
    assert "Sam owes Thanoo ₹682.33" in saved
    assert {m.conversation.ref for m in world.last} == {FLAT}
    assert drafts(world) == [DraftState.SAVED]


def test_subset_and_payer_from_the_caption() -> None:
    # C2, C3
    world = World()
    flat(world, YOU, SAM, RAJ)
    summary = world.say(
        YOU, FLAT, "split with me and Sam, Sam paid", image=receipt("restaurant_tip")
    )
    assert "paid by Sam" in summary
    assert "Raj" not in summary


def test_manual_bill_split_equally() -> None:
    # C4
    world = World()
    flat(world, YOU, SAM, RAJ)
    summary = world.say(YOU, FLAT, "electricity 1800, split all")
    assert "electricity, ₹1,800.00" in summary
    assert "Sam: ₹600.00" in summary
    assert "Saved" in world.say(YOU, FLAT, "save")


def test_only_current_members_can_be_in_a_group_bill() -> None:
    # C2: Priya isn't in Flat 4B
    world = World()
    flat(world, YOU, SAM)
    world.say(YOU, None, "add Priya +919876500004")
    reply = world.say(YOU, FLAT, "split with me and Priya", image=receipt("restaurant_tip"))
    assert "Only current members" in reply
    assert drafts(world) == []


def test_total_mismatch_is_shown_and_can_be_accepted() -> None:
    # C5: lines 560 vs total 570, then "yes" shares the difference like a tip
    world = World()
    flat(world, YOU, SAM)
    summary = world.say(YOU, FLAT, image=receipt("total_mismatch"))
    assert "The lines add up to ₹560.00 but the total says ₹570.00" in summary
    asked = world.say(YOU, FLAT, "yes")
    assert "share the difference" in asked
    saved = world.say(YOU, FLAT, "yes")
    assert "Saved: Kirana, ₹570.00." in saved
    assert "Sam owes Thanoo ₹285.00" in saved


def test_fixing_the_total_instead() -> None:
    # C5, C6
    world = World()
    flat(world, YOU, SAM)
    world.say(YOU, FLAT, image=receipt("total_mismatch"))
    fixed = world.say(YOU, FLAT, "total is 560")
    assert "add up to" not in fixed
    assert "Saved" in world.say(YOU, FLAT, "yes")


def test_review_edits_recompute_the_split() -> None:
    # C6, G6
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.say(YOU, FLAT, image=receipt("total_mismatch"))
    fixed = world.say(YOU, FLAT, "line 2 is 150")
    assert "Thanoo: ₹190.00" in fixed
    assert "Couldn't read" not in fixed
    assert "Amounts must be more than 0" in world.say(YOU, FLAT, "add water 0")
    after_add = world.say(YOU, FLAT, "add water 30")
    assert "Kirana, ₹600.00" in after_add
    after_remove = world.say(YOU, FLAT, "remove water")
    assert "Kirana, ₹570.00" in after_remove
    details = world.say(YOU, FLAT, "details")
    assert "1. Rice 5kg ₹420.00: Thanoo, Sam and Raj" in details
    without_raj = world.say(YOU, FLAT, "Raj had none of the rice")
    assert "Raj: ₹50.00" in without_raj
    weighted = world.say(YOU, FLAT, "2 for Sam, 1 for Raj on line 1")
    assert "Sam: ₹330.00" in weighted


def test_unclear_line_is_flagged() -> None:
    # C7: Dal was read with confidence 0.4
    world = World()
    flat(world, YOU, SAM)
    summary = world.say(YOU, FLAT, image=receipt("total_mismatch"))
    assert "Couldn't read line 2 clearly: Dal 1kg ₹140.00?" in summary


def test_unreadable_receipt() -> None:
    # C9
    world = World()
    flat(world, YOU, SAM)
    reply = world.say(YOU, FLAT, image=ImageAttachment("image/jpeg", b"\xff\xd8 blurry"))
    assert reply == "Couldn't read that receipt, try another photo."
    assert drafts(world) == [DraftState.CANCELLED]


def test_second_receipt_waits_for_the_first() -> None:
    # C10: queued, read only when it starts
    world = World()
    flat(world, YOU, SAM)
    world.say(YOU, FLAT, image=receipt("restaurant_tip"))
    reads = world.parser.calls
    queued = world.say(SAM, FLAT, image=receipt("total_mismatch"))
    assert queued == "I'll do this one after we finish the Toit bill."
    assert world.parser.calls == reads
    saved = world.say(YOU, FLAT, "yes")
    assert "Saved: Toit" in saved
    assert "Kirana, ₹560.00, paid by Sam." in saved
    assert world.parser.calls == reads + 1


def test_only_a_few_receipts_can_wait() -> None:
    world = World()
    flat(world, YOU, SAM)
    world.say(YOU, FLAT, image=receipt("restaurant_tip"))
    for _ in range(world.settings.max_queued_drafts):
        world.say(SAM, FLAT, image=receipt("total_mismatch"))
    assert "already a few receipts waiting" in world.say(SAM, FLAT, image=receipt("usd_receipt"))


def test_same_receipt_twice_is_flagged() -> None:
    # C11
    world = World()
    flat(world, YOU, SAM)
    world.say(SAM, FLAT, image=receipt("restaurant_tip"))
    world.say(SAM, FLAT, "yes")
    again = world.say(YOU, FLAT, image=receipt("restaurant_tip"))
    assert "Looks like Sam already added this (₹2,047.00)" in again
    dropped = world.say(YOU, FLAT, "no")
    assert "dropped the Toit bill" in dropped
    assert drafts(world)[-1] is DraftState.CANCELLED


def test_duplicate_kept_on_yes() -> None:
    world = World()
    flat(world, YOU, SAM)
    world.say(SAM, FLAT, image=receipt("restaurant_tip"))
    world.say(SAM, FLAT, "yes")
    world.say(YOU, FLAT, image=receipt("restaurant_tip"))
    shown = world.say(YOU, FLAT, "yes")
    assert "Toit, ₹2,047.00, paid by Thanoo." in shown
    assert "Saved" in world.say(YOU, FLAT, "yes")


def test_any_member_can_cancel_and_the_bot_says_who() -> None:
    # C12
    world = World()
    flat(world, YOU, SAM)
    world.say(YOU, FLAT, image=receipt("restaurant_tip"))
    assert world.say(SAM, FLAT, "cancel") == "Sam cancelled the Toit bill. Nothing was saved."
    assert drafts(world) == [DraftState.CANCELLED]


def test_up_to_three_questions_then_the_next_batch() -> None:
    # G1, G2
    world = World()
    flat(world, YOU, SAM, RAJ, PRIYA)
    for person in (SAM, RAJ, PRIYA, YOU):
        world.say(person, FLAT, "I usually don't drink beer pitcher")
    summary = world.say(YOU, FLAT, image=receipt("restaurant_tip"))
    assert "1) Does" in summary and "3) Does" in summary and "4)" not in summary
    after = world.say(SAM, FLAT, "1 no")
    assert "1) Does" not in after and "2) Does" in after and "3) Does" in after
    world.say(SAM, FLAT, "2 yes")
    next_batch = world.say(RAJ, FLAT, "3 yes")
    assert "1) Does Priya share the Beer Pitcher" in next_batch
    assert "2)" not in next_batch
    last = world.say(PRIYA, FLAT, "1 no")
    assert "Does" not in last
    assert "Priya: ₹" in last


def test_latest_answer_wins() -> None:
    # G3
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.say(SAM, FLAT, "I usually don't drink beer pitcher")
    world.say(RAJ, FLAT, "I usually don't drink beer pitcher")
    world.say(YOU, FLAT, image=receipt("restaurant_tip"))
    world.say(SAM, FLAT, "1 no")  # the batch is still open: question 2 has no answer yet
    world.say(RAJ, FLAT, "1: Sam and Raj")
    shown = world.say(YOU, FLAT, "details")
    assert "Beer Pitcher ₹950.00: Sam and Raj" in shown


def test_adder_can_save_with_questions_open_and_only_the_adder() -> None:
    # G4, G5
    world = World()
    flat(world, YOU, SAM)
    world.say(SAM, FLAT, "I usually don't drink beer pitcher")
    summary = world.say(YOU, FLAT, image=receipt("restaurant_tip"))
    assert "Does Sam share the Beer Pitcher" in summary
    assert world.say(SAM, FLAT, "yes") == "Only Thanoo can save this bill."
    assert "Saved" in world.say(YOU, FLAT, "yes")


def test_review_resumes_after_a_restart() -> None:
    # G7: a new orchestrator on the same database picks up the open question
    world = World()
    flat(world, YOU, SAM)
    world.say(SAM, FLAT, "I usually don't drink beer pitcher")
    world.say(YOU, FLAT, image=receipt("restaurant_tip"))
    restarted = World(clock=world.clock, repository=world.repository)
    answered = restarted.say(SAM, FLAT, "1 no")
    assert "Sam: ₹" in answered and "Does Sam" not in answered
    assert "Saved" in restarted.say(YOU, FLAT, "yes")


def test_bill_learns_from_answers() -> None:
    # F5 through the chat: two bills where Sam is taken off chips → no more question
    world = World()
    flat(world, YOU, SAM)
    world.say(SAM, FLAT, "I usually don't eat chips")
    for _ in range(2):
        world.say(YOU, FLAT, "chips 100, split all")
        world.say(YOU, FLAT, "1 no")
        world.say(YOU, FLAT, "yes")
        world.clock.advance(timedelta(hours=1))
    summary = world.say(YOU, FLAT, "chips 100, split all")
    assert "Does Sam" not in summary
    assert "Sam skipped: chips" in summary
