"""Opt-in: more conversations with the real models, phrased the way people type (use cases C,
D, F, H, I, J, L). Same harness and checks as test_live_conversation.py; checks are on state."""

from datetime import timedelta

import pytest

from smartsplit.adapters.fakes.agent import call
from smartsplit.domain.enums import DraftState
from tests.integration.world import FLAT, RAJ, SAM, YOU, Someone
from tests.live.session import Live, live, photo

pytestmark = [pytest.mark.live, pytest.mark.enable_socket]

GOA = "Goa trip"


def rules_about(s: Live, who: Someone) -> list[str]:
    person_id = s.world.person(who).id
    with s.world.repository.unit_of_work() as uow:
        return [r.item_key for r in uow.rules.for_subjects([person_id])]


def test_messy_typing_still_makes_the_right_bill(request: pytest.FixtureRequest) -> None:
    s = live(request, YOU, SAM, RAJ)
    s.say(YOU, None, "dinnr 1.2k w sam n raj")
    assert s.reviewing(None, YOU) == [120000]
    s.say(YOU, None, "ya save")
    assert [b.total_cents for b in s.bills(YOU)] == [120000]
    assert s.owes(RAJ, YOU) == 40000


def test_a_rule_said_in_chat_is_used_then_dropped(request: pytest.FixtureRequest) -> None:
    # F2, F13, F9, E2: Raj's group rule keeps him off the cappuccinos
    s = live(request, YOU, SAM, RAJ)
    s.say(RAJ, FLAT, "pls never put me on cappuccino, i dont drink coffee")
    assert rules_about(s, RAJ) == ["cappuccino"]
    s.say(YOU, FLAT, "split this", image=photo())
    raj = s.world.person(RAJ).id
    draft = next(d for d in s.world.drafts(FLAT) if d.state is DraftState.REVIEWING)
    assert raj in draft.participants
    listed = s.say(RAJ, None, "what rules do u have on me")
    assert "cappuccino" in listed.casefold()
    s.say(RAJ, FLAT, "ok i drink coffee now lol")
    assert rules_about(s, RAJ) == []


def test_not_there_for_a_saved_bill(request: pytest.FixtureRequest) -> None:
    # H2/H1: Raj takes himself off a saved bill; it's re-split once he says yes
    s = live(request, YOU, SAM, RAJ)
    s.say(YOU, FLAT, "dinner 1500 split all")
    s.say(YOU, FLAT, "yes")
    assert s.owes(RAJ, YOU) == 50000
    s.say(RAJ, FLAT, "wait i wasnt even at that dinner")
    assert s.owes(RAJ, YOU) == 50000
    s.say(RAJ, FLAT, "yes")
    assert s.owes(RAJ, YOU) == 0
    assert s.owes(SAM, YOU) == 75000


def test_overpaying_then_undoing_it(request: pytest.FixtureRequest) -> None:
    # I9, I10
    s = live(request, YOU, SAM)
    s.say(YOU, None, "lunch 600 with sam")
    s.say(YOU, None, "yes")
    assert s.owes(SAM, YOU) == 30000
    s.say(SAM, None, "sent alex 1000 on upi")
    assert s.owes(SAM, YOU) == 30000
    s.say(SAM, None, "yes")
    assert s.owes(SAM, YOU) == -70000
    s.say(SAM, None, "oops that was wrong, undo it")
    assert s.owes(SAM, YOU) == -70000
    s.say(SAM, None, "yes")
    assert s.owes(SAM, YOU) == 30000


def test_a_payment_that_never_arrived(request: pytest.FixtureRequest) -> None:
    # I8: the receiver says it never came; reversed on their yes
    s = live(request, YOU, SAM)
    s.say(YOU, None, "lunch 600 with sam")
    s.say(YOU, None, "yes")
    s.say(SAM, None, "paid alex 300")
    s.say(SAM, None, "yes")
    assert s.owes(SAM, YOU) == 0
    s.world.tick()  # Alex gets "Sam paid you ₹300" in his own chat
    s.say(YOU, None, "sam's 300 never came through")
    s.say(YOU, None, "yes")
    assert s.owes(SAM, YOU) == 30000


