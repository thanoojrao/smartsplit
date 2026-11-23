"""The refusals and less common paths of the tools: each is a short reason the model can act
on, and leaves nothing half done (SPEC 8.3)."""

from smartsplit.adapters.fakes.agent import call, say
from smartsplit.domain.enums import DraftState
from smartsplit.ports.agent import ToolResult
from tests.integration.world import FLAT, PRIYA, RAJ, SAM, YOU, World, calling, flat, receipt


def result(world: World) -> ToolResult:
    return world.agent.requests[-1].history[-1][1][0]


def manual(world: World, chat: str | None = FLAT, **more: object) -> str:
    return world.say(
        YOU, chat, "bill", calling("add_manual_bill", description="dinner", amount="300", **more)
    )


def change(world: World, chat: str | None, change: dict[str, object]) -> ToolResult:
    world.say(YOU, chat, "edit", calling("edit_draft", draft="@D", change=change))
    return result(world)


def test_people_edits_and_their_refusals() -> None:
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.say(PRIYA, None, "hi")
    manual(world)
    assert change(world, FLAT, {"type": "RemovePeople", "people": ["me"]}).error == (
        "The one who paid stays in the bill."
    )
    assert change(world, FLAT, {"type": "SetPayer", "person": "@Sam"}).ok
    assert "paid by Sam" in world.in_chat(FLAT)
    assert change(world, FLAT, {"type": "RemovePeople", "people": ["@Raj"]}).ok
    assert change(world, FLAT, {"type": "AddPeople", "people": ["@Raj"]}).ok
    assert "Raj: ₹100.00" in world.in_chat(FLAT)


def test_unassigning_someone_from_every_line() -> None:
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.say(YOU, FLAT, "split", call("start_receipt"), image=receipt("restaurant_tip"))
    assert change(world, FLAT, {"type": "UnassignLine", "line": None, "people": ["@Raj"]}).ok
    assert "Raj: ₹0.00" in world.in_chat(FLAT)


def test_assignment_refusals() -> None:
    world = World()
    flat(world, YOU, SAM)
    manual(world)
    nobody = change(world, FLAT, {"type": "AssignLine", "line": "L1"})
    assert nobody.error == "Say who shares that line."
    heavy = change(
        world,
        FLAT,
        {"type": "AssignLine", "line": "L1", "weights": [{"person": "@Sam", "weight": 5000}]},
    )
    assert heavy.error == "Weights are whole numbers from 1 to 1000."
    twice = change(
        world,
        FLAT,
        {
            "type": "AssignLine",
            "line": "L1",
            "exact": [{"person": "@Sam", "amount": "10"}, {"person": "@Sam", "amount": "20"}],
        },
    )
    assert twice.error == "Each person can have one amount."
    alone = change(world, FLAT, {"type": "UnassignLine", "line": "L1", "people": ["me", "@Sam"]})
    assert alone.error == "Someone has to share the dinner."


def test_personal_drafts_have_no_other_payer_and_need_someone_else() -> None:
    world = World()
    world.say(YOU, None, "hi")
    world.say(SAM, None, "hi")
    world.say(YOU, None, "add Sam", call("add_person", name="Sam", phone=SAM.phone))
    manual(world, None, people=["@Sam"])
    assert change(world, None, {"type": "SetPayer", "person": "@Sam"}).error == (
        "In your own splits you're always the one who paid."
    )
    world.say(YOU, None, "save", calling("confirm_draft", draft="@D"))
    manual(world, None)
    world.say(YOU, None, "just me", calling("set_draft_people", draft="@D", people=[]))
    assert result(world).error == "Who else is in it?"


def test_a_queued_personal_bill_asks_who_when_its_turn_comes() -> None:
    world = World()
    world.say(YOU, None, "hi")
    world.say(SAM, None, "hi")
    world.say(YOU, None, "add Sam", call("add_person", name="Sam", phone=SAM.phone))
    manual(world, None, people=["@Sam"])
    world.say(YOU, None, "and this", call("start_receipt"), image=receipt("restaurant_tip"))
    assert [d.state for d in world.drafts(None, YOU)] == [DraftState.REVIEWING, DraftState.QUEUED]
    world.say(YOU, None, "cancel the first", calling("cancel_draft", draft="@D"))
    assert "Next up, the Toit bill. Who's it with?" in world.in_chat(None, YOU)
    world.say(YOU, None, "edit queued", say(""))
    assert "awaiting people" in world.turn_input


def test_a_queued_bill_cant_be_edited_yet() -> None:
    world = World()
    flat(world, YOU, SAM)
    manual(world)
    world.say(YOU, FLAT, "another", call("start_receipt"), image=receipt("restaurant_tip"))
    world.say(
        YOU,
        FLAT,
        "edit the second",
        call("edit_draft", draft="D2", change={"type": "SetTotal", "amount": "10"}),
    )
    assert result(world).error is not None


