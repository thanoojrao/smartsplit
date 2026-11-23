"""After saving: messages to people's own chats, batching, invites, and idle drafts
(D6-D9, C13, SPEC 10.5, 10.8)."""

from datetime import timedelta

from smartsplit.domain.enums import DraftState
from tests.integration.world import FLAT, PRIYA, RAJ, SAM, YOU, World, flat, receipt


def friends(world: World) -> None:
    for person in (YOU, SAM, RAJ):
        world.say(person, None, "help")
    world.say(YOU, None, "add Sam +919876500002")
    world.say(YOU, None, "add Raj +919876500003")


def test_a_personal_split_tells_the_others_with_their_overall_balance() -> None:
    # D6
    world = World()
    friends(world)
    world.say(YOU, None, "split with Sam and Raj", image=receipt("restaurant_tip"))
    world.say(YOU, None, "yes")
    assert world.tick() != ""
    to_sam = world.in_chat(None, SAM)
    assert to_sam == (
        "Thanoo added Toit (21 Nov): your share is ₹682.33.\n"
        "Overall you owe Thanoo ₹682.33.\n"
        'Reply "ok", "details", "not mine", or tell me what to fix.'
    )
    assert "your share is ₹682.33" in world.in_chat(None, RAJ)
    assert world.tick() == ""


def test_group_bills_send_no_personal_messages() -> None:
    # C15
    world = World()
    flat(world, YOU, SAM)
    world.say(YOU, FLAT, "rent 3000, split all")
    world.say(YOU, FLAT, "yes")
    assert world.tick() == ""


def test_never_used_the_bot_gets_an_invite_once_and_messages_wait() -> None:
    # D7, D8
    world = World()
    world.say(YOU, None, "help")
    world.say(YOU, None, "add Priya +919876500004")
    world.say(YOU, None, "chai 200 with Priya")
    saved = world.say(YOU, None, "yes")
    assert "Priya hasn't used SmartSplit yet. Forward this to them:" in saved
    world.say(YOU, None, "lunch 400 with Priya")
    assert "Forward this" not in world.say(YOU, None, "yes")
    assert world.tick() == ""
    welcome = world.say(PRIYA, None, "hi")
    assert "Waiting for you:\nYou owe Thanoo ₹300.00" in welcome
    batch = world.tick()
    assert batch.startswith("Thanoo added 2 bills:\n1. chai")
    assert "2. lunch" in batch


def test_several_bills_in_one_tick_become_one_numbered_message() -> None:
    # D9: and "details 2" means the second one listed
    world = World()
    friends(world)
    for bill in ("chai 100 with Sam", "lunch 300 with Sam", "taxi 500 with Sam"):
        world.say(YOU, None, bill)
        world.say(YOU, None, "yes")
    message = world.tick()
    assert message.startswith("Thanoo added 3 bills:")
    assert "Overall you owe Thanoo ₹450.00." in message
    assert "lunch" in world.say(SAM, None, "details 2")


def test_stop_holds_messages_and_start_releases_them() -> None:
    # SPEC 10.8 opt-out
    world = World()
    friends(world)
    assert world.say(SAM, None, "stop") == 'OK, I won\'t message you. Say "start" to undo.'
    world.say(YOU, None, "chai 100 with Sam")
    world.say(YOU, None, "yes")
    assert world.tick() == ""
    assert world.say(SAM, None, "start") == "OK, you'll hear from me again."
    assert "chai" in world.tick()


def test_daily_cap_holds_the_rest_until_tomorrow() -> None:
    world = World()
    friends(world)
    capped = World(
        clock=world.clock,
        repository=world.repository,
        settings=type(world.settings)(max_notifications_per_day=1),
    )
    capped.say(YOU, None, "chai 100 with Sam")
    capped.say(YOU, None, "yes")
    capped.tick()
    capped.say(YOU, None, "lunch 300 with Sam")
    capped.say(YOU, None, "yes")
    assert capped.tick() == ""
    capped.clock.advance(timedelta(days=1))
    assert "lunch" in capped.tick()


def test_an_idle_draft_is_reminded_once_then_expires() -> None:
    # C13
    world = World()
    flat(world, YOU, SAM)
    world.say(YOU, FLAT, "rent 3000, split all")
    world.clock.advance(timedelta(hours=23))
    assert world.tick() == ""
    world.clock.advance(timedelta(hours=2))
    assert world.tick() == (
        'Still waiting on the rent bill. Thanoo, say "yes" to save it, or "cancel".'
    )
    assert {m.conversation.ref for m in world.last} == {FLAT}
    world.clock.advance(timedelta(hours=2))
    assert world.tick() == ""
    world.clock.advance(timedelta(days=2))
    assert world.tick() == "The rent bill expired. Nothing was saved."
    assert world.say(YOU, FLAT, "yes") == "There's nothing to save right now."


def test_activity_restarts_the_clock() -> None:
    world = World()
    flat(world, YOU, SAM)
    world.say(YOU, FLAT, "rent 3000, split all")
    world.clock.advance(timedelta(hours=25))
    world.tick()
    world.clock.advance(timedelta(hours=1))
    world.say(YOU, FLAT, "line 1 is 3100")
    world.clock.advance(timedelta(days=2, hours=1))
    assert "Still waiting" in world.tick()


def test_expiry_starts_the_next_receipt() -> None:
    world = World()
    flat(world, YOU, SAM)
    world.say(YOU, FLAT, "rent 3000, split all")
    world.say(SAM, FLAT, image=receipt("restaurant_tip"))
    world.clock.advance(timedelta(days=3, hours=1))
    expired = world.tick()
    assert "The rent bill expired." in expired
    assert "Toit, ₹2,047.00, paid by Sam." in expired


def drafts(world: World) -> list[DraftState]:
    with world.repository.unit_of_work() as uow:
        key = world.message(YOU, FLAT).conversation
        return [d.state for d in uow.drafts.for_conversation(key, list(DraftState))]
