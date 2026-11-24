"""Rules, balances, history, reminders and privacy (use cases F1-F16, I1-I4, J1-J5, L14)."""

from smartsplit.adapters.fakes.agent import call
from smartsplit.adapters.fakes.llm import FakeCanonicalizer
from smartsplit.domain.values import Everywhere, GroupScope, NotesScope
from smartsplit.ports.agent import ToolResult
from tests.integration.world import FLAT, RAJ, SAM, YOU, World, calling, flat, receipt


def result(world: World) -> ToolResult:
    return world.agent.requests[-1].history[-1][1][0]


def rule_scopes(world: World, subject: str) -> list[object]:
    with world.repository.unit_of_work() as uow:
        return [r.scope for r in uow.rules.for_subjects([subject])]


def test_a_rule_about_yourself_in_your_own_chat_applies_everywhere_at_once() -> None:
    # F1
    world = World()
    world.say(RAJ, None, "hi")
    noted = world.say(
        RAJ, None, "I don't drink milk", call("add_rule", subject="me", item="milk", kind="exclude")
    )
    assert noted == "Noted: Raj never shares milk."
    assert rule_scopes(world, world.person(RAJ).id) == [Everywhere()]


def test_the_same_said_in_a_group_is_a_group_rule() -> None:
    # F2, F3
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.say(
        RAJ, FLAT, "I don't drink milk", call("add_rule", subject="me", item="milk", kind="exclude")
    )
    scopes = rule_scopes(world, world.person(RAJ).id)
    assert len(scopes) == 1 and isinstance(scopes[0], GroupScope)


def test_a_rule_about_someone_else_waits_for_a_yes() -> None:
    # F3, F4, SPEC 6.2: "protein powder is Sam's" said by Alex is restated first
    world = World()
    flat(world, YOU, SAM)
    asked = world.say(
        YOU,
        FLAT,
        "protein is Sam's",
        calling("add_rule", subject="@Sam", item="protein powder", kind="only"),
    )
    assert asked == "Save this rule: protein powder is Sam's?\nWaiting for Alex to say yes."
    assert rule_scopes(world, world.person(SAM).id) == []
    saved = world.say(YOU, FLAT, "yes", calling("confirm_pending", action="@A"))
    assert saved == "Alex saved a rule: protein powder is Sam's."


def test_your_notes_apply_only_to_your_personal_splits() -> None:
    # F4, F8
    world = World()
    for someone in (YOU, SAM):
        world.say(someone, None, "hi")
    world.say(YOU, None, "add Sam", call("add_person", name="Sam", phone=SAM.phone))
    world.say(
        YOU,
        None,
        "Sam never shares dessert",
        calling("add_rule", subject="@Sam", item="dessert", kind="exclude"),
    )
    world.say(YOU, None, "yes", calling("confirm_pending", action="@A"))
    assert rule_scopes(world, world.person(SAM).id) == [NotesScope(world.person(YOU).id)]


def test_rules_shape_the_split_and_the_summary_says_who_was_skipped() -> None:
    # E2, F16: someone's everywhere rule shows only that they were skipped
    world = World(canonical=FakeCanonicalizer({"2% MLK GAL": "milk"}))
    flat(world, YOU, SAM, RAJ)
    world.say(RAJ, None, "no milk", call("add_rule", subject="me", item="milk", kind="exclude"))
    summary = world.say(
        YOU, FLAT, "split", call("start_receipt"), image=receipt("grocery_taxed_mix")
    )
    assert "Raj skipped: 2% MLK GAL" in summary
    assert "(group rule)" not in summary.split("Raj skipped: 2% MLK GAL")[1].split("\n")[0]


def test_drinks_milk_now_deletes_the_rule() -> None:
    # F9, F15
    world = World()
    world.say(RAJ, None, "hi")
    world.say(RAJ, None, "no milk", call("add_rule", subject="me", item="milk", kind="exclude"))
    removed = world.say(
        RAJ, None, "I drink milk now", call("delete_rule", subject="me", item="milk")
    )
    assert removed == "Removed: Raj never shares milk."
    world.say(RAJ, None, "again", call("delete_rule", subject="me", item="milk"))
    assert result(world).error == "There's no rule like that here."


def test_that_is_not_milk_fixes_the_match_here() -> None:
    # F11, F12
    world = World()
    flat(world, YOU, SAM)
    world.say(YOU, FLAT, "milk", call("add_rule", subject="me", item="milk", kind="soft_exclude"))
    world.say(YOU, FLAT, "split", call("start_receipt"), image=receipt("milk_discount_linked"))
    fixed = world.say(
        YOU,
        FLAT,
        "that's not milk",
        calling(
            "edit_draft",
            draft="@D",
            change={"type": "NotThisItem", "line": "L1", "item_said": "oat drink"},
        ),
    )
    assert "is Alex in?" not in fixed


def test_listing_rules_in_a_group_shows_only_that_groups_rules() -> None:
    # F13, F14
    world = World()
    flat(world, YOU, SAM)
    world.say(SAM, None, "no milk", call("add_rule", subject="me", item="milk", kind="exclude"))
    world.say(
        SAM, FLAT, "no chips here", call("add_rule", subject="me", item="chips", kind="exclude")
    )
    shown = world.say(SAM, FLAT, "my rules?", call("list_rules", about="me"))
    assert "chips" in world.in_chat(FLAT) and "milk" not in world.in_chat(FLAT)
    assert "I sent you the full list in a DM." in shown
    assert "milk" in world.in_chat(None, SAM)
    world.say(SAM, None, "my rules?", call("list_rules", about="me"))
    assert "Sam never shares milk (everywhere, set by Sam)" in world.in_chat(None, SAM)


