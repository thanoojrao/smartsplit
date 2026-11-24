"""The same conversations on real Postgres: drafts, prompts, photo reads and the transcript
round-trip through the database, and two messages for one chat at once are handled one after
the other (K6, G7)."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import Engine

from smartsplit.adapters.db.repository import SqlRepository
from smartsplit.adapters.fakes.agent import call, first_handle, say
from smartsplit.domain.messages import ContactAttachment
from smartsplit.ports.agent import AgentRequest, ModelStep
from tests.integration.world import FLAT, PRIYA, RAJ, SAM, YOU, World, calling, flat, receipt

pytestmark = pytest.mark.db

YES = calling("confirm_pending", action="@A")


def test_a_tour_of_drafts_questions_and_pending_actions(clean_pg: Engine) -> None:
    world = World(repository=SqlRepository(clean_pg))
    flat(world, YOU, SAM)
    world.say(RAJ, None, "hi")
    world.say(RAJ, FLAT, "join", call("join_group"))
    world.say(
        SAM,
        FLAT,
        "skip beer",
        call("add_rule", subject="me", item="beer pitcher", kind="soft_exclude"),
    )
    world.say(
        YOU, FLAT, "Raj no chips", calling("add_rule", subject="@Raj", item="chips", kind="exclude")
    )
    assert world.say(YOU, FLAT, "yes", YES) == "Alex saved a rule: Raj never shares chips."
    world.say(YOU, FLAT, "split", call("start_receipt"), image=receipt("restaurant_tip"))
    world.say(SAM, FLAT, "no beer", calling("answer_question", question="@Q", included=False))
    assert "Saved: Toit" in world.say(YOU, FLAT, "yes", calling("confirm_draft", draft="@D"))
    warned = world.say(SAM, FLAT, "split", call("start_receipt"), image=receipt("restaurant_tip"))
    assert "Looks like Alex already added this" in warned
    world.say(SAM, FLAT, "drop it", calling("cancel_draft", draft="@D"))
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
    )
    shown = world.say(
        YOU,
        None,
        None,
        call("add_person", name="Meera", use_contact=True),
        calling("edit_draft", draft="@D", change={"type": "AddPeople", "people": ["@Meera"]}),
        contact=ContactAttachment("Meera", "+919876500009"),
    )
    assert "Meera: ₹300.00" in shown
    added = world.say(
        SAM,
        FLAT,
        None,
        call("add_person", name="Priya", use_contact=True),
        contact=ContactAttachment("Priya", PRIYA.phone),
    )
    assert added == "Sam added Priya to Flat 4B."
    restarted = World(repository=world.repository, clock=world.clock, images=world.images)
    restarted.say(YOU, None, "where were we?", say(""))
    assert "names not found yet" not in restarted.turn_input
    assert 'D1 "dinner"' in restarted.turn_input


def test_two_confirms_at_once_save_one_bill(clean_pg: Engine) -> None:
    # K6: the conversation lock serializes them; the second finds the bill already saved
    world = World(repository=SqlRepository(clean_pg))
    flat(world, YOU, SAM)
    world.say(YOU, FLAT, "taxi 600", call("add_manual_bill", description="taxi", amount="600"))

    def confirm(request: AgentRequest) -> ModelStep:
        return (
            call("confirm_draft", draft=first_handle(request, "D"))
            if "D1" in request.turn_input
            else say("")
        )

    world.agent.queue(confirm, confirm)
    confirms = [world.message(YOU, FLAT, "yes", message_id=f"c{n}") for n in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(world.bot.handle, confirms))
    texts = sorted("\n".join(m.text for m in o.replies) for o in outcomes)
    assert sum(t.startswith("Saved: taxi") for t in texts) == 1
    assert world.say(SAM, FLAT, "balances", call("get_balances")) == "Sam owes Alex ₹300.00"


def test_money_and_the_outbox_on_postgres(clean_pg: Engine) -> None:
    world = World(repository=SqlRepository(clean_pg))
    flat(world, YOU, SAM)
    world.say(SAM, None, "add Alex", call("add_person", name="Alex", phone=YOU.phone))
    for what in ("lunch", "dinner"):
        world.say(
            SAM,
            None,
            what,
            calling("add_manual_bill", description=what, amount="400", people=["@Alex"]),
        )
        world.say(SAM, None, "yes", calling("confirm_draft", draft="@D", keep_duplicate=True))
    assert world.tick().startswith("Sam added 2 bills:")
    world.say(
        YOU,
        None,
        "not mine, the second",
        calling("change_bill", bill="B2", change={"type": "NotMine"}),
    )
    assert world.say(YOU, None, "yes", YES).startswith("Changed dinner.")
    world.say(
        YOU,
        None,
        "paid Sam 200",
        calling("record_payment", from_person="me", to_person="@Sam", amount="200"),
    )
    assert world.say(YOU, None, "yes", YES).startswith("Recorded.")
    world.say(SAM, None, "not received", call("not_received"))
    assert world.say(SAM, None, "yes", YES).startswith("Done, that payment is reversed.")
    world.say(YOU, FLAT, "rent", call("add_manual_bill", description="rent", amount="900"))
    world.say(YOU, FLAT, "yes", calling("confirm_draft", draft="@D"))
    world.say(YOU, None, "square up", calling("square_up", with_person="@Sam"))
    assert world.say(YOU, None, "yes", YES).startswith("Squared up.")
    assert "Squared up" in world.transcript(None, YOU)[-1].text
