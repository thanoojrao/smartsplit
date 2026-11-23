"""Getting started, groups and membership (use cases A1-A13, B1-B5)."""

from dataclasses import replace
from datetime import timedelta

from smartsplit.domain.messages import ChatEvent, ContactAttachment
from tests.integration.world import (
    FLAT,
    PRIYA,
    RAJ,
    SAM,
    YOU,
    Someone,
    World,
    flat,
    receipt,
)


def members(world: World) -> list[str]:
    with world.repository.unit_of_work() as uow:
        group = uow.groups.by_channel_ref(world.message(YOU, FLAT).conversation)
        assert group is not None
        names = []
        for membership in uow.memberships.for_group(group.id):
            person = uow.people.get(membership.person_id)
            if membership.left_at is None and person is not None:
                names.append(person.display_name)
        return names


def test_first_personal_message_welcomes_with_help() -> None:
    # A1
    world = World()
    reply = world.say(YOU, None, "hi")
    assert reply.startswith("Hi Alex! I split bills.")
    assert "Waiting for you" not in reply
    assert (
        world.say(YOU, None, "hi") == 'Sorry, I didn\'t get that. Say "help" to see what I can do.'
    )


def test_first_message_shows_what_is_waiting() -> None:
    # A1: Sam added Raj to a personal split before Raj ever talked to the bot
    world = World()
    world.say(SAM, None, "help")
    world.say(SAM, None, "add Raj +919876500003")
    world.say(SAM, None, "pizza 600 with Raj")
    world.say(SAM, None, "yes")
    welcome = world.say(RAJ, None, "hi")
    assert "Waiting for you:\nYou owe Sam ₹300.00" in welcome


def test_new_group_chat_creates_the_group_and_asks_others_to_join() -> None:
    # A2, A3, A4
    world = World()
    hello = world.say(YOU, FLAT, "help")
    assert (
        'Hi Flat 4B! Alex is in. Everyone else who wants to split bills here, reply "join".'
        in hello
    )
    assert world.say(SAM, FLAT, "balances") == 'Sam, join splits here? Say "join".'
    assert world.say(SAM, FLAT, "join") == "Sam joined Flat 4B."
    assert world.say(SAM, FLAT, "join") == "You're already in."
    world.say(RAJ, FLAT, "balances")
    assert world.say(RAJ, FLAT, "yes") == "Raj joined Flat 4B."
    assert members(world) == ["Alex", "Sam", "Raj"]


def test_join_prompt_is_asked_once() -> None:
    world = World()
    world.say(YOU, FLAT, "help")
    world.say(SAM, FLAT, "balances")
    assert world.say(SAM, FLAT, "balances") == ""


def test_add_someone_with_a_contact_card_or_number() -> None:
    # A5, A13: the number is masked
    world = World()
    flat(world, YOU, SAM)
    added = world.say(YOU, FLAT, "add Priya", contact=ContactAttachment("Priya", "098765 00004"))
    assert added == "Alex added Priya to Flat 4B."
    assert "Priya" in members(world)
    assert world.say(SAM, None, "add Meera 9876500009") == "Got it: Meera (+91•••••00009)."


def test_unknown_name_asks_for_a_contact_then_carries_on() -> None:
    # A11: no name-only people
    world = World()
    world.say(YOU, None, "help")
    asked = world.say(YOU, None, "dinner 900 with Meera")
    assert asked == "I don't know Meera yet. Send their contact card or number."
    resumed = world.say(YOU, None, "+91 98765 00009")
    assert "dinner, ₹900.00, paid by Alex." in resumed
    assert "Meera: ₹450.00" in resumed


