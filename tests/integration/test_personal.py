"""Personal splits in a 1:1 chat with the bot (use cases D1-D5)."""

from tests.integration.world import FLAT, PRIYA, RAJ, SAM, YOU, Someone, World, flat, receipt


def known(world: World) -> None:
    world.say(YOU, None, "help")
    world.say(YOU, None, "add Sam +919876500002")
    world.say(YOU, None, "add Raj +919876500003")


def test_photo_with_a_caption_names_who_it_is_with() -> None:
    # D1
    world = World()
    known(world)
    summary = world.say(YOU, None, "split with Sam and Raj", image=receipt("restaurant_tip"))
    assert "Toit, ₹2,047.00, paid by Thanoo." in summary
    assert "Sam: ₹682.33" in summary and "Raj: ₹682.33" in summary
    saved = world.say(YOU, None, "yes")
    assert "Saved: Toit, ₹2,047.00." in saved
    assert "Sam owes you ₹682.33" in saved


def test_photo_without_a_caption_asks_who_it_is_with() -> None:
    # D2: a numbered list of groups and frequent people, or names
    world = World()
    flat(world, YOU, SAM)
    world.say(YOU, None, "chai 100 with Sam")
    world.say(YOU, None, "yes")
    asked = world.say(YOU, None, image=receipt("restaurant_tip"))
    assert asked == 'Who\'s this with?\n1. Flat 4B\n2. Sam\nOr say names: "with Sam and Raj".'
    shown = world.say(YOU, None, "2")
    assert "Sam: ₹1,023.50" in shown
    world.say(YOU, None, "cancel")
    world.say(YOU, None, image=receipt("restaurant_tip"))
    named = world.say(YOU, None, "with Sam")
    assert "Sam: ₹1,023.50" in named


def test_typed_bill_with_nobody_named_asks_too() -> None:
    world = World()
    flat(world, YOU, SAM)
    assert world.say(YOU, None, "taxi 600").startswith("Who's this with?")
    assert "taxi, ₹600.00" in world.say(YOU, None, "with Sam")


def test_someone_owes_all_of_it() -> None:
    # D3
    world = World()
    known(world)
    shown = world.say(YOU, None, "split with Sam, Sam owes all", image=receipt("restaurant_tip"))
    assert "Sam: ₹2,047.00" in shown and "Thanoo: ₹0.00" in shown


def test_the_payer_is_always_you_in_personal_splits() -> None:
    # D4
    world = World()
    known(world)
    refused = world.say(YOU, None, "split with Sam, Sam paid", image=receipt("restaurant_tip"))
    assert refused == "In your own splits you're always the one who paid."


def test_filing_a_personal_draft_into_a_group() -> None:
    # D5: group rules apply, questions asked here, confirmed here, posted in the group
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.say(SAM, FLAT, "I usually don't drink beer pitcher")
    world.say(YOU, None, "split with Sam and Raj", image=receipt("restaurant_tip"))
    filed = world.say(YOU, None, "add to Flat 4B")
    assert "1) Does Sam share the Beer Pitcher" in filed
    world.say(YOU, None, "1 no")
    world.say(YOU, None, "yes")
    in_group = world.in_chat(FLAT)
    assert in_group.startswith("Thanoo added a bill. Saved: Toit, ₹2,047.00.")
    assert "Sam owes Thanoo" in in_group
    assert "Saved: Toit" in world.in_chat(None, YOU)


def test_filing_needs_membership() -> None:
    world = World()
    flat(world, SAM, RAJ)
    world.say(YOU, None, "help")
    world.say(YOU, None, "add Sam +919876500002")
    world.say(YOU, None, "split with Sam", image=receipt("restaurant_tip"))
    assert world.say(YOU, None, "add to Flat 4B") == "You're not in a group called Flat 4B."


def test_cancelling_a_personal_split() -> None:
    world = World()
    known(world)
    world.say(YOU, None, "taxi 600 with Sam")
    assert world.say(YOU, None, "cancel") == "Cancelled the taxi bill. Nothing was saved."


def test_the_photo_waits_while_the_bot_asks_who_someone_is() -> None:
    # A11 with a photo: the receipt isn't lost while the contact is asked for
    world = World()
    world.say(YOU, None, "help")
    asked = world.say(YOU, None, "split with Meera", image=receipt("restaurant_tip"))
    assert asked == "I don't know Meera yet. Send their contact card or number."
    resumed = world.say(YOU, None, "+91 98765 00009")
    assert "Toit, ₹2,047.00" in resumed and "Meera: ₹1,023.50" in resumed


def test_moving_on_drops_an_unanswered_which_person() -> None:
    world = World()
    other_sam = Someone("Sam", "+919876500012")
    flat(world, YOU, SAM)
    world.say(other_sam, None, "help")
    world.say(YOU, "Goa trip", "help")
    world.say(other_sam, "Goa trip", "join")
    assert world.say(YOU, None, "chai 100 with Sam").startswith("Which Sam?")
    world.say(YOU, None, "add Priya +919876500004")
    world.say(YOU, None, "pizza 600 with Priya")
    assert "Saved: pizza" in world.say(YOU, None, "yes")


def test_no_dm_without_a_personal_chat() -> None:
    # SPEC 10.7: the wider answer never goes to the group, even with nowhere else to send it
    world = World()
    flat(world, YOU, SAM)
    world.say(YOU, "Goa trip", "help")
    world.say(PRIYA, "Goa trip", "join")
    world.say(PRIYA, FLAT, "join")
    world.say(YOU, "Goa trip", "boat 300, split all")
    world.say(YOU, "Goa trip", "yes")
    assert world.say(PRIYA, FLAT, "balances") == (
        "Everyone is settled up here.\nMessage me 1:1 and I'll send you the rest there."
    )
