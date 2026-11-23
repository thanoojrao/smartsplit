"""Personal splits in a 1:1 chat with the bot (use cases D1-D9, L1, L5)."""

from datetime import timedelta

from smartsplit.adapters.fakes.agent import calls, say
from smartsplit.ports.agent import AgentRequest, ModelStep
from smartsplit.domain.enums import DraftState
from smartsplit.domain.messages import ContactAttachment
from smartsplit.domain.values import GroupContext
from tests.integration.world import FLAT, PRIYA, RAJ, SAM, YOU, Someone, World, call, calling
from tests.integration.world import flat, receipt

SAVE = calling("confirm_draft", draft="@D")


def know(world: World, *people: Someone) -> None:
    """Everyone says hi; Alex knows them by number."""
    for someone in (YOU, *people):
        world.say(someone, None, "hi")
    for someone in people:
        world.say(
            YOU,
            None,
            f"add {someone.name}",
            call("add_person", name=someone.name, phone=someone.phone),
        )


def test_photo_with_caption_splits_with_the_people_named() -> None:
    # D1: the speaker plus the people named; the speaker paid
    world = World()
    know(world, SAM, RAJ)
    summary = world.say(
        YOU,
        None,
        "split with Sam and Raj",
        calling("start_receipt", people=["@Sam", "@Raj"]),
        image=receipt("restaurant_tip"),
    )
    assert "paid by Alex" in summary and "Sam: ₹682.33" in summary


def test_photo_alone_waits_for_people_and_the_next_message_picks_it_up() -> None:
    # D2: no caption → "who's this with?"; a photo sent on its own is picked up later
    world = World()
    know(world, SAM)
    world.say(
        YOU,
        None,
        None,
        call("start_receipt"),
        say("Who's this with?"),
        image=receipt("restaurant_tip"),
    )
    assert [d.state for d in world.drafts(None, YOU)] == [DraftState.AWAITING_PEOPLE]
    shown = world.say(YOU, None, "Sam", calling("set_draft_people", draft="@D", people=["@Sam"]))
    assert "Sam: ₹1,023.50" in shown
    assert [d.state for d in world.drafts(None, YOU)] == [DraftState.REVIEWING]


def test_photo_then_caption_in_the_next_message() -> None:
    # D2, SPEC 10.4: start_receipt picks up the sender's last unused photo within 10 minutes
    world = World()
    know(world, SAM)
    world.say(YOU, None, None, say(""), image=receipt("restaurant_tip"))
    assert "[photo: receipt, Toit" in world.turn_input
    world.clock.advance(timedelta(minutes=5))
    shown = world.say(YOU, None, "split with Sam", calling("start_receipt", people=["@Sam"]))
    assert "Toit, ₹2,047.00" in shown
    world.clock.advance(timedelta(minutes=11))
    world.say(YOU, None, "split with Sam", calling("start_receipt", people=["@Sam"]))
    refused = world.agent.requests[-1].history[-1][1][0]
    assert refused.error == "There's no receipt photo from you here in the last 10 minutes."


def test_owes_all_and_payer_is_always_the_speaker() -> None:
    # D3, D4
    world = World()
    know(world, SAM)
    shown = world.say(
        YOU,
        None,
        "taxi 300, Sam owes all",
        calling(
            "add_manual_bill", description="taxi", amount="300", people=["@Sam"], owes_all="@Sam"
        ),
    )
    assert "Sam: ₹300.00" in shown and "Alex: ₹0.00" in shown
    world.say(
        YOU,
        None,
        "lunch 300 with Sam, Sam paid",
        calling(
            "add_manual_bill", description="lunch", amount="300", people=["@Sam"], payer="@Sam"
        ),
    )
    refused = world.agent.requests[-1].history[-1][1][0]
    assert refused.error == "In your own splits you're always the one who paid."


def test_unknown_name_keeps_the_draft_waiting_until_a_number_comes() -> None:
    # A11, SPEC 10.4: the draft is created in awaiting_people while the bot asks for a number
    world = World()
    know(world, SAM)
    world.say(
        YOU,
        None,
        "dinner 900 with Sam and Meera",
        calling(
            "add_manual_bill",
            description="dinner",
            amount="900",
            people=["@Sam"],
            unknown_names=["Meera"],
        ),
        say("I don't know Meera yet: send her contact card or number."),
    )
    draft = world.drafts(None, YOU)[0]
    assert (draft.state, draft.waiting_for) == (DraftState.AWAITING_PEOPLE, ("Meera",))
    world.say(YOU, None, "still there?", say(""))
    assert "names not found yet: Meera" in world.turn_input
    meera = ContactAttachment("Meera", "+919876500009")
    shown = world.say(
        YOU,
        None,
        None,
        call("add_person", name="Meera", phone=None, use_contact=True),
        calling("edit_draft", draft="@D", change={"type": "AddPeople", "people": ["@Meera"]}),
        contact=meera,
    )
    assert "Meera: ₹300.00" in shown
    assert world.drafts(None, YOU)[0].state is DraftState.REVIEWING


