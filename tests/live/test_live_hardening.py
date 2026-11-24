"""Opt-in hardening: a long receipt with several open questions, many changes in one message,
and two people changing the same bill at once (SPEC 8.4, 10.4, 12.2; C6, C8, G1-G4)."""

import threading

import pytest
from sqlalchemy import Engine

from smartsplit.adapters.db.repository import SqlRepository
from smartsplit.adapters.fakes.agent import call
from smartsplit.domain.enums import DraftState, PromptKind, PromptStatus
from smartsplit.domain.model import BillDraft
from tests.integration.world import FLAT, RAJ, SAM, YOU, Someone
from tests.live.session import Live, grocery, live, photo

pytestmark = [pytest.mark.live, pytest.mark.enable_socket]

GROCERY_TOTAL = 626535


def flat_rules(s: Live) -> None:
    """Raj never drinks milk; Sam usually skips beer; Raj usually skips chips; the whey is
    Sam's (said in Flat 4B, scripted)."""
    s.switch.current = s.world.agent
    for who, item, kind in (
        (RAJ, "milk", "exclude"),
        (SAM, "beer", "soft_exclude"),
        (RAJ, "chips", "soft_exclude"),
        (SAM, "whey protein", "only"),
    ):
        s.world.say(who, FLAT, f"{item} rule", call("add_rule", subject="me", item=item, kind=kind))
    s.go_live()


def open_questions(s: Live) -> int:
    with s.world.repository.unit_of_work() as uow:
        prompts = uow.prompts.for_conversation(s.world.key(FLAT), [PromptStatus.OPEN])
    return sum(p.kind is PromptKind.ENGINE_QUESTION for p in prompts)


def reviewing(s: Live) -> list[BillDraft]:
    return [d for d in s.world.drafts(FLAT) if d.state is DraftState.REVIEWING]


def share(s: Live, who: Someone) -> int:
    """`who`'s share of the one saved bill."""
    person_id = s.world.person(who).id
    (bill,) = s.bills(YOU)
    return sum(x.cents for x in bill.shares if x.person_id == person_id)


def test_a_long_receipt_with_several_questions(request: pytest.FixtureRequest) -> None:
    # C8, G1, G2, E2, E3, E5: short summary, questions by line, anyone answers
    s = live(request, YOU, SAM, RAJ)
    flat_rules(s)
    summary = s.say(YOU, FLAT, "split this", image=grocery())
    assert s.reviewing(FLAT) == [GROCERY_TOTAL]
    assert open_questions(s) >= 2, summary
    s.say(SAM, FLAT, "i didnt have any of the beer")
    s.say(RAJ, FLAT, "i did have some chips")
    assert open_questions(s) == 0
    details = s.say(YOU, FLAT, "show me all the lines")
    assert "Carry Bag" in details or "carry bag" in details.casefold()
    s.say(YOU, FLAT, "yes")
    assert [b.total_cents for b in s.bills(YOU)] == [GROCERY_TOTAL]
    assert share(s, SAM) > 289900  # all of the whey, plus his part of the rest
    assert sum(x.cents for x in s.bills(YOU)[0].shares) == GROCERY_TOTAL


def test_many_changes_in_one_message(request: pytest.FixtureRequest) -> None:
    # C6, C5, G6: every change applied, one summary shown; the lines then differ from the
    # receipt total by ₹5, which the adder keeps as a tip
    s = live(request, YOU, SAM, RAJ)
    s.say(YOU, FLAT, "split this", image=grocery())
    reply = s.say(
        YOU,
        FLAT,
        "beer was 600 not 640, remove the carry bag, add water 40, and raj had none of the beer",
    )
    assert reply.count("paid by Alex") == 1, reply
    (draft,) = reviewing(s)
    amounts = {line.name.casefold(): line.amount_cents for line in draft.lines}
    beer = next(v for k, v in amounts.items() if "beer" in k)
    assert beer == 60000
    assert not any("bag" in k for k in amounts)
    assert any("water" in k and v == 4000 for k, v in amounts.items())
    s.say(YOU, FLAT, "keep the 5 as a tip and save it")
    raj, sam = share(s, RAJ), share(s, SAM)
    assert raj < sam  # Raj is off the beer, Sam isn't


def test_yes_to_an_older_summary_after_someone_changed_it(request: pytest.FixtureRequest) -> None:
    # G4: Sam changes the bill; Alex's "yes" quotes the summary from before the change
    s = live(request, YOU, SAM, RAJ)
    first = s.say(YOU, FLAT, "split this", image=photo())
    s.say(SAM, FLAT, "raj wasnt there, take him off this one")
    quoting = s.world.message(
        YOU, FLAT, "yes", addressed=False, reply_to_bot=True, quoted_text=first[:40]
    )
    s.switch.words = []
    reply = s.world.send(quoting)
    s.log.messages += 1
    s.log.lines.append(f"Alex in Flat 4B (quoting the first summary): yes -> {reply!r}")
    assert s.bills(YOU) == []  # his yes answered the old summary (G4)
    assert reviewing(s)
    s.say(YOU, FLAT, "ok yes, save it")
    assert share(s, RAJ) == 0


@pytest.mark.db
def test_two_people_at_the_same_moment(request: pytest.FixtureRequest, clean_pg: Engine) -> None:
    # SPEC 12.2: one at a time per chat; the bill saved is one the adder was shown
    s = live(request, YOU, SAM, RAJ, repository=SqlRepository(clean_pg))
    s.say(YOU, FLAT, "split this", image=photo())
    replies: dict[str, str] = {}

    def send(who: Someone, text: str) -> None:
        replies[who.name] = s.world.bot.handle(s.world.message(who, FLAT, text)).replies[0].text

    threads = [
        threading.Thread(target=send, args=(YOU, "yes")),
        threading.Thread(target=send, args=(SAM, "take raj off, he wasnt there")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=120)
    s.log.messages += 2
    s.log.lines += [f"{name} (at the same time): {text!r}" for name, text in replies.items()]
    assert set(replies) == {"Alex", "Sam"}
    saved = s.bills(YOU)
    open_drafts = reviewing(s)
    assert len(saved) + len(open_drafts) == 1  # never both, never neither
    if saved:
        (bill,) = saved
        assert sum(x.cents for x in bill.shares) == bill.total_cents == 60900