def test_two_people_with_one_name_are_told_apart() -> None:
    # A10: two Sams from two groups; picking one stores a nickname, so it's never asked again
    world = World()
    other_sam = Someone("Sam", "+919876500012")
    flat(world, YOU, SAM)
    world.say(other_sam, None, "help")
    world.say(YOU, "Goa trip", "help")
    world.say(other_sam, "Goa trip", "join")
    asked = world.say(YOU, None, "lunch 300 with Sam")
    assert asked == "Which Sam?\n1. Sam (+91•••••00002)\n2. Sam (+91•••••00012)"
    resumed = world.say(YOU, None, "2")
    assert "lunch, ₹300.00" in resumed
    world.say(YOU, None, "yes")
    assert "Which" not in world.say(YOU, None, "lunch 300 with Sam")


def test_nicknames_belong_to_their_owner() -> None:
    # A9
    world = World()
    flat(world, YOU, SAM, RAJ)
    assert world.say(RAJ, None, "call Sam Samuel") == "Got it, Samuel it is."
    assert "Samuel: ₹" in world.say(RAJ, None, "chai 100 with Samuel")
    assert "I don't know Samuel" in world.say(YOU, None, "chai 100 with Samuel")


def test_wrong_number_can_be_fixed_until_they_use_the_bot() -> None:
    # A12
    world = World()
    world.say(YOU, None, "help")
    world.say(YOU, None, "add Priya +919876500044")
    assert world.say(YOU, None, "Priya's number is +919876500004") == (
        "Updated: Priya is +91•••••00004."
    )
    world.say(PRIYA, None, "hi")
    assert "can't be changed" in world.say(YOU, None, "Priya's number is +919876500005")


def test_hidden_id_without_a_number_is_asked_to_message_first() -> None:
    # A7
    world = World()
    hidden = replace(world.message(YOU, FLAT, "help"), sender_ref="123@lid", sender_phone=None)
    assert world.send(hidden) == "Message me 1:1 first, so I can link this chat to your number."


def test_busy_group_chat_is_ignored() -> None:
    # B1: nothing addressed to the bot and nothing asked: no reply, no model call
    world = World()
    flat(world, YOU, SAM)
    assert world.say(SAM, FLAT, "lol", addressed=False) == ""
    assert world.say(SAM, FLAT, "who took my charger", addressed=False) == ""


def test_unaddressed_answer_to_an_open_question_counts() -> None:
    # B1: clear answers to its questions count even when not addressed
    world = World()
    flat(world, YOU, SAM)
    world.say(SAM, FLAT, "I usually don't drink beer pitcher")
    world.say(YOU, FLAT, image=receipt("restaurant_tip"))
    assert world.say(YOU, FLAT, "nice place", addressed=False) == ""
    assert "Sam: ₹" in world.say(SAM, FLAT, "1 no", addressed=False)


def test_moving_out_ends_membership_and_keeps_the_balance() -> None:
    # B2, B5
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.say(YOU, FLAT, "rent 3000, split all")
    world.say(YOU, FLAT, "yes")
    moved = world.say(SAM, FLAT, "Raj moved out")
    assert moved == "Raj left Flat 4B. Their balance stays until it's settled."
    assert members(world) == ["Alex", "Sam"]
    assert "Raj owes Alex ₹1,000.00" in world.say(YOU, FLAT, "balances")
    assert "You owe Alex ₹1,000.00" in world.say(RAJ, None, "what do I owe")
    assert "Raj" not in world.say(YOU, FLAT, "water 100, split all")


def test_leaving_the_chat_is_the_same_as_moving_out() -> None:
    world = World()
    flat(world, YOU, SAM, RAJ)
    left = world.send(
        world.message(SAM, FLAT, event=ChatEvent("participant_left", RAJ.ref), addressed=False)
    )
    assert left == "Raj left Flat 4B. Their balance stays until it's settled."


def test_a_leaver_is_taken_out_of_open_drafts() -> None:
    # B3: their questions are dropped and the draft is re-split
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.say(RAJ, FLAT, "I usually don't drink beer pitcher")
    world.say(YOU, FLAT, image=receipt("restaurant_tip"))
    shown = world.say(SAM, FLAT, "Raj moved out")
    assert "Raj" not in shown.split("\n", 1)[1]
    assert "Alex: ₹1,023.50" in shown and "Does" not in shown