def test_filing_refusals() -> None:
    world = World()
    flat(world, YOU, SAM)
    world.say(PRIYA, None, "hi")
    world.say(YOU, None, "add Priya", call("add_person", name="Priya", phone=PRIYA.phone))
    manual(world, None, people=["@Priya"])
    world.say(YOU, None, "file it", calling("file_into_group", draft="@D", group="@Flat 4B"))
    assert result(world).error == "Everyone in this bill has to be in Flat 4B."
    manual(world, FLAT)
    world.say(YOU, FLAT, "file it", calling("file_into_group", draft="@D", group="@Flat 4B"))
    assert result(world).error == "That's for bills in your own chat with me."


def test_adding_by_mention_only_in_a_group() -> None:
    world = World()
    flat(world, YOU, SAM)
    world.say(RAJ, None, "hi")
    world.say(YOU, None, "add Raj", call("add_person", name="Raj", phone=RAJ.phone))
    world.say(YOU, None, "add him", calling("add_person", name="Raj", mention="@Raj"))
    assert result(world).error == "Mentions only add people in a group chat."
    added = world.say(SAM, FLAT, "add Raj", call("add_person", name="Raj", phone=RAJ.phone))
    assert added == "Sam added Raj to Flat 4B."
    assert world.say(SAM, FLAT, "add Raj", calling("add_person", name="Raj", phone=RAJ.phone)) == (
        "Raj is already in."
    )


def test_balances_for_a_named_group_and_a_pair_in_a_group() -> None:
    world = World()
    flat(world, YOU, SAM)
    manual(world)
    world.say(YOU, FLAT, "yes", calling("confirm_draft", draft="@D"))
    shown = world.say(YOU, None, "Flat 4B?", calling("get_balances", group="@Flat 4B"))
    assert shown == "Sam owes Alex ₹150.00"
    pair = world.say(SAM, FLAT, "me and Alex?", calling("get_balances", with_person="@Alex"))
    assert pair == "Here, you owe Alex ₹150.00."
    world.say(YOU, FLAT, "me and Sam?", calling("get_balances", with_person="@Sam"))
    assert world.in_chat(FLAT) == "Here, Sam owes you ₹150.00."


def test_bill_lists_by_text_and_by_person_and_a_bill_line_by_line() -> None:
    world = World()
    flat(world, YOU, SAM)
    manual(world)
    world.say(YOU, FLAT, "yes", calling("confirm_draft", draft="@D"))
    world.say(YOU, None, "the dinner bill", call("list_bills", text="din"))
    assert result(world).data == {"bills": ["B1"]}
    world.say(YOU, None, "bills with Sam", calling("list_bills", person="@Sam"))
    assert result(world).data == {"bills": ["B1"]}
    world.say(YOU, None, "nothing", call("list_bills", text="pizza"))
    assert world.in_chat(None, YOU) == "No bills like that."
    shown = world.say(YOU, FLAT, "details", calling("get_bill", bill="@B"))
    assert shown.startswith("dinner (21 Nov), paid by Alex, ₹300.00\n1. dinner ₹300.00:")


def test_deleting_a_group_rule_about_someone_else_needs_a_yes() -> None:
    world = World()
    flat(world, YOU, SAM)
    world.say(SAM, FLAT, "no chips", call("add_rule", subject="me", item="chips", kind="exclude"))
    asked = world.say(
        YOU, FLAT, "Sam eats chips now", calling("delete_rule", subject="@Sam", item="chips")
    )
    assert asked == "Remove this rule: Sam never shares chips?\nWaiting for Alex to say yes."
    assert world.say(YOU, FLAT, "yes", calling("confirm_pending", action="@A")) == (
        "Alex removed a rule: Sam never shares chips."
    )


def test_a_stale_bill_change_is_refused_on_yes() -> None:
    world = World()
    flat(world, YOU, SAM)
    manual(world)
    world.say(YOU, FLAT, "yes", calling("confirm_draft", draft="@D"))
    world.say(YOU, FLAT, "delete", calling("change_bill", bill="@B", change={"type": "DeleteBill"}))
    world.say(SAM, FLAT, "delete", calling("change_bill", bill="@B", change={"type": "DeleteBill"}))
    world.say(YOU, FLAT, "yes", calling("confirm_pending", action="A1"))
    assert result(world).ok
    world.say(SAM, FLAT, "yes", calling("confirm_pending", action="A1"))
    assert result(world).error == "That bill was already changed or deleted."


def test_the_payer_cant_say_not_mine_and_matches_are_fixed_only_in_review() -> None:
    world = World()
    flat(world, YOU, SAM)
    manual(world)
    world.say(YOU, FLAT, "yes", calling("confirm_draft", draft="@D"))
    world.say(YOU, FLAT, "not mine", calling("change_bill", bill="@B", change={"type": "NotMine"}))
    assert "it stays yours" in str(result(world).error)
    world.say(
        YOU,
        FLAT,
        "not milk",
        calling("change_bill", bill="@B", change={"type": "NotThisItem", "line": "L1"}),
    )
    assert result(world).error == "Item matches can only be fixed while a bill is under review."
