"""Rules said in chat, matching shown in the summary, balances and privacy (F11-F16, I1-I4)."""

from smartsplit.adapters.fakes.llm import FakeCanonicalizer
from smartsplit.domain.values import GroupScope
from tests.integration.world import FLAT, PRIYA, RAJ, SAM, YOU, World, flat, receipt

GOA = "Goa trip"


def two_groups(world: World) -> None:
    flat(world, YOU, SAM, RAJ)
    world.say(PRIYA, None, "help")
    world.say(YOU, GOA, "help")
    world.say(RAJ, GOA, "join")
    world.say(PRIYA, GOA, "join")


def test_new_match_is_shown_once_and_can_be_fixed() -> None:
    # F11, F12
    world = World(canonical=FakeCanonicalizer({"2% MLK GAL": "milk"}))
    flat(world, YOU, SAM)
    world.say(YOU, FLAT, "milk 100, split all")
    world.say(YOU, FLAT, "yes")
    first = world.say(YOU, FLAT, image=receipt("grocery_taxed_mix"))
    assert "New match: 2% MLK GAL → milk?" in first
    fixed = world.say(YOU, FLAT, "that's not milk, it's yogurt")
    assert "New match" not in fixed
    details = world.say(YOU, FLAT, "details")
    assert "2% MLK GAL" in details
    world.say(YOU, FLAT, "yes")
    again = world.say(YOU, FLAT, image=receipt("grocery_taxed_mix"))
    assert "New match" not in again


def test_own_rules_apply_at_once_and_rules_about_others_need_yes() -> None:
    # F2, F3, K8: a rule about someone else is restated first
    world = World()
    flat(world, YOU, SAM, RAJ)
    assert world.say(RAJ, FLAT, "I don't drink milk") == "Noted: Raj never shares milk."
    asked = world.say(YOU, FLAT, "protein powder is Sam's")
    assert asked == 'Save this rule: protein powder is Sam\'s? Say "yes" to confirm.'
    assert world.say(SAM, FLAT, "yes") == "There's nothing to save right now."
    assert world.say(YOU, FLAT, "yes") == "Alex saved a rule: protein powder is Sam's."


def test_declining_a_restated_rule() -> None:
    world = World()
    flat(world, YOU, SAM)
    world.say(YOU, FLAT, "Sam doesn't eat chips")
    assert world.say(YOU, FLAT, "no") == "OK, nothing changed."
    assert "No rules" in world.say(YOU, FLAT, "rules about Sam")


def test_listing_rules_in_a_personal_chat() -> None:
    # F13: every rule about you, with scope and who set it
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.say(RAJ, None, "I don't drink milk")
    world.say(YOU, FLAT, "Raj doesn't eat chips")
    world.say(YOU, FLAT, "yes")
    listed = world.say(RAJ, None, "what rules are about me")
    assert "Raj never shares milk (everywhere, set by Raj)" in listed
    assert "Raj never shares chips (Flat 4B, set by Alex)" in listed


def test_listing_rules_in_a_group_shows_only_that_group() -> None:
    # F14: the full list goes to the personal chat
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.say(RAJ, None, "I don't drink milk")
    world.say(YOU, FLAT, "Raj doesn't eat chips")
    world.say(YOU, FLAT, "yes")
    world.say(RAJ, FLAT, "what rules are about me")
    assert world.in_chat(FLAT) == (
        "Raj never shares chips (set by Alex)\nI sent you the full list in a DM."
    )
    assert "milk (everywhere" in world.in_chat(None, RAJ)


def test_deleting_rules() -> None:
    # F9, F15: your own at once; group rules about others need yes and are announced
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.say(RAJ, FLAT, "I don't drink milk")
    assert world.say(RAJ, FLAT, "Raj drinks milk now") == "Removed: Raj never shares milk."
    world.say(RAJ, FLAT, "I don't drink milk")
    asked = world.say(SAM, FLAT, "Raj drinks milk now")
    assert asked == 'Remove this rule: Raj never shares milk? Say "yes" to confirm.'
    assert world.say(SAM, FLAT, "yes") == "Sam removed a rule: Raj never shares milk."
    assert world.say(SAM, FLAT, "Raj drinks milk now") == "There's no rule like that here."


