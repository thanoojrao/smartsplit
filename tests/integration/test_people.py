"""People, identity and membership (use cases A1-A13, B1-B5, L8)."""

from dataclasses import replace

from smartsplit.adapters.fakes.agent import call, say
from smartsplit.domain.enums import DraftState
from smartsplit.domain.messages import ChatEvent, ContactAttachment
from tests.integration.world import FLAT, PRIYA, RAJ, SAM, YOU, World, calling, flat, receipt


def test_first_personal_message_creates_the_person_and_welcomes_them() -> None:
    # A1: the welcome is fixed; the model sees that it was shown
    world = World()
    reply = world.say(YOU, None, "hi", say("Ask me anything."))
    assert reply.startswith("Hi Alex! I split bills")
    assert reply.endswith("Ask me anything.")
    assert "the welcome message was just shown" in world.turn_input
    assert "Hi Alex!" not in world.say(YOU, None, "hi again", say("Hello."))


def test_a_new_group_chat_creates_the_group_and_the_first_speaker_joins() -> None:
    # A2, A3: everyone else joins explicitly, announced
    world = World()
    flat(world, YOU)
    assert "Alex is in." in world.transcript(FLAT)[-1].text
    world.say(SAM, None, "hi")
    joined = world.say(SAM, FLAT, "join", call("join_group"))
    assert joined == "Sam joined Flat 4B."


def test_a_non_member_can_only_join() -> None:
    # A4, SPEC 10.3: tools refuse anything else for them until they do
    world = World()
    flat(world, YOU, SAM)
    world.say(RAJ, None, "hi")
    world.say(RAJ, FLAT, "balances", call("get_balances"), say("Join first?"))
    refused = world.agent.requests[-1].history[-1][1][0]
    assert refused.error == 'Raj isn\'t in this group yet: say "join".'
    assert "(the speaker isn't a member of this group)" in world.turn_input


def test_a_member_adds_someone_with_a_number_or_a_contact_card() -> None:
    # A5, A11: no name-only people
    world = World()
    flat(world, YOU, SAM)
    world.say(YOU, FLAT, "add Priya", call("add_person", name="Priya"))
    assert world.agent.requests[-1].history[-1][1][0].error == (
        "I need Priya's contact card or phone number."
    )
    added = world.say(
        YOU,
        FLAT,
        None,
        call("add_person", name="Priya", use_contact=True),
        contact=ContactAttachment("Priya", "098765 00004"),
    )
    assert added == "Alex added Priya to Flat 4B."
    assert world.person(PRIYA).phone == PRIYA.phone


def test_numbers_are_masked_in_the_bots_words() -> None:
    # A13, SPEC 8.5: whatever the model writes, a full number never goes out
    world = World()
    reply = world.say(YOU, None, "hi", say("Your number is +91 98765 00001, right?"))
    assert "+91•••••00001" in reply and "98765 00001" not in reply


def test_handles_become_names_and_markdown_becomes_plain_text() -> None:
    # SPEC 8.5, L16
    world = World()
    flat(world, YOU, SAM)
    reply = world.say(YOU, FLAT, "hey", say("## Done\n**P2** owes you, see [this](https://x.y)."))
    assert reply == "Done\n*Sam* owes you, see this (https://x.y)."


def test_moving_out_ends_the_membership_and_their_drafts_are_re_split() -> None:
    # B2, B3: announced; the draft is re-split and shown again
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.say(YOU, FLAT, "split", call("start_receipt"), image=receipt("restaurant_tip"))
    left = world.say(SAM, FLAT, "Raj moved out", calling("member_left", person="@Raj"))
    assert "Raj left Flat 4B. Their balance stays until it's settled." in left
    assert "Raj" not in left.split("settled.")[1]
    assert world.drafts(FLAT)[0].participants == (world.person(YOU).id, world.person(SAM).id)


def test_leaving_the_chat_is_an_event_handled_without_the_model() -> None:
    # B2
    world = World()
    flat(world, YOU, SAM)
    calls_before = len(world.agent.requests)
    world.send(world.message(SAM, FLAT, event=ChatEvent("participant_left", SAM.ref)))
    assert world.in_chat(FLAT) == "Sam left Flat 4B. Their balance stays until it's settled."
    assert len(world.agent.requests) == calls_before


def test_the_adder_leaving_cancels_their_draft() -> None:
    world = World()
    flat(world, YOU, SAM)
    world.say(SAM, FLAT, "split", call("start_receipt"), image=receipt("restaurant_tip"))
    world.say(YOU, FLAT, "Sam left", calling("member_left", person="@Sam"))
    assert world.drafts(FLAT)[0].state is DraftState.CANCELLED


def test_a_leaver_can_still_see_balances_but_not_add_bills() -> None:
    # B2, B4: rejoining is explicit
    world = World()
    flat(world, YOU, SAM)
    world.say(SAM, FLAT, "bye", call("member_left", person="me"))
    world.say(SAM, FLAT, "balances", call("get_balances"))
    assert world.agent.requests[-1].history[-1][1][0].ok
    world.say(SAM, FLAT, "taxi 100", call("add_manual_bill", description="taxi", amount="100"))
    assert world.agent.requests[-1].history[-1][1][0].ok is False
    assert world.say(SAM, FLAT, "join", call("join_group")) == "Sam joined Flat 4B."


def test_nicknames_are_per_speaker() -> None:
    # A9
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.say(
        RAJ, None, "call Sam Samuel", calling("set_nickname", person="@Sam", nickname="Samuel")
    )
    world.say(RAJ, None, "who", say(""))
    assert "Samuel" in world.turn_input
    world.say(YOU, None, "who", say(""))
    assert "Samuel" not in world.turn_input


def test_a_number_can_be_corrected_until_they_use_the_bot() -> None:
    # A12
    world = World()
    world.say(YOU, None, "hi")
    world.say(YOU, None, "add Priya", call("add_person", name="Priya", phone="+919876500099"))
    fixed = world.say(
        YOU,
        None,
        "her number is ...",
        calling("correct_number", person="@Priya", phone=PRIYA.phone),
    )
    assert fixed == "Updated: Priya is +91•••••00004."
    world.say(PRIYA, None, "hi")
    world.say(
        YOU, None, "fix it", calling("correct_number", person="@Priya", phone="+919876500098")
    )
    assert "can't be changed" in str(world.agent.requests[-1].history[-1][1][0].error)


def test_group_chatter_never_reaches_the_model_and_is_not_stored() -> None:
    # B1, L8
    world = World()
    flat(world, YOU, SAM)
    before = len(world.agent.requests), len(world.transcript(FLAT))
    assert world.say(SAM, FLAT, "who took my charger", addressed=False) == ""
    assert (len(world.agent.requests), len(world.transcript(FLAT))) == before


def test_an_addressed_message_the_model_ignores_leaves_no_trace_in_the_group() -> None:
    # SPEC 10.2, 8.6: only messages the bot answered or acted on are stored in a group
    world = World()
    flat(world, YOU, SAM)
    before = len(world.transcript(FLAT))
    world.say(SAM, FLAT, "@bot lol", say(""))
    assert len(world.transcript(FLAT)) == before


def test_someone_with_only_a_hidden_id_is_asked_to_message_first() -> None:
    # A7
    world = World()
    flat(world, YOU)
    reply = world.send(replace(world.message(PRIYA, FLAT, "hi"), sender_phone=None))
    assert reply.startswith("Message me 1:1 first")