def test_squaring_up_across_two_groups(request: pytest.FixtureRequest) -> None:
    # I11: Sam owes Alex in Flat 4B, Alex owes Sam on the trip; no money moves
    s = live(request, YOU, SAM)
    s.switch.current = s.world.agent
    s.world.say(YOU, GOA, "hi")
    s.world.say(SAM, GOA, "join", call("join_group"))
    s.go_live()
    s.say(YOU, FLAT, "wifi 600 split all")
    s.say(YOU, FLAT, "yes")
    s.say(SAM, GOA, "cab 600 split all")
    s.say(SAM, GOA, "yes")
    assert s.owes(SAM, YOU) == 0
    assert s.group_balance(FLAT, YOU) == 30000
    s.say(YOU, None, "can we just square up me and sam")
    s.say(YOU, None, "yes")
    assert s.group_balance(FLAT, YOU) == 0
    assert s.group_balance(GOA, YOU) == 0


def test_fixing_a_line_then_cancelling(request: pytest.FixtureRequest) -> None:
    # C6, C12: anyone in the group may cancel
    s = live(request, YOU, SAM, RAJ)
    s.say(YOU, FLAT, "split this pls", image=photo())
    s.say(YOU, FLAT, "the sandwich was 250 not 220")
    draft = next(d for d in s.world.drafts(FLAT) if d.state is DraftState.REVIEWING)
    assert sorted(line.amount_cents for line in draft.lines) == [25000, 36000]
    s.say(SAM, FLAT, "nah cancel this one, wrong receipt")
    assert s.reviewing(FLAT) == []
    assert s.bills(YOU) == []


def test_group_balances_stay_in_the_group(request: pytest.FixtureRequest) -> None:
    # L14, I3, I4: the overall answer goes privately
    s = live(request, YOU, SAM)
    s.say(YOU, FLAT, "rent 20000 split all")
    s.say(YOU, FLAT, "yes")
    s.say(YOU, None, "coffee 400 with sam")
    s.say(YOU, None, "yes")
    s.say(YOU, FLAT, "flat balances, and what am i owed overall?")
    chats = {m.conversation.ref for m in s.world.last}
    assert FLAT in chats
    private = [m.text for m in s.world.last if m.conversation.ref == f"dm:{YOU.phone}"]
    group = [m.text for m in s.world.last if m.conversation.ref == FLAT]
    assert any("10,200" in text for text in private), private
    assert not any("10,200" in text for text in group), group


def test_a_personal_message_can_add_to_the_group(request: pytest.FixtureRequest) -> None:
    # D5: the bill is a Flat 4B bill, posted in the group once saved
    s = live(request, YOU, SAM)
    s.say(YOU, None, "put internet 900 in flat 4b, split with everyone")
    s.say(YOU, None, "yes")
    bills = s.bills(YOU)
    assert [b.total_cents for b in bills] == [90000]
    assert s.group_balance(FLAT, YOU) == 45000
    assert FLAT in {m.conversation.ref for m in s.world.last}


def test_stop_and_start_notifications(request: pytest.FixtureRequest) -> None:
    # J: "stop" turns off notifications and reminders; "start" turns them back on
    s = live(request, YOU, SAM)
    s.say(SAM, None, "stop sending me stuff pls")
    assert not s.world.person(SAM).notifications_enabled
    s.say(SAM, None, "ok you can message me again")
    assert s.world.person(SAM).notifications_enabled


def test_chatter_in_the_group_is_left_alone(request: pytest.FixtureRequest) -> None:
    # L8, B1, SPEC 10.2: Sam was just answered, so the bot listens for 10 minutes but says
    # nothing and stores nothing; after that his chatter doesn't reach the model at all
    s = live(request, YOU, SAM)
    before = len(s.world.transcript(FLAT))
    for text in ("lol", "who ate my maggi"):
        assert s.say(SAM, FLAT, text, addressed=False) == ""
    assert len(s.world.transcript(FLAT)) == before
    s.world.clock.advance(timedelta(minutes=11))
    calls = s.world.model_calls("install")
    assert s.world.say(SAM, FLAT, "bro the wifi is down again", addressed=False) == ""
    assert s.world.model_calls("install") == calls


def test_which_sam_in_a_group(request: pytest.FixtureRequest) -> None:
    # L5 in a group: the list is code's, the adder picks, only the adder and that Sam pay
    other_sam = Someone("Sam", "+919876500010")
    s = live(request, YOU, SAM, other_sam, RAJ)
    asked = s.say(YOU, FLAT, "dinner 900 with sam")
    assert "Which Sam?" in asked
    s.say(YOU, FLAT, "the second one")
    assert s.participants(FLAT) == {s.world.person(YOU).id, s.world.person(other_sam).id}