def bill(world: World, chat: str, amount: str = "900") -> None:
    world.say(YOU, chat, "bill", call("add_manual_bill", description="groceries", amount=amount))
    world.say(YOU, chat, "yes", calling("confirm_draft", draft="@D"))


def test_balances_in_a_personal_chat_and_with_one_person() -> None:
    # I1, I2
    world = World()
    flat(world, YOU, SAM, RAJ)
    bill(world, FLAT)
    overall = world.say(YOU, None, "what do I get?", call("get_balances", overall=True))
    assert "Sam owes you ₹300.00" in overall and "Raj owes you ₹300.00" in overall
    with_sam = world.say(YOU, None, "and Sam?", calling("get_balances", with_person="@Sam"))
    assert with_sam == "Sam owes you ₹300.00\n  Flat 4B: owes you ₹300.00"


def test_group_balances_stay_in_the_group_and_overall_goes_privately() -> None:
    # I3, I4, L14: the model never sees other contexts in a group turn
    world = World()
    flat(world, YOU, SAM, RAJ)
    bill(world, FLAT)
    world.say(SAM, None, "hi")
    world.say(YOU, "Goa trip", "hi")
    world.say(SAM, "Goa trip", "join", call("join_group"))
    bill(world, "Goa trip", "200")
    group = world.say(
        YOU,
        FLAT,
        "balances here, and what do I get overall?",
        call("get_balances"),
        call("get_balances", overall=True),
    )
    assert "Sam owes Alex ₹300.00" in world.in_chat(FLAT)
    assert "Goa" not in world.in_chat(FLAT)
    assert "I sent you that in a DM." in group
    assert "Sam owes you ₹400.00" in world.in_chat(None, YOU)
    second = world.agent.requests[-1].history[-1][1][-1]
    assert second.data == {"sent_privately": True} and second.shown == ("I sent you that in a DM.",)
    assert "Goa" not in world.turn_input


def test_this_group_and_overall_in_one_call_shows_both() -> None:
    # L14, seen live: the group's balances in the group, the overall answer privately
    world = World()
    flat(world, YOU, SAM)
    bill(world, FLAT)
    world.say(
        YOU,
        FLAT,
        "flat balances, and what am I owed overall?",
        calling("get_balances", group="@G", overall=True),
    )
    assert "Sam owes Alex" in world.in_chat(FLAT)
    assert "I sent you that in a DM." in world.in_chat(FLAT)
    assert "Sam owes you" in world.in_chat(None, YOU)


def test_history_this_month_goes_privately_from_a_group() -> None:
    # J2, J3
    world = World()
    flat(world, YOU, SAM)
    bill(world, FLAT)
    world.say(YOU, FLAT, "what did I spend?", call("list_bills", period="this_month"))
    assert "You spent ₹450.00 this month." in world.in_chat(None, YOU)
    listed = world.say(YOU, FLAT, "last bills", call("list_bills", last_n=5))
    assert listed.startswith("1 bills, newest first:\n1. groceries (21 Nov): ₹450.00")
    assert result(world).data == {"bills": ["B1"]}


def test_remind_once_a_day_only_people_who_owe_you() -> None:
    # J1
    world = World()
    flat(world, YOU, SAM)
    bill(world, FLAT)
    world.say(YOU, None, "remind Sam", calling("remind", person="@Sam"))
    assert result(world).ok
    assert "A friendly nudge from Alex." in world.tick()
    world.say(YOU, None, "remind Sam", calling("remind", person="@Sam"))
    assert result(world).error == "I already reminded Sam today."
    world.say(SAM, None, "remind Alex", calling("remind", person="@Alex"))
    assert result(world).error == "I can only remind people who owe you overall."


def test_stop_holds_messages_and_start_lets_them_through() -> None:
    # J4
    world = World()
    flat(world, YOU, SAM)
    bill(world, FLAT)
    world.say(SAM, None, "stop", call("set_notifications", on=False))
    world.say(YOU, None, "remind Sam", calling("remind", person="@Sam"))
    assert result(world).error == "Sam doesn't get messages from me, so I can't remind them."
    world.say(SAM, None, "start", call("set_notifications", on=True))
    assert world.person(SAM).notifications_enabled


def test_daily_cap_holds_extra_messages() -> None:
    # J5
    world = World()
    for someone in (YOU, SAM):
        world.say(someone, None, "hi")
    world.say(YOU, None, "add Sam", call("add_person", name="Sam", phone=SAM.phone))
    sam, sent = world.person(SAM).id, 0
    for n in range(world.settings.max_notifications_per_day + 2):
        world.say(
            YOU,
            None,
            f"bill {n}",
            calling(
                "add_manual_bill", description=f"bill {n}", amount=str(10 + n), people=["@Sam"]
            ),
        )
        world.say(YOU, None, "yes", calling("confirm_draft", draft="@D"))
        world.tick()
        sent += sum(1 for m in world.last if m.recipient_id == sam)
    assert sent == world.settings.max_notifications_per_day
