"""The same conversations on real Postgres: every prompt and draft round-trips through the
database, and two messages for one chat at once are handled one after the other (K6, G7)."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import Engine

from smartsplit.adapters.db.repository import SqlRepository
from smartsplit.domain.messages import ContactAttachment
from tests.integration.world import FLAT, PRIYA, RAJ, SAM, YOU, World, flat, receipt

pytestmark = pytest.mark.db


def test_a_tour_of_every_prompt(clean_pg: Engine) -> None:
    world = World(repository=SqlRepository(clean_pg))
    flat(world, YOU, SAM)
    assert "join splits here" in world.say(RAJ, FLAT, "balances")
    world.say(RAJ, FLAT, "yes")
    world.say(SAM, FLAT, "I usually don't drink beer pitcher")
    world.say(YOU, FLAT, "Raj doesn't eat chips")
    assert world.say(YOU, FLAT, "yes") == "Thanoo saved a rule: Raj never shares chips."
    world.say(YOU, FLAT, image=receipt("restaurant_tip"))
    world.say(SAM, FLAT, "1 no")
    assert "Saved: Toit" in world.say(YOU, FLAT, "yes")
    assert "Looks like Thanoo already added this" in world.say(
        SAM, FLAT, image=receipt("restaurant_tip")
    )
    world.say(SAM, FLAT, "no")
    world.say(YOU, FLAT, image=receipt("total_mismatch"))
    world.say(YOU, FLAT, "yes")
    assert "Saved: Kirana, ₹570.00." in world.say(YOU, FLAT, "yes")
    assert world.say(YOU, None, "dinner 900 with Meera").startswith("I don't know Meera")
    assert "Meera: ₹450.00" in world.say(YOU, None, "+919876500009")
    world.say(YOU, None, "cancel")
    asked = world.say(YOU, None, image=receipt("milk_discount_linked"))
    assert asked.startswith("Who's this with?\n1. Flat 4B")
    assert "More, ₹272.00" in world.say(YOU, None, "1")
    added = world.say(SAM, FLAT, "add Priya", contact=ContactAttachment("Priya", PRIYA.phone))
    assert added == "Sam added Priya to Flat 4B."


def test_two_confirms_at_once_save_one_bill(clean_pg: Engine) -> None:
    # K6: the conversation lock serializes them; the second finds nothing left to save
    world = World(repository=SqlRepository(clean_pg))
    flat(world, YOU, SAM)
    world.say(YOU, FLAT, "taxi 600, split all")
    confirms = [world.message(YOU, FLAT, "yes", message_id=f"c{n}") for n in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = sorted("\n".join(m.text for m in r) for r in pool.map(world.bot.handle, confirms))
    assert replies[0].startswith("Saved: taxi")
    assert replies[1] == "There's nothing to save right now."
    assert world.say(SAM, FLAT, "balances") == "Sam owes Thanoo ₹300.00"


def test_a_tour_of_m8_on_postgres(clean_pg: Engine) -> None:
    # Payments, square-up, bill changes and the outbox through real storage
    world = World(repository=SqlRepository(clean_pg))
    flat(world, YOU, SAM)
    world.say(SAM, None, "add Thanoo +919876500001")
    world.say(SAM, None, "lunch 400 with Thanoo")
    world.say(SAM, None, "yes")
    world.say(SAM, None, "lunch 600 with Thanoo")
    world.say(SAM, None, "yes")
    assert world.tick().startswith("Sam added 2 bills:")
    assert "Change lunch" in world.say(YOU, None, "not mine 2")
    assert world.say(YOU, None, "yes").startswith("Changed lunch.")
    world.say(YOU, FLAT, "rent 900, split all\x00")
    world.say(YOU, FLAT, "yes")
    assert "Record: you paid Sam ₹200.00" in world.say(YOU, None, "paid Sam 200")
    assert world.say(YOU, None, "yes").startswith("Recorded.")
    assert world.say(SAM, None, "not received").startswith("Undid the ₹200.00 payment")
    assert world.say(YOU, None, "square up with Sam").endswith('Say "yes" to confirm.')
    assert world.say(YOU, None, "yes").startswith("Squared up.")
    assert world.say(YOU, FLAT, "remind Sam") == "OK, I'll remind Sam."
    assert world.say(YOU, None, "delete last bill") == "I can't find that bill."
    assert world.say(YOU, FLAT, "delete last bill").startswith("Delete rent")
    assert world.say(YOU, FLAT, "yes").startswith("Deleted rent.")
    world.tick()
    assert "show last" not in world.say(YOU, None, "show last 5 bills")
