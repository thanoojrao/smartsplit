"""The production flow around the agent: when the bot reacts in a group, photo checks,
mentions, quoted replies, the bot being added, daily limits, busy chats, tick batches and the
per-turn report (SPEC 7, 10.1-10.3, 10.8, 12.2, 12.4, 12.5)."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

import pytest

from smartsplit.adapters.fakes.agent import call, say
from smartsplit.adapters.fakes.repository import InMemoryRepository
from smartsplit.adapters.fakes.system import FixedClock
from smartsplit.domain.messages import ChatEvent, ContactAttachment, Mention
from smartsplit.ports.errors import DuplicateKeyError, StorageUnavailableError
from smartsplit.ports.llm import CountCall, LlmUnavailableError, ParsedReceipt
from smartsplit.services import orchestrator
from smartsplit.services.text import NEEDS_NUMBER, OVER_LIMIT, TRY_AGAIN
from smartsplit.services.ticking import Ticker
from smartsplit.services.turn import OrchestratorSettings
from tests.integration.world import FLAT, PRIYA, RAJ, SAM, T0, YOU, World, calling, flat, receipt

SAVE = calling("confirm_draft", draft="@D")


def start_bill(world: World) -> str:
    return world.say(
        YOU, FLAT, "split this", calling("start_receipt"), image=receipt("restaurant_tip")
    )


def member_ids(world: World) -> set[str]:
    with world.repository.unit_of_work() as uow:
        group = uow.conversations.get(world.key(FLAT))
        assert group is not None and group.group_id is not None
        return {m.person_id for m in uow.memberships.for_group(group.group_id) if m.left_at is None}


def test_the_bot_listens_to_people_it_waits_on_for_ten_minutes() -> None:
    # SPEC 10.2: the adder of an active draft, and whoever it last replied to
    world = World()
    flat(world, YOU, SAM, RAJ)
    start_bill(world)
    calls = len(world.agent.requests)
    assert world.say(YOU, FLAT, "looks right", say("Say yes to save it."), addressed=False)
    assert len(world.agent.requests) == calls + 1
    assert world.say(RAJ, FLAT, "nice dinner", addressed=False) == ""
    assert len(world.agent.requests) == calls + 1
    world.clock.advance(timedelta(minutes=11))
    assert world.say(YOU, FLAT, "ok", addressed=False) == ""
    assert len(world.agent.requests) == calls + 1


def test_a_waited_on_message_the_model_lets_pass_is_not_stored() -> None:
    world = World()
    flat(world, YOU, SAM)
    start_bill(world)
    before = len(world.transcript(FLAT))
    assert world.say(YOU, FLAT, "brb", say(""), addressed=False) == ""
    assert len(world.transcript(FLAT)) == before


def test_people_who_left_are_not_waited_on() -> None:
    world = World()
    flat(world, YOU, SAM)
    world.say(YOU, FLAT, "Sam moved out", calling("member_left", person="@Sam"))
    world.say(SAM, FLAT, "bye", say("Bye Sam."))  # addressed: the bot replies to Sam
    assert world.say(SAM, FLAT, "one more thing", addressed=False) == ""


def test_an_unaddressed_receipt_photo_in_a_group_reaches_the_model() -> None:
    # SPEC 10.2: a photo that turns out to be a receipt; the sender isn't charged for it
    world = World()
    flat(world, YOU, SAM)
    me = world.person(YOU).id
    before = world.model_calls(me)
    reply = world.say(
        YOU, FLAT, None, calling("start_receipt"), image=receipt("restaurant_tip"), addressed=False
    )
    assert "Toit, ₹2,047.00, paid by Alex." in reply
    assert world.model_calls(me) == before


def test_an_addressed_photo_that_is_not_a_receipt_still_reaches_the_model() -> None:
    world = World()
    flat(world, YOU, SAM)
    reply = world.say(
        YOU, FLAT, "what is this", say("That's not a receipt."), image=receipt("not_a_receipt")
    )
    assert reply == "That's not a receipt."
    assert "[photo: not a receipt]" in world.turn_input


def test_photos_from_non_members_are_not_read() -> None:
    # SPEC 7: the checks come before the (paid) read
    world = World()
    flat(world, YOU, SAM)
    world.say(PRIYA, None, "hi")
    reads = world.parser.calls
    assert world.say(PRIYA, FLAT, None, image=receipt("restaurant_tip"), addressed=False) == ""
    assert world.parser.calls == reads


def test_a_photo_over_the_size_limit_is_not_read() -> None:
    world = World(settings=OrchestratorSettings(max_image_bytes=50))
    world.say(YOU, None, "hi")
    reply = world.say(
        YOU,
        None,
        "split this",
        say("That photo is too big for me."),
        image=receipt("restaurant_tip"),
    )
    assert reply == "That photo is too big for me."
    assert "[photo: not read]" in world.turn_input
    assert world.parser.calls == 0


def test_mentions_read_as_names_and_a_mention_with_a_number_adds_someone() -> None:
    # SPEC 10.1, 10.3
    world = World()
    flat(world, YOU, SAM)
    mentions = (
        Mention("lid:priya", "Priya", PRIYA.phone),
        Mention(SAM.ref, "Sammy", None),
        Mention("lid:bob", "Bob", None),
    )
    text = f"add @lid:priya, ask @{SAM.ref} and @lid:bob"
    message = world.message(YOU, FLAT, text, mentions=mentions)
    reply = world.send(message, [calling("add_person", name="Priya", mention="@Priya")])
    assert "Alex added Priya to Flat 4B." in reply
    assert "add @Priya, ask @Sammy and @Bob" in world.turn_input
    assert "[@Sammy is P2 Sam]" in world.turn_input
    assert "[@Bob: someone I don't know, no number given]" in world.turn_input
    assert world.transcript(FLAT)[-2].text == "add @Priya, ask @Sammy and @Bob"
    assert world.person(PRIYA).id in member_ids(world)


def test_a_mention_alone_adds_nobody() -> None:
    world = World()
    flat(world, YOU, SAM)
    mention = (Mention("lid:priya", "Priya", PRIYA.phone),)
    world.send(world.message(YOU, FLAT, "hi @lid:priya", mentions=mention), [say("Hi Priya!")])
    assert world.person(PRIYA).id not in member_ids(world)


def test_a_quoted_bot_message_gets_the_first_handles() -> None:
    # SPEC 8.6: "yes" to an older summary means that summary
    world = World()
    flat(world, YOU, SAM)
    summary = start_bill(world)
    world.say(SAM, FLAT, "hello", say("Hi Sam."))
    quoting = world.message(
        YOU, FLAT, "yes", addressed=False, reply_to_bot=True, quoted_text=summary[:30]
    )
    saved = world.send(quoting, [SAVE])
    assert "Saved: Toit, ₹2,047.00." in saved
    first_line = world.turn_input.split("<message>\n", 1)[1].splitlines()[0]
    assert first_line.startswith('[replying to the bot\'s message "Toit, ₹2,047.00, paid by Alex."')
    assert "(showed D1 v" in first_line


def test_a_quote_that_matches_nothing_is_just_a_message() -> None:
    world = World()
    flat(world, YOU, SAM)
    quoting = world.message(
        YOU, FLAT, "hm", addressed=False, reply_to_bot=True, quoted_text="something old"
    )
    world.send(quoting, [say("Hm?")])
    assert "replying to" not in world.turn_input


def test_added_to_a_group_the_bot_introduces_itself_and_a_reply_joins() -> None:
    # SPEC 10.3: no model call for the intro; replies to it are addressed to the bot
    world = World()
    world.say(YOU, None, "hi")
    world.say(SAM, None, "hi")
    calls = len(world.agent.requests)
    added = world.message(YOU, FLAT, event=ChatEvent("bot_added", None), addressed=False)
    intro = world.send(added)
    assert intro.startswith("Hi Flat 4B! I split bills")
    assert intro.endswith('reply to this message with "join" to split bills here.')
    assert len(world.agent.requests) == calls
    assert member_ids(world) == {world.person(YOU).id}
    reply = world.message(
        SAM, FLAT, "join", addressed=False, reply_to_bot=True, quoted_text=intro[:40]
    )
    assert "Sam joined Flat 4B." in world.send(reply, [call("join_group")])


def test_someone_known_only_by_a_hidden_id_gets_the_one_tap_link() -> None:
    world = World(settings=OrchestratorSettings(bot_link="https://wa.me/15550001?text=hi"))
    hidden = replace(world.message(YOU, FLAT, "hi"), sender_ref="lid:alex", sender_phone=None)
    reply = world.send(hidden)
    assert reply == NEEDS_NUMBER.format(link="https://wa.me/15550001?text=hi")
    assert reply.endswith("https://wa.me/15550001?text=hi")


def test_a_participant_left_event_without_a_subject_is_ignored() -> None:
    world = World()
    flat(world, YOU, SAM)
    gone = world.message(SAM, FLAT, event=ChatEvent("participant_left", None), addressed=False)
    assert world.send(gone) == ""
    assert world.person(SAM).id in member_ids(world)


def test_over_the_daily_limit_the_bot_says_so_once_then_is_quiet_until_tomorrow() -> None:
    # SPEC 12.5
    world = World(settings=OrchestratorSettings(llm_calls_per_person_per_day=2))
    world.say(YOU, None, "hi", say("Hi!"))  # the first message comes before anyone to charge
    world.say(YOU, None, "and?", say("Yes?"))
    world.say(YOU, None, "and then?", say("Then?"))
    assert world.say(YOU, None, "more") == OVER_LIMIT
    assert world.outcome is not None and world.outcome.report.outcome == "limit"
    assert world.say(YOU, None, "more!") == ""
    world.clock.advance(timedelta(days=1))
    assert world.say(YOU, None, "morning", say("Morning!")) == "Morning!"


def test_the_whole_install_has_a_daily_cap_too() -> None:
    world = World(settings=OrchestratorSettings(llm_calls_per_day=2))
    world.say(SAM, None, "hi", say("Hi Sam!"))
    world.say(YOU, None, "hi", say("Hi Alex!"))  # two calls: the install's cap
    assert world.say(SAM, None, "and now?") == OVER_LIMIT
    assert world.outcome is not None and world.outcome.report.install_nearly_spent
    assert world.say(YOU, None, "me too?") == OVER_LIMIT
    assert world.say(YOU, None, "me too!") == ""


def test_over_the_limit_unaddressed_group_messages_stay_silent() -> None:
    world = World(settings=OrchestratorSettings(llm_calls_per_person_per_day=20))
    flat(world, YOU, SAM)
    me = world.person(YOU).id
    for _ in range(20 - world.model_calls(me)):
        world.repository.count_usage(me, world.clock.now().date())
    calls = world.parser.calls
    assert world.say(YOU, FLAT, None, image=receipt("restaurant_tip"), addressed=False) == ""
    assert world.parser.calls == calls
    assert world.say(YOU, FLAT, "c") == OVER_LIMIT


def test_a_busy_chat_is_answered_busy_and_nothing_is_recorded() -> None:
    # SPEC 12.2: 503, and the gateway retries the same message
    repository = InMemoryRepository()
    world = World(repository=repository)
    world.say(YOU, None, "hi", say("Hi!"))
    repository.busy.add(world.key(None, YOU))
    message = world.message(YOU, None, "balances")
    assert world.send(message) == ""
    assert world.outcome is not None and world.outcome.busy
    assert world.outcome.report.outcome == "busy"
    repository.busy.clear()
    assert world.send(message, [say("All square.")]) == "All square."


def test_a_tick_batch_comes_back_until_it_is_acknowledged() -> None:
    # SPEC 10.8: a lost response never loses a notice
    world = World()
    flat(world, YOU, SAM)
    start_bill(world)
    world.clock.advance(timedelta(hours=25))
    first = world.bot.tick()
    assert any("Still waiting on the Toit bill." in m.text for m in first.messages)
    world.clock.advance(timedelta(minutes=1))
    assert world.bot.tick().messages == ()
    world.clock.advance(timedelta(minutes=2))
    again = world.bot.tick()
    assert (again.id, again.messages) == (first.id, first.messages)
    assert world.bot.ack(first.id)
    world.clock.advance(timedelta(minutes=3))
    assert world.bot.tick().id != first.id
    assert not world.bot.ack("no-such-batch")


def test_notices_claimed_before_a_tick_failed_still_come_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # SPEC 10.8: a notice marked sent is always in a stored batch
    world = World()
    for someone in (YOU, SAM):
        world.say(someone, None, "hi")
    world.say(YOU, None, "add Sam", call("add_person", name="Sam", phone=SAM.phone))
    world.say(
        YOU,
        None,
        "taxi",
        calling("add_manual_bill", description="taxi", amount="300", people=["@Sam"]),
    )
    world.say(YOU, None, "yes", SAVE)

    def broken(self: Ticker, now: datetime, batch_id: str) -> None:
        raise RuntimeError("database went away")

    with monkeypatch.context() as patched:
        patched.setattr(Ticker, "idle_drafts", broken)
        with pytest.raises(RuntimeError):
            world.bot.tick()
    world.clock.advance(timedelta(minutes=3))
    assert "Alex added taxi" in world.tick()


def test_an_empty_tick_batch_can_be_acknowledged_too() -> None:
    world = World()
    batch = world.bot.tick()
    assert batch.messages == ()
    assert world.bot.ack(batch.id)


def test_tick_skips_a_busy_chat_and_gets_to_it_next_time() -> None:
    # SPEC 10.8: tick never waits behind a turn
    repository = InMemoryRepository()
    world = World(repository=repository)
    flat(world, YOU, SAM)
    start_bill(world)
    world.clock.advance(timedelta(hours=25))
    repository.busy.add(world.key(FLAT))
    assert "Still waiting" not in world.tick()
    repository.busy.clear()
    assert "Still waiting on the Toit bill." in world.tick()


def test_each_turn_reports_what_it_did_without_content() -> None:
    # SPEC 12.4
    world = World()
    message = world.message(YOU, None, "how do I stand?")
    world.send(message, [call("get_balances"), say("All square.")])
    assert world.outcome is not None
    report = world.outcome.report
    assert report.outcome == "replied"
    assert report.steps == 2
    assert report.tools == (("get_balances", True),)
    assert len(report.chat) == 12 and YOU.phone not in report.chat
    world.send(message)
    assert outcome_of(world) == "repeat"
    assert world.say(SAM, FLAT, "chatter", addressed=False) == ""
    assert outcome_of(world) == "silent"


def outcome_of(world: World) -> str:
    assert world.outcome is not None
    return world.outcome.report.outcome


@dataclass
class DownParser:
    """The receipt reader is down, after a while if given a clock."""

    clock: FixedClock | None = None

    def parse(
        self,
        image: bytes,
        mime_type: str,
        currency: str,
        timeout_seconds: float,
        count_call: CountCall,
    ) -> ParsedReceipt:
        count_call()
        if self.clock is not None:
            self.clock.advance(timedelta(seconds=7))
        raise LlmUnavailableError("down")


def test_the_last_person_replied_to_is_waited_on() -> None:
    # SPEC 10.2: no draft or question involved
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.clock.advance(timedelta(minutes=11))
    world.say(RAJ, FLAT, "hey bot", say("Hi Raj."))
    assert world.say(RAJ, FLAT, "thanks", say("Any time."), addressed=False) == "Any time."
    assert world.say(SAM, FLAT, "lol", addressed=False) == ""


def test_people_an_open_question_is_about_are_waited_on() -> None:
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.say(
        SAM,
        FLAT,
        "I skip beer",
        call("add_rule", subject="me", item="beer pitcher", kind="soft_exclude"),
    )
    start_bill(world)
    world.say(RAJ, FLAT, "nice", say("Thanks Raj."))  # the bot last replied to Raj
    reply = world.say(SAM, FLAT, "I had none", say("Noted."), addressed=False)
    assert reply == "Noted."


def test_the_person_a_pending_action_waits_for_is_waited_on() -> None:
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.say(SAM, FLAT, "no chips", call("add_rule", subject="me", item="chips", kind="exclude"))
    world.say(RAJ, FLAT, "Sam eats chips now", calling("delete_rule", subject="@Sam", item="chips"))
    world.say(YOU, FLAT, "hello", say("Hi Alex."))  # the bot last replied to Alex
    done = world.say(RAJ, FLAT, "yes", calling("confirm_pending", action="@A"), addressed=False)
    assert done == "Raj removed a rule: Sam never shares chips."


def test_a_waited_on_message_the_model_acts_on_is_stored() -> None:
    world = World()
    flat(world, YOU, SAM)
    start_bill(world)
    before = len(world.transcript(FLAT))
    world.say(YOU, FLAT, "yes", SAVE, addressed=False)
    assert len(world.transcript(FLAT)) == before + 2


def test_events_are_handled_even_over_the_limits() -> None:
    world = World(settings=OrchestratorSettings(llm_calls_per_day=30))
    flat(world, YOU, SAM)
    for _ in range(30 - world.model_calls("install")):
        world.repository.count_usage("install", world.clock.now().date())
    sam = world.person(SAM).id
    gone = world.message(YOU, FLAT, event=ChatEvent("participant_left", SAM.ref), addressed=False)
    assert "Sam" in world.send(gone)
    assert sam not in member_ids(world)


def test_added_again_to_a_known_group_the_adder_is_in() -> None:
    world = World()
    flat(world, YOU, SAM)
    world.say(RAJ, None, "hi")
    added = world.message(RAJ, FLAT, event=ChatEvent("bot_added", None), addressed=False)
    assert "Raj is in" in world.send(added)
    assert world.person(RAJ).id in member_ids(world)


def test_an_unknown_group_starts_only_when_someone_talks_to_the_bot() -> None:
    # SPEC 10.3
    world = World()
    world.say(YOU, None, "hi")
    card = ContactAttachment("Priya", PRIYA.phone)
    assert world.say(YOU, FLAT, None, contact=card, addressed=False) == ""
    assert world.say(YOU, FLAT, None, image=receipt("restaurant_tip"), addressed=False) == ""
    assert world.parser.calls == 0
    with world.repository.unit_of_work() as uow:
        assert uow.conversations.get(world.key(FLAT)) is None


def test_an_unaddressed_group_photo_says_nothing_when_the_reader_is_down() -> None:
    world = World(receipts=DownParser())
    flat(world, YOU, SAM)
    assert world.say(YOU, FLAT, None, image=receipt("restaurant_tip"), addressed=False) == ""
    assert world.say(YOU, FLAT, "split this", image=receipt("restaurant_tip")) == TRY_AGAIN


def test_the_limit_notice_survives_a_busy_retry() -> None:
    repository = InMemoryRepository()
    world = World(
        repository=repository, settings=OrchestratorSettings(llm_calls_per_person_per_day=1)
    )
    world.say(YOU, None, "hi", say("Hi!"))
    world.say(YOU, None, "one", say("One."))
    repository.busy.add(world.key(None, YOU))
    message = world.message(YOU, None, "more")
    assert world.send(message) == ""
    repository.busy.clear()
    assert world.send(message) == OVER_LIMIT


def test_a_failed_turn_reports_its_time() -> None:
    clock = FixedClock(T0)
    world = World(clock=clock, receipts=DownParser(clock))
    world.say(YOU, None, "hi")
    world.say(YOU, None, "split", image=receipt("restaurant_tip"))
    assert outcome_of(world) == "failed"
    assert world.outcome is not None and world.outcome.report.seconds == 7.0


def test_a_database_error_mid_turn_asks_to_try_again_and_records_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # SPEC 12.2: the same new person writing in two chats at once, a deadlock, no connection
    world = World()
    message = world.message(YOU, None, "hi")
    for error in (DuplicateKeyError("phone taken"), StorageUnavailableError("deadlock")):

        def failing(*args: object, failure: Exception = error, **kwargs: object) -> None:
            raise failure

        with monkeypatch.context() as patched:
            patched.setattr(orchestrator, "arrive", failing)
            assert world.send(message) == TRY_AGAIN
        assert outcome_of(world) == "failed"
    retried = world.send(message, [say("Hi Alex!")])
    assert retried.startswith("Hi Alex! I split bills")  # still the first message: a welcome


def test_an_unaddressed_contact_card_in_a_group_is_ignored() -> None:
    # SPEC 10.2: only addressed messages, receipt photos, events and waited-on people
    world = World()
    flat(world, YOU, SAM)
    world.clock.advance(timedelta(minutes=11))
    calls = len(world.agent.requests)
    card = ContactAttachment("Priya", PRIYA.phone)
    assert world.say(SAM, FLAT, None, contact=card, addressed=False) == ""
    assert outcome_of(world) == "silent"
    assert len(world.agent.requests) == calls


def test_the_one_tap_link_is_kept_in_the_transcript_and_never_posted_unasked() -> None:
    # SPEC 8.6: every bot message is stored; an unaddressed group message gets no reply
    world = World()
    flat(world, YOU, SAM)
    hidden = replace(world.message(RAJ, FLAT, "hi"), sender_ref="lid:raj", sender_phone=None)
    reply = world.send(hidden)
    assert reply == NEEDS_NUMBER.format(link=world.settings.bot_link)
    assert world.transcript(FLAT)[-1].text == reply
    left = ChatEvent("bot_added", None)
    quiet = replace(world.message(RAJ, FLAT, event=left, addressed=False), sender_ref="lid:raj")
    assert world.send(replace(quiet, sender_phone=None)) == ""
    assert world.transcript(FLAT)[-1].text == reply
