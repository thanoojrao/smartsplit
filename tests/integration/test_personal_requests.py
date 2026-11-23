"""Reminders, history and opt-out (J1-J4; the daily cap, J5, is in test_notifications)."""

from datetime import timedelta

from tests.integration.world import FLAT, RAJ, YOU, World, flat


def raj_owes_you(world: World) -> None:
    flat(world, YOU, RAJ)
    world.say(YOU, FLAT, "rent 3000, split all")
    world.say(YOU, FLAT, "yes")


def test_remind_sends_a_nudge_at_most_once_a_day() -> None:
    # J1
    world = World()
    raj_owes_you(world)
    assert world.say(YOU, FLAT, "remind Raj") == "OK, I'll remind Raj."
    world.tick()
    assert world.in_chat(None, RAJ) == (
        "A friendly nudge from Alex.\nOverall you owe Alex ₹1,500.00."
    )
    assert world.say(YOU, FLAT, "remind Raj") == "I already reminded Raj today."
    world.clock.advance(timedelta(hours=25))
    assert world.say(YOU, FLAT, "remind Raj") == "OK, I'll remind Raj."


def test_no_reminder_to_someone_who_stopped_or_owes_nothing() -> None:
    world = World()
    raj_owes_you(world)
    world.say(RAJ, None, "stop")
    assert world.say(YOU, FLAT, "remind Raj") == (
        "Raj doesn't get messages from me, so I can't remind them."
    )
    assert world.say(RAJ, FLAT, "remind Alex") == "I can only remind people who owe you overall."


def test_what_did_i_spend_this_month() -> None:
    # J2: by purchase date; edits count once, deletes not at all
    world = World()
    raj_owes_you(world)
    world.say(YOU, FLAT, "chai 200, split all")
    world.say(YOU, FLAT, "yes")
    world.say(YOU, FLAT, "old dinner 800, split all")
    world.say(YOU, FLAT, "yes")
    world.say(YOU, FLAT, "delete last bill")
    world.say(YOU, FLAT, "yes")
    spent = world.say(YOU, None, "what did I spend this month")
    assert spent == (
        "You spent ₹1,600.00 this month.\n1. rent (21 Nov): ₹1,500.00\n2. chai (21 Nov): ₹100.00"
    )
    assert world.say(YOU, None, "what did I spend last month") == "You spent ₹0.00 last month."


def test_last_bills_and_history_asked_in_a_group_goes_to_a_dm() -> None:
    # J3
    world = World()
    raj_owes_you(world)
    world.say(YOU, FLAT, "chai 200, split all")
    world.say(YOU, FLAT, "yes")
    world.say(YOU, FLAT, "show last 5 bills")
    assert world.in_chat(FLAT) == "I sent you the rest in a DM."
    assert world.in_chat(None, YOU) == (
        "Your last 2 bills:\n1. chai (21 Nov): ₹100.00\n2. rent (21 Nov): ₹1,500.00"
    )
    assert world.say(YOU, None, "details 2").startswith("rent (21 Nov), paid by Alex")


def test_stop_and_start() -> None:
    # J4
    world = World()
    raj_owes_you(world)
    assert world.say(RAJ, None, "stop") == 'OK, I won\'t message you. Say "start" to undo.'
    assert world.say(RAJ, None, "start") == "OK, you'll hear from me again."
    assert world.say(YOU, FLAT, "remind Raj") == "OK, I'll remind Raj."


def test_last_month_counts_bills_bought_last_month() -> None:
    world = World()
    raj_owes_you(world)
    world.clock.advance(timedelta(days=15))
    world.say(YOU, FLAT, "chai 200, split all")
    world.say(YOU, FLAT, "yes")
    assert world.say(YOU, None, "what did I spend last month") == (
        "You spent ₹1,500.00 last month.\n1. rent (21 Nov): ₹1,500.00"
    )
    assert world.say(YOU, None, "what did I spend this month").startswith(
        "You spent ₹100.00 this month."
    )