def test_everywhere_rule_skips_without_saying_why() -> None:
    # F16
    world = World()
    two_groups(world)
    world.say(RAJ, None, "I don't drink milkshake")
    shown = world.say(YOU, GOA, "milkshake 300, split all")
    assert "Raj skipped: milkshake\n" in shown


def test_group_balances_in_the_group() -> None:
    # I3
    world = World()
    two_groups(world)
    world.say(YOU, FLAT, "rent 3000, split all")
    world.say(YOU, FLAT, "yes")
    world.say(SAM, GOA, "help")
    balances = world.say(SAM, FLAT, "balances")
    assert balances == "Sam owes Alex ₹1,000.00\nRaj owes Alex ₹1,000.00"


def test_overall_balances_in_a_personal_chat() -> None:
    # I1, I2: total per person, and with one person the breakdown by context
    world = World()
    two_groups(world)
    world.say(YOU, FLAT, "rent 3000, split all")
    world.say(YOU, FLAT, "yes")
    world.say(RAJ, GOA, "boat 900, split all")
    world.say(RAJ, GOA, "yes")
    overall = world.say(YOU, None, "what do I owe")
    assert overall == "Sam owes you ₹1,000.00\nRaj owes you ₹700.00"
    with_raj = world.say(YOU, None, "what do I owe Raj")
    assert with_raj == (
        "Raj owes you ₹700.00\n  Flat 4B: owes you ₹1,000.00\n  Goa trip: you owe ₹300.00"
    )


def test_asking_in_a_group_shows_only_that_group_and_dms_the_rest() -> None:
    # I4
    world = World()
    two_groups(world)
    world.say(YOU, FLAT, "rent 3000, split all")
    world.say(YOU, FLAT, "yes")
    world.say(RAJ, GOA, "boat 900, split all")
    world.say(RAJ, GOA, "yes")
    world.say(YOU, GOA, "what do I owe Raj")
    assert world.in_chat(GOA) == "Here, you owe Raj ₹300.00.\nI sent you the rest in a DM."
    assert world.in_chat(None, YOU).startswith("Raj owes you ₹700.00")
    world.say(YOU, GOA, "balances in Flat 4B")
    assert world.in_chat(GOA) == "I sent you the rest in a DM."
    assert "Sam owes Alex" in world.in_chat(None, YOU)


def test_no_dm_for_someone_who_never_messaged_the_bot() -> None:
    world = World()
    world.say(YOU, FLAT, "help")
    world.say(SAM, FLAT, "join")
    assert world.say(SAM, FLAT, "what do I owe") == "Everyone is settled up here."


def test_rules_about_you_include_other_peoples_notes() -> None:
    # SPEC 6.2: every rule with you as subject, scope and author included
    world = World()
    flat(world, YOU, SAM)
    world.say(SAM, None, "Alex never shares dessert")
    world.say(SAM, None, "yes")
    assert "Alex never shares dessert (Sam's notes, set by Sam)" in world.say(
        YOU, None, "what rules are about me"
    )


def aliases(world: World) -> dict[str, str]:
    with world.repository.unit_of_work() as uow:
        group = uow.groups.by_channel_ref(world.message(YOU, FLAT).conversation)
        assert group is not None
        return {a.raw_name: a.item_key for a in uow.aliases.for_scope(GroupScope(group.id))}


def test_a_fixed_match_is_remembered_for_the_group() -> None:
    # F12: the alias now points at the item named
    world = World(canonical=FakeCanonicalizer({"2% MLK GAL": "milk"}))
    flat(world, YOU, SAM)
    world.say(YOU, FLAT, "milk 100, split all")
    world.say(YOU, FLAT, "yes")
    world.say(YOU, FLAT, image=receipt("grocery_taxed_mix"))
    assert aliases(world)["2% mlk gal"] == "milk"
    world.say(YOU, FLAT, "that's not milk, it's yogurt")
    assert aliases(world)["2% mlk gal"] == "yogurt"
