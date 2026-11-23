"""Every review edit on a draft, and the refusals that keep it consistent (C6, G6, SPEC 10.4)."""

from smartsplit.adapters.fakes.llm import FakeCanonicalizer
from smartsplit.domain.values import GroupScope
from tests.integration.world import FLAT, PRIYA, RAJ, SAM, YOU, World, flat, receipt

OUTSIDER = 'Priya isn\'t in Flat 4B. "add Priya" with a contact.'


def reviewing() -> World:
    world = World(canonical=FakeCanonicalizer({"OAT MLK 1L": "milk"}))
    flat(world, YOU, SAM, RAJ)
    world.say(YOU, FLAT, image=receipt("total_mismatch"))
    return world


def test_payer_change_in_a_group_draft() -> None:
    world = reviewing()
    assert "paid by Sam" in world.say(YOU, FLAT, "Sam paid")


def test_payer_must_be_a_member() -> None:
    world = reviewing()
    world.say(YOU, None, "add Priya +919876500004")
    assert world.say(YOU, FLAT, "Priya paid") == OUTSIDER


def test_people_added_and_removed() -> None:
    world = reviewing()
    removed = world.say(YOU, FLAT, "take Raj off the bill")
    assert "Raj" not in removed.split("\n", 1)[1]
    assert "Raj: ₹186.66" in world.say(YOU, FLAT, "add Raj to the bill")
    assert world.say(YOU, FLAT, "remove me from the bill") == "The one who paid stays in the bill."


def test_only_members_can_be_added() -> None:
    world = reviewing()
    world.say(YOU, None, "add Priya +919876500004")
    assert world.say(YOU, FLAT, "add Priya to the bill") == OUTSIDER


def test_accepting_the_difference_during_review() -> None:
    world = reviewing()
    accepted = world.say(YOU, FLAT, "accept the difference")
    assert "add up to" not in accepted
    assert "Kirana, ₹570.00" in accepted
    assert "Saved: Kirana, ₹570.00." in world.say(YOU, FLAT, "yes")


def test_exact_part_of_a_line() -> None:
    # E8 through the chat
    world = reviewing()
    shown = world.say(YOU, FLAT, "Sam's part of the rice was 100")
    assert "Sam: ₹146.67" in shown


def test_exact_parts_must_fit() -> None:
    world = reviewing()
    assert world.say(YOU, FLAT, "Sam's part of the rice was 500") == (
        "Those amounts don't add up to the total."
    )


def test_lines_by_name_and_number_must_exist() -> None:
    world = reviewing()
    assert world.say(YOU, FLAT, "line 9 is 100") == "There's no line 9."
    assert world.say(YOU, FLAT, "remove the caviar") == "I can't find a line called caviar."


def test_someone_has_to_share_each_line() -> None:
    world = reviewing()
    world.say(YOU, FLAT, "2 for Sam, 1 for Raj on the rice")
    world.say(YOU, FLAT, "Sam had none of the rice")
    assert world.say(YOU, FLAT, "Raj had none of the rice") == "Someone has to share the Rice 5kg."


def test_assigning_someone_not_in_the_bill() -> None:
    world = reviewing()
    world.say(YOU, FLAT, "take Raj off the bill")
    assert world.say(YOU, FLAT, "2 for Sam, 1 for Raj on the rice") == "Add them to the bill first."


def test_forgetting_a_wrong_match() -> None:
    # F12 without naming the right item: the line becomes its own item here
    world = World(canonical=FakeCanonicalizer({"OAT MLK 1L": "milk"}))
    flat(world, YOU, SAM)
    world.say(YOU, FLAT, "milk 100, split all")
    world.say(YOU, FLAT, "yes")
    shown = world.say(YOU, FLAT, image=receipt("milk_discount_linked"))
    assert "New match: OAT MLK 1L → milk?" in shown
    fixed = world.say(YOU, FLAT, "that's not milk")
    assert "New match" not in fixed
    assert "1. OAT MLK 1L ₹240.00" in world.say(YOU, FLAT, "details")
    with world.repository.unit_of_work() as uow:
        group = uow.groups.by_channel_ref(world.message(YOU, FLAT).conversation)
        assert group is not None
        assert uow.aliases.for_scope(GroupScope(group.id)) == ()


def test_details_and_edits_need_a_draft() -> None:
    world = World()
    flat(world, YOU, SAM, PRIYA)
    assert world.say(YOU, FLAT, "details") == "There's no bill under review here."
    assert world.say(YOU, FLAT, "yes") == "There's nothing to save right now."
    assert world.say(YOU, FLAT, "cancel") == "There's no bill to cancel here."
    assert world.say(YOU, FLAT, "save") == "There's no bill under review here."
