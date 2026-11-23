"""Editing, deleting and "not mine" on saved bills (use cases H1-H5)."""

from tests.integration.world import FLAT, RAJ, SAM, YOU, World, flat, receipt


def friends(world: World) -> None:
    for person in (YOU, SAM, RAJ):
        world.say(person, None, "help")
    world.say(YOU, None, "add Sam +919876500002")
    world.say(YOU, None, "add Raj +919876500003")


def saved_toit(world: World) -> None:
    friends(world)
    world.say(YOU, None, "split with Sam and Raj", image=receipt("restaurant_tip"))
    world.say(YOU, None, "yes")
    world.tick()


def test_editing_a_saved_bill_is_confirmed_and_others_are_told_why() -> None:
    # H1: reversal + new bill; the reason travels with the notification
    world = World()
    saved_toit(world)
    asked = world.say(YOU, None, "edit the Toit bill: Raj wasn't there, he left early")
    assert asked == (
        "Change Toit: Alex ₹682.34 → ₹1,023.50, Sam ₹682.33 → ₹1,023.50, Raj ₹682.33 → ₹0.00?"
        ' Say "yes" to confirm.'
    )
    done = world.say(YOU, None, "yes")
    assert done.startswith("Changed Toit.")
    assert "Sam owes you ₹1,023.50" in done
    world.tick()
    assert world.in_chat(None, SAM) == (
        "Alex changed Toit (he left early): your share is now ₹1,023.50.\n"
        "Overall you owe Alex ₹1,023.50."
    )
    assert world.in_chat(None, RAJ).startswith("Alex changed Toit (he left early)")
    assert "You and Alex are settled up." in world.in_chat(None, RAJ)


def test_any_participant_can_edit() -> None:
    world = World()
    saved_toit(world)
    asked = world.say(SAM, None, "not mine 1")
    assert asked.startswith("Change Toit:")
    assert "Sam ₹682.33 → ₹0.00" in asked


def test_not_mine_removes_you_and_re_splits_your_part() -> None:
    # H2: from the notification, Raj replies "not mine"
    world = World()
    saved_toit(world)
    asked = world.say(RAJ, None, "not mine")
    assert asked.startswith("Change Toit: Alex ₹682.34 → ₹1,023.50")
    world.say(RAJ, None, "yes")
    assert world.say(RAJ, None, "what do I owe") == "You're all settled up."
    world.tick()
    assert "Raj changed Toit (not mine)" in world.in_chat(None, SAM)


def test_the_payer_cannot_say_not_mine() -> None:
    world = World()
    saved_toit(world)
    world.say(YOU, None, "last 1 bills")
    assert "You paid for that one" in world.say(YOU, None, "not mine 1")


def test_deleting_your_last_bill() -> None:
    # H3
    world = World()
    saved_toit(world)
    asked = world.say(YOU, None, "delete last bill")
    assert asked == 'Delete Toit (₹2,047.00)? Say "yes" to confirm.'
    assert world.say(YOU, None, "yes") == "Deleted Toit.\nYou're all settled up."
    world.tick()
    assert world.in_chat(None, SAM) == ("Alex deleted Toit.\nYou and Alex are settled up.")
    assert world.say(YOU, None, "delete last bill") == "I can't find that bill."


def test_changing_a_bill_twice_needs_the_latest_version() -> None:
    # the restated change is stale once the bill was changed meanwhile
    world = World()
    saved_toit(world)
    world.say(YOU, None, "delete last bill")
    world.say(SAM, None, "not mine 1")
    world.say(YOU, None, "yes")
    assert "changed meanwhile" in world.say(SAM, None, "yes")


def test_edits_to_group_bills_are_posted_in_the_group() -> None:
    # H4, from someone's personal chat too
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.say(YOU, FLAT, "rent 3000, split all")
    world.say(YOU, FLAT, "yes")
    assert world.say(SAM, FLAT, "last bill: Raj wasn't there") == "I can't find that bill."
    asked = world.say(YOU, FLAT, "last bill: Raj wasn't there")
    assert "Raj ₹1,000.00 → ₹0.00" in asked
    done = world.say(YOU, FLAT, "yes")
    assert done == "Changed rent.\nSam owes Alex ₹1,500.00"
    assert world.tick() == ""


def test_details_of_a_saved_bill() -> None:
    # H5: as saved, line by line
    world = World()
    saved_toit(world)
    world.say(YOU, None, "show last 1 bills")
    details = world.say(YOU, None, "details 1")
    assert details.startswith("Toit (21 Nov), paid by Alex, ₹2,047.00\n1. Margherita Pizza")
    assert "Sam: ₹682.33" in details
    assert world.say(YOU, None, "details 4") == "I haven't listed a bill 4 here."


def test_only_people_in_a_bill_can_change_it() -> None:
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.say(YOU, FLAT, "taxi 600 with me and Sam")
    world.say(YOU, FLAT, "yes")
    refused = world.say(RAJ, FLAT, "edit the taxi bill: Sam wasn't there")
    assert refused == "Only people in that bill can change it."
    assert world.say(YOU, None, "delete bill 9") == "I haven't listed a bill 9 here."


def test_a_reply_to_the_notification_edits_that_bill() -> None:
    # SPEC 10.5: "Reply ok, details, not mine, or tell me what to fix"
    world = World()
    saved_toit(world)
    asked = world.say(RAJ, None, "Sam wasn't there")
    assert asked.startswith("Change Toit:")
    assert world.say(RAJ, None, "edit the Toit bill: Sam wasn't there").startswith("Change Toit:")


def test_a_line_edit_on_a_saved_bill_moves_its_total() -> None:
    world = World()
    flat(world, YOU, SAM)
    world.say(YOU, FLAT, "rent 3000, split all")
    world.say(YOU, FLAT, "yes")
    asked = world.say(YOU, FLAT, "last bill: add water 300")
    assert asked == (
        "Change rent: total ₹3,000.00 → ₹3,300.00, Alex ₹1,500.00 → ₹1,650.00, "
        'Sam ₹1,500.00 → ₹1,650.00? Say "yes" to confirm.'
    )
    world.say(YOU, FLAT, "yes")
    world.say(YOU, FLAT, "last bill: line 1 is 3100")
    assert world.say(YOU, FLAT, "yes") == "Changed rent.\nSam owes Alex ₹1,700.00"


def test_details_of_a_saved_bill_show_tax_and_tip() -> None:
    world = World()
    saved_toit(world)
    world.say(YOU, None, "show last 1 bills")
    details = world.say(YOU, None, "details 1")
    assert "Tax ₹89.00\nTip, charges and discounts ₹178.00" in details