def test_two_sams_the_answer_becomes_a_nickname_and_the_draft_goes_on() -> None:
    # L5, A10: the draft is already created; "which Sam?" is the model's question
    world = World()
    other_sam = Someone("Sam", "+919876500010")
    flat(world, YOU, SAM)
    world.say(other_sam, None, "hi")
    world.say(YOU, "Goa trip", "hi")
    world.say(other_sam, "Goa trip", "join", call("join_group"))
    world.say(
        YOU,
        None,
        "lunch 600 with Sam",
        call("find_person", name="Sam"),
        call("add_manual_bill", description="lunch", amount="600", unknown_names=["Sam"]),
        say("Which Sam: Flat 4B or Goa trip?"),
    )
    matches = world.agent.requests[-2].history[-1][1][0].data["matches"]
    assert [m["known_from"] for m in matches] == [[FLAT], ["Goa trip"]]
    shown = world.say(YOU, None, "the Goa one", call("find_person", name="Sam"), _pick_goa_sam)
    assert "Sam: ₹300.00" in shown
    assert world.drafts(None, YOU)[0].waiting_for == ()
    me, goa_sam = world.person(YOU).id, world.person(other_sam).id
    with world.repository.unit_of_work() as uow:
        nicknames = uow.nicknames.for_owner(me)
    assert [n.subject_id for n in nicknames if n.name == "sam"] == [goa_sam]


def _pick_goa_sam(request: AgentRequest) -> ModelStep:
    found = request.history[-1][1][0].data["matches"]
    assert isinstance(found, list)
    goa = next(m["person"] for m in found if m["known_from"] == ["Goa trip"])
    return calls(
        ("set_nickname", {"person": goa, "nickname": "Sam"}),
        ("edit_draft", {"draft": "D1", "change": {"type": "AddPeople", "people": [goa]}}),
    )


def test_same_as_last_time_means_same_people_and_payer() -> None:
    # L1: a new bill with the people of the bill meant; amounts from the engine
    world = World()
    know(world, SAM, RAJ)
    world.say(
        YOU,
        None,
        "cleaner 1200 with Sam and Raj",
        calling("add_manual_bill", description="cleaner", amount="1200", people=["@Sam", "@Raj"]),
    )
    world.say(YOU, None, "yes", SAVE)
    shown = world.say(
        YOU,
        None,
        "same as last time but 1500",
        calling("add_manual_bill", description="cleaner", amount="1500", people=["@Sam", "@Raj"]),
    )
    assert "Sam: ₹500.00" in shown
    assert "B1" in world.turn_input


def test_filing_into_a_group_posts_the_saved_bill_there() -> None:
    # D5: group rules apply; confirmed in the personal chat; summary posted in the group
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.say(YOU, None, "taxi 600", call("add_manual_bill", description="taxi", amount="600"))
    shown = world.say(
        YOU, None, "add to Flat 4B", calling("file_into_group", draft="@D", group="@Flat 4B")
    )
    assert "Raj: ₹200.00" in shown
    assert isinstance(world.drafts(None, YOU)[0].context, GroupContext)
    world.say(YOU, None, "yes", SAVE)
    assert "Alex added a bill. Saved: taxi, ₹600.00." in world.in_chat(FLAT)
    assert "Saved: taxi" in world.in_chat(None, YOU)
    group_transcript = world.transcript(FLAT)
    assert group_transcript[-1].refs[0].kind == "bill"


def test_saved_split_notifies_people_who_use_the_bot_and_invites_the_rest() -> None:
    # D6, D7, D8
    world = World()
    know(world, SAM)
    world.say(YOU, None, "add Priya", call("add_person", name="Priya", phone=PRIYA.phone))
    world.say(
        YOU,
        None,
        "dinner 900",
        calling("add_manual_bill", description="dinner", amount="900", people=["@Sam", "@Priya"]),
    )
    saved = world.say(YOU, None, "yes", SAVE)
    assert "Priya hasn't used SmartSplit yet. Forward this to them:" in saved
    sent = world.tick()
    assert "Alex added dinner (21 Nov): your share is ₹300.00." in sent
    assert "Priya" not in [m.recipient_id for m in world.last]
    welcome = world.say(PRIYA, None, "hi", say("Alex added a split with you."))
    assert welcome.startswith("Hi Priya!")
    assert "Alex added dinner" in world.tick()


def test_several_bills_become_one_message_and_details_on_the_second_one_resolves() -> None:
    # D9, SPEC 8.6: the notification's references give "the second one" a handle
    world = World()
    know(world, SAM)
    for what, amount in (("taxi", "300"), ("lunch", "600"), ("movie", "900")):
        world.say(
            YOU,
            None,
            what,
            calling("add_manual_bill", description=what, amount=amount, people=["@Sam"]),
        )
        world.say(YOU, None, "yes", SAVE)
    combined = world.tick()
    assert "Alex added 3 bills:" in combined
    assert len(world.last) == 1
    shown = world.say(SAM, None, "details on the second one", call("get_bill", bill="B2"))
    assert "bot (showed B1, B2, B3)" in world.turn_input
    assert shown.startswith("lunch (21 Nov), paid by Alex, ₹600.00")


def test_a_personal_draft_belongs_to_its_adder() -> None:
    world = World()
    know(world, SAM)
    world.say(
        YOU,
        None,
        "taxi 300 with Sam",
        calling("add_manual_bill", description="taxi", amount="300", people=["@Sam"]),
    )
    world.say(SAM, None, "what's up", say(""))
    assert "no bills being added here" in world.turn_input


def test_nobody_named_in_a_personal_chat_asks_who() -> None:
    world = World()
    know(world)
    world.say(
        YOU, None, "groceries 500", call("add_manual_bill", description="groceries", amount="500")
    )
    result = world.agent.requests[-1].history[-1][1][0].data
    assert result["state"] == "awaiting_people" and result["next"] == "ask who it's with"


def test_raj_is_known_through_a_group_without_being_added() -> None:
    world = World()
    flat(world, YOU, RAJ)
    world.say(YOU, None, "who is Raj", call("find_person", name="Raj"))
    match = world.agent.requests[-1].history[-1][1][0].data["matches"]
    assert match == [
        {"person": "P2", "name": "Raj", "number": "+91•••••00003", "known_from": [FLAT]}
    ]
