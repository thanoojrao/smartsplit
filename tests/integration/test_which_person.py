"""Names in group bills: sure matches, "Which Sam?" settled by the adder, nobody found
(SPEC 6.1, 10.4; L5), plus the listening hint for unaddressed messages (SPEC 10.2)."""

from smartsplit.adapters.fakes.agent import call, say
from smartsplit.domain.enums import DraftState
from tests.integration.world import FLAT, RAJ, SAM, YOU, Someone, World, calling, flat

OTHER_SAM = Someone("Sam", "+919876500010")
DINNER = call("add_manual_bill", description="dinner", amount="900", unknown_names=["Sam"])


def test_a_group_bill_with_a_sure_name_is_the_adder_and_them() -> None:
    world = World()
    flat(world, YOU, SAM, RAJ)
    shown = world.say(YOU, FLAT, "dinner 900 with Sam", DINNER)
    assert "Alex: ₹450.00" in shown and "Sam: ₹450.00" in shown
    assert "Raj" not in shown


def test_which_sam_in_a_group_is_settled_by_the_adder() -> None:
    world = World()
    flat(world, YOU, SAM, OTHER_SAM, RAJ)
    asked = world.say(YOU, FLAT, "dinner 900 with Sam", DINNER)
    assert asked.startswith("Which Sam?\n1. Sam, +91•••••00002\n2. Sam, +91•••••00010")
    refused = world.say(
        RAJ, FLAT, "the second", calling("pick_person", question="@Q", option=2), say("")
    )
    assert refused == ""
    error = world.agent.requests[-1].history[-1][1][0].error
    assert error == "Only Alex can say who they meant."
    shown = world.say(YOU, FLAT, "2", calling("pick_person", question="@Q", option=2))
    assert "Alex: ₹450.00" in shown
    draft = world.drafts(FLAT)[0]
    assert (draft.state, draft.waiting_for) == (DraftState.REVIEWING, ())
    assert set(draft.participants) == {world.person(YOU).id, world.person(OTHER_SAM).id}


def test_someone_not_in_the_group_is_asked_to_join() -> None:
    world = World()
    flat(world, YOU, SAM)
    world.say(OTHER_SAM, None, "hi")
    meera = call("add_manual_bill", description="dinner", amount="900", unknown_names=["Meera"])
    asked = world.say(YOU, FLAT, "dinner 900 with Meera", meera)
    assert (
        asked == "I can't find Meera in this group. If they're in this chat, they can say \"join\"."
    )


def test_an_unaddressed_message_from_someone_waited_on_carries_a_hint() -> None:
    world = World()
    flat(world, YOU, SAM)
    world.say(SAM, FLAT, "lol", say(""), addressed=False)
    assert "[not addressed to you" in world.turn_input
    world.say(SAM, FLAT, "hey bot", say("Hi Sam."))
    assert "[not addressed to you" not in world.turn_input
    world.say(SAM, None, "hi", say("Hi."))
    assert "[not addressed to you" not in world.turn_input


def test_which_sam_in_a_group_shows_group_names_not_the_adders_nicknames() -> None:
    # SPEC 6.1: the adder's own nicknames are private to their chat
    world = World()
    flat(world, YOU, SAM, OTHER_SAM, RAJ)
    world.say(
        YOU, None, "gym sam", call("add_person", name="Sam from the gym", phone=OTHER_SAM.phone)
    )
    asked = world.say(YOU, FLAT, "dinner 900 with Sam", DINNER)
    assert asked.startswith("Which Sam?\n1. Sam, +91•••••00002\n2. Sam, +91•••••00010")
    assert "gym" not in world.turn_input