def test_the_adder_leaving_cancels_the_draft() -> None:
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.say(RAJ, FLAT, image=receipt("restaurant_tip"))
    assert "cancelled: whoever added it left" in world.say(SAM, FLAT, "Raj moved out")


def test_rejoining_is_explicit_and_old_group_rules_apply_again() -> None:
    # B4
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.say(YOU, FLAT, "Raj doesn't drink milk")
    world.say(YOU, FLAT, "yes")
    world.say(SAM, FLAT, "Raj moved out")
    world.clock.advance(timedelta(days=1))
    assert "Raj owes" not in world.say(RAJ, FLAT, "balances")  # a leaver can still look
    assert world.say(RAJ, FLAT, "chai 100, split all") == 'Raj, join splits here? Say "join".'
    world.say(RAJ, FLAT, "join")
    shown = world.say(YOU, FLAT, "milk 300, split all")
    assert "Raj skipped: milk (group rule)" in shown


def test_a_leaver_is_taken_out_of_a_group_draft_filed_from_a_personal_chat() -> None:
    # B2/B3 across chats: the draft lives in Alex's personal chat
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.say(YOU, None, "split with Sam and Raj", image=receipt("restaurant_tip"))
    world.say(YOU, None, "add to Flat 4B")
    world.say(SAM, FLAT, "Raj moved out")
    assert world.in_chat(None, YOU) == "Raj left Flat 4B, so they're out of Toit."
    saved = world.say(YOU, None, "yes")
    assert "Raj" not in saved


def test_the_adder_leaving_cancels_a_filed_draft_in_their_chat() -> None:
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.say(RAJ, None, "split with Sam", image=receipt("restaurant_tip"))
    world.say(RAJ, None, "add to Flat 4B")
    world.say(SAM, FLAT, "Raj moved out")
    assert world.in_chat(None, RAJ) == "The Toit bill was cancelled: whoever added it left."


def test_only_whoever_gave_a_number_can_correct_it() -> None:
    # A12
    world = World()
    flat(world, YOU, SAM)
    world.say(YOU, FLAT, "add Priya +919876500044")
    refused = world.say(SAM, None, "Priya's number is +919876500055")
    assert refused == "Only whoever gave me their number can correct it."


def test_group_names_only_cover_the_group() -> None:
    # SPEC 10.7: no "which Sam?" listing someone from another group to the whole group
    world = World()
    other_sam = Someone("Sam", "+919876500012")
    flat(world, YOU, SAM)
    world.say(other_sam, None, "help")
    world.say(YOU, "Goa trip", "help")
    world.say(other_sam, "Goa trip", "join")
    shown = world.say(YOU, FLAT, "split with me and Sam", image=receipt("restaurant_tip"))
    assert "Which" not in shown and "Sam: ₹1,023.50" in shown


def test_unaddressed_chatter_is_ignored_while_someone_elses_prompt_is_open() -> None:
    # B1: Sam's "join splits here?" is only Sam's to answer
    world = World()
    flat(world, YOU, RAJ)
    world.say(SAM, FLAT, "balances")
    calls_before = world.model_calls(RAJ)
    for text in ("yes", "no", "2", "who took my charger"):
        assert world.say(RAJ, FLAT, text, addressed=False) == ""
    assert world.model_calls(RAJ) == calls_before


def test_unaddressed_non_answers_get_no_reply() -> None:
    # B1: an open line question makes the bot read chatter, but only answers count
    world = World()
    flat(world, YOU, SAM)
    world.say(SAM, FLAT, "I usually don't drink beer pitcher")
    world.say(YOU, FLAT, image=receipt("restaurant_tip"))
    assert world.say(SAM, FLAT, "5 no", addressed=False) == ""
