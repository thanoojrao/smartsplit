"""Adding, reviewing and saving bills in a group chat (use cases C1-C15, G1-G7, L3, L11)."""

from dataclasses import replace
from datetime import timedelta

from smartsplit.adapters.fakes.agent import call, say
from smartsplit.adapters.fakes.llm import FakeCanonicalizer
from smartsplit.domain.enums import DraftState
from tests.integration.world import FLAT, PRIYA, RAJ, SAM, YOU, World, calling, flat, receipt

SAVE = calling("confirm_draft", draft="@D")


def photo(world: World, name: str = "restaurant_tip", **args: object) -> str:
    """The adder sends a receipt photo and the model starts it."""
    return world.say(YOU, FLAT, "split this", calling("start_receipt", **args), image=receipt(name))


def edit(world: World, change: dict[str, object]) -> str:
    return world.say(YOU, FLAT, "fix", calling("edit_draft", draft="@D", change=change))


def test_receipt_photo_is_split_among_current_members_and_saved() -> None:
    # C1, C15: summary, the adder confirms on a later message, balances posted in the group
    world = World()
    flat(world, YOU, SAM, RAJ)
    summary = photo(world)
    assert "Toit, ₹2,047.00, paid by Alex." in summary
    assert "Alex: ₹682.34" in summary and "Raj: ₹682.33" in summary
    saved = world.say(YOU, FLAT, "yes", SAVE)
    assert "Saved: Toit, ₹2,047.00." in saved
    assert "Sam owes Alex ₹682.33" in saved
    assert {m.conversation.ref for m in world.last} == {FLAT}
    assert [d.state for d in world.drafts(FLAT)] == [DraftState.SAVED]


def test_the_models_words_come_first_then_the_shown_block() -> None:
    # SPEC 8.5: every amount the user reads is rendered by code, after the model's words
    world = World()
    flat(world, YOU, SAM)
    reply = world.say(
        YOU,
        FLAT,
        "split this",
        call("start_receipt"),
        say("Here you go."),
        image=receipt("restaurant_tip"),
    )
    assert reply.startswith("Here you go.\n\nToit, ₹2,047.00")


def test_split_and_save_in_one_message_only_shows_the_summary() -> None:
    # L11, SPEC 8.4: the adder must see the split before saving it
    world = World()
    flat(world, YOU, SAM)
    world.say(
        YOU,
        FLAT,
        "split this and save it",
        call("start_receipt"),
        SAVE,
        image=receipt("restaurant_tip"),
    )
    tool_result = world.agent.requests[-1].history[-1][1][0]
    assert tool_result.data == {
        "saved": False,
        "why": "it was just shown or changed: the adder has to see it first",
    }
    assert [d.state for d in world.drafts(FLAT)] == [DraftState.REVIEWING]
    assert "Saved" in world.say(YOU, FLAT, "yes", SAVE)


def test_subset_and_payer_from_the_caption() -> None:
    # C2, C3
    world = World()
    flat(world, YOU, SAM, RAJ)
    summary = photo(world, people=["me", "@Sam"], payer="@Sam")
    assert "paid by Sam" in summary
    assert "Raj" not in summary


def test_everyone_except() -> None:
    # C2
    world = World()
    flat(world, YOU, SAM, RAJ)
    summary = photo(world, everyone_except=["@Raj"])
    assert "Raj" not in summary and "Sam: ₹1,023.50" in summary


def test_manual_bill_split_equally() -> None:
    # C4
    world = World()
    flat(world, YOU, SAM, RAJ)
    summary = world.say(
        YOU,
        FLAT,
        "electricity 1800, split all",
        call("add_manual_bill", description="electricity", amount="1800"),
    )
    assert "electricity, ₹1,800.00" in summary
    assert "Sam: ₹600.00" in summary
    assert "Saved" in world.say(YOU, FLAT, "save", SAVE)


def test_only_current_members_can_be_in_a_group_bill() -> None:
    # C2, SPEC 10.7: Priya isn't in Flat 4B, so she has no handle here at all
    world = World()
    flat(world, YOU, SAM)
    world.say(PRIYA, None, "hi")
    world.say(YOU, None, "add Priya", call("add_person", name="Priya", phone=PRIYA.phone))
    world.say(
        YOU,
        FLAT,
        "split with Priya",
        call("start_receipt", people=["P9"]),
        image=receipt("restaurant_tip"),
    )
    refused = world.agent.requests[-1].history[-1][1][0]
    assert refused.ok is False
    assert refused.error == "P9 isn't a P handle from this conversation."
    assert "Priya" not in world.turn_input.split("</state>")[0]
    assert world.drafts(FLAT) == []


def test_total_mismatch_is_shown_and_kept_only_when_the_adder_says_so() -> None:
    # C5: lines 560 vs total 570; the difference is shared like a tip once accepted
    world = World()
    flat(world, YOU, SAM)
    summary = photo(world, "total_mismatch")
    assert "The lines add up to ₹560.00 but the total says ₹570.00" in summary
    world.say(YOU, FLAT, "yes", SAVE)
    asked = world.agent.requests[-1].history[-1][1][0].data
    assert asked["saved"] is False and "don't add up" in str(asked["why"])
    saved = world.say(
        YOU, FLAT, "keep it", calling("confirm_draft", draft="@D", accept_difference=True)
    )
    assert "Saved: Kirana, ₹570.00." in saved
    assert "Sam owes Alex ₹285.00" in saved


def test_review_edits_recompute_and_line_numbers_never_shift() -> None:
    # C6, C8, L3: "line 4 is 120", "remove the bag", "add water 40", "total is ..."
    world = World()
    flat(world, YOU, SAM)
    photo(world, "grocery_taxed_mix")
    before = world.drafts(FLAT)[0]
    first, second = before.lines[0], before.lines[1]
    edit(world, {"type": "RemoveLine", "line": "L1"})
    shown = edit(world, {"type": "SetLineAmount", "line": "L2", "amount": "120"})
    after = world.drafts(FLAT)[0]
    assert first.id not in {x.id for x in after.lines}
    assert after.lines[0].position == 2
    assert next(x for x in after.lines if x.id == second.id).amount_cents == 12000
    edit(world, {"type": "AddLine", "name": "water", "amount": "40"})
    added = world.drafts(FLAT)[0].lines[-1]
    assert (added.name, added.position) == ("water", len(before.lines) + 1)
    assert "paid by Alex" in shown


def test_unknown_line_is_refused() -> None:
    world = World()
    flat(world, YOU, SAM)
    photo(world)
    edit(world, {"type": "RemoveLine", "line": "L99"})
    result = world.agent.requests[-1].history[-1][1][0]
    assert result.error == "There's no line 99 in the Toit bill."


def test_a_hard_to_read_line_is_flagged_and_fixing_it_clears_the_flag() -> None:
    # C7
    world = World()
    flat(world, YOU, SAM)
    summary = photo(world, "grocery_taxed_mix")
    assert "Couldn't read line" in summary
    flagged = next(x for x in world.drafts(FLAT)[0].lines if x.confidence < 0.6)
    fixed = edit(world, {"type": "SetLineAmount", "line": f"L{flagged.position}", "amount": "50"})
    assert "Couldn't read line" not in fixed


def test_weights_and_someone_had_none() -> None:
    # G6, E7: "Raj had none of the wine", "2 for Sam, 1 for Raj"
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.say(YOU, FLAT, "wine 300", call("add_manual_bill", description="wine", amount="300"))
    shown = edit(world, {"type": "UnassignLine", "line": "L1", "people": ["@Raj"]})
    assert "Raj: ₹0.00" in shown and "Sam: ₹150.00" in shown
    weighted = edit(
        world,
        {
            "type": "AssignLine",
            "line": "L1",
            "weights": [{"person": "@Sam", "weight": 2}, {"person": "@Raj", "weight": 1}],
        },
    )
    assert "Sam: ₹200.00" in weighted and "Raj: ₹100.00" in weighted


def test_exact_part_of_a_line() -> None:
    # E8, E9
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.say(YOU, FLAT, "dinner 250", call("add_manual_bill", description="dinner", amount="250"))
    shown = edit(
        world,
        {"type": "AssignLine", "line": "L1", "exact": [{"person": "@Sam", "amount": "100"}]},
    )
    assert "Sam: ₹100.00" in shown and "Raj: ₹75.00" in shown


def test_manual_bill_with_exact_amounts_must_add_up() -> None:
    # E9
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.say(
        YOU,
        FLAT,
        "rent 30000: Sam 12000, me 9000, Raj 9000",
        calling(
            "add_manual_bill",
            description="rent",
            amount="30000",
            exact=[
                {"person": "@Sam", "amount": "12000"},
                {"person": "me", "amount": "9000"},
                {"person": "@Raj", "amount": "9000"},
            ],
        ),
    )
    assert "Sam: ₹12,000.00" in world.in_chat(FLAT)
    world.say(
        YOU,
        FLAT,
        "rent 30000: Sam 25000, me 9000",
        calling(
            "add_manual_bill",
            description="rent",
            amount="30000",
            exact=[{"person": "@Sam", "amount": "25000"}, {"person": "me", "amount": "9000"}],
        ),
    )
    refused = world.agent.requests[-1].history[-1][1][0]
    assert refused.error == "Those amounts don't add up to the total."


def test_money_arguments_are_strings_in_major_units() -> None:
    # SPEC 8.3: a float, or more decimals than the currency has, is refused
    world = World()
    flat(world, YOU, SAM)
    world.say(YOU, FLAT, "taxi", call("add_manual_bill", description="taxi", amount=12.5))
    assert world.agent.requests[-1].history[-1][1][0].ok is False
    world.say(YOU, FLAT, "taxi", call("add_manual_bill", description="taxi", amount="12.505"))
    assert "isn't an amount" in str(world.agent.requests[-1].history[-1][1][0].error)
    world.say(YOU, FLAT, "taxi", call("add_manual_bill", description="taxi", amount="12.5"))
    assert "taxi, ₹12.50" in world.in_chat(FLAT)


def test_soft_rule_question_is_asked_and_answered_by_anyone() -> None:
    # E5, G1-G3: worded by line; anyone in the group may answer; the latest answer wins
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.say(
        SAM,
        FLAT,
        "I usually skip tips",
        call("add_rule", subject="me", item="beer pitcher", kind="soft_exclude"),
    )
    summary = photo(world)
    assert "Line 3, Beer Pitcher: is Sam in?" in summary
    answered = world.say(
        RAJ, FLAT, "Sam didn't have any", calling("answer_question", question="@Q", included=False)
    )
    assert "open question Q1: Line 3, Beer Pitcher: is Sam in?" in world.turn_input
    assert "is Sam in?" not in answered
    assert world.drafts(FLAT)[0].overrides


def test_questions_can_stay_open_when_saving() -> None:
    # G4
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.say(
        SAM,
        FLAT,
        "skip",
        call("add_rule", subject="me", item="beer pitcher", kind="soft_exclude"),
    )
    photo(world)
    assert "Saved" in world.say(YOU, FLAT, "yes", SAVE)


def test_only_the_adder_saves() -> None:
    # G5
    world = World()
    flat(world, YOU, SAM)
    photo(world)
    world.say(SAM, FLAT, "yes", SAVE)
    assert world.agent.requests[-1].history[-1][1][0].error == "Only Alex can save this bill."


def test_a_change_after_the_summary_means_the_adder_sees_it_again() -> None:
    # G4, SPEC 8.4: the version in the bot's last summary must match
    world = World()
    flat(world, YOU, SAM, RAJ)
    photo(world)
    world.say(
        SAM,
        FLAT,
        "Raj had none of line 1",
        calling(
            "edit_draft",
            draft="@D",
            change={"type": "UnassignLine", "line": "L1", "people": ["@Raj"]},
        ),
    )
    # the edit was shown in the chat, so the adder has seen the new version
    assert "Saved" in world.say(YOU, FLAT, "yes", SAVE)


def test_a_stale_yes_shows_the_new_split_instead() -> None:
    # SPEC 8.4: a change the chat never saw (made elsewhere) blocks the save
    world = World()
    flat(world, YOU, SAM)
    photo(world)
    with world.repository.unit_of_work() as uow:
        draft = uow.drafts.for_conversation(world.key(FLAT), [DraftState.REVIEWING])[0]
        uow.drafts.update(replace(draft, version=draft.version + 1), expected_version=draft.version)
    world.say(YOU, FLAT, "yes", SAVE)
    result = world.agent.requests[-1].history[-1][1][0]
    assert result.data["saved"] is False
    assert "Toit, ₹2,047.00" in world.in_chat(FLAT)
    assert "Saved" in world.say(YOU, FLAT, "yes", SAVE)


def test_second_receipt_from_the_same_adder_is_queued() -> None:
    # C10: started when the first is done; someone else's receipt starts its own draft
    world = World()
    flat(world, YOU, SAM)
    photo(world)
    photo(world, "total_mismatch")
    states = [d.state for d in world.drafts(FLAT)]
    assert states == [DraftState.REVIEWING, DraftState.QUEUED]
    world.say(SAM, FLAT, "here's mine", call("start_receipt"), image=receipt("grocery_taxed_mix"))
    assert [d.state for d in world.drafts(FLAT)].count(DraftState.REVIEWING) == 2
    saved = world.say(YOU, FLAT, "yes", calling("confirm_draft", draft="D1"))
    assert "Next up, the Kirana bill:" in saved


def test_duplicates_need_keep_it() -> None:
    # C11
    world = World()
    flat(world, YOU, SAM)
    photo(world)
    world.say(YOU, FLAT, "yes", SAVE)
    warned = world.say(SAM, FLAT, "split", call("start_receipt"), image=receipt("restaurant_tip"))
    assert "Looks like Alex already added this." in warned
    world.say(SAM, FLAT, "yes", SAVE)
    assert "duplicate" in str(world.agent.requests[-1].history[-1][1][0].data["why"])
    kept = world.say(
        SAM, FLAT, "keep it", calling("confirm_draft", draft="@D", keep_duplicate=True)
    )
    assert "Saved" in kept


def test_anyone_in_the_group_can_cancel_and_the_bot_says_who() -> None:
    # C12
    world = World()
    flat(world, YOU, SAM)
    photo(world)
    cancelled = world.say(SAM, FLAT, "cancel", calling("cancel_draft", draft="@D"))
    assert cancelled == "Sam cancelled the Toit bill. Nothing was saved."


def test_reminder_after_a_day_and_expiry_after_three() -> None:
    # C13
    world = World()
    flat(world, YOU, SAM)
    photo(world)
    world.clock.advance(timedelta(hours=25))
    assert "Still waiting on the Toit bill." in world.tick()
    assert world.tick() == ""
    world.clock.advance(timedelta(days=3))
    assert world.tick() == "The Toit bill expired. Nothing was saved."


def test_a_one_member_group_suggests_asking_others_to_join() -> None:
    world = World()
    flat(world, YOU)
    assert "ask the others to join" in photo(world)


def test_foreign_currency_receipt_gets_a_warning() -> None:
    # C14
    world = World()
    flat(world, YOU, SAM)
    assert "USD" in photo(world, "usd_receipt")


def test_unreadable_photo_and_not_a_receipt() -> None:
    # C9
    world = World()
    flat(world, YOU, SAM)
    world.say(
        YOU,
        FLAT,
        "split",
        say("Couldn't read that, try another photo."),
        image=receipt("invalid_total_zero"),
    )
    assert "[photo: couldn't read it]" in world.turn_input
    world.say(YOU, FLAT, "lol", say(""), image=receipt("not_a_receipt"))
    assert "[photo: not a receipt]" in world.turn_input
    assert world.drafts(FLAT) == []


def test_a_member_moving_in_later_is_not_in_older_drafts() -> None:
    # B5
    world = World()
    flat(world, YOU, SAM)
    photo(world)
    world.say(PRIYA, None, "hi")
    world.say(PRIYA, FLAT, "join", call("join_group"))
    assert PRIYA.name not in world.say(YOU, FLAT, "show it", calling("get_bill", bill="@D"))


def test_a_removed_last_line_number_is_never_reused() -> None:
    # SPEC 4.4: a removed line leaves a gap; an added line takes the next number
    world = World()
    flat(world, YOU, SAM)
    world.say(YOU, FLAT, "cab", call("add_manual_bill", description="cab", amount="400"))
    edit(world, {"type": "AddLine", "name": "tip", "amount": "40"})
    edit(world, {"type": "RemoveLine", "line": "L2"})
    edit(world, {"type": "AddLine", "name": "water", "amount": "20"})
    assert [(x.name, x.position) for x in world.drafts(FLAT)[0].lines] == [
        ("cab", 1),
        ("water", 3),
    ]
    edit(world, {"type": "RemoveLine", "line": "L1"})
    edit(world, {"type": "RemoveLine", "line": "L3"})
    assert world.agent.requests[-1].history[-1][1][0].error == (
        "That's the only line: cancel the bill instead."
    )


def test_two_edits_in_one_turn_then_yes_saves() -> None:
    # SPEC 8.4: the version in the bot's last summary is the newest one it showed
    world = World()
    flat(world, YOU, SAM, RAJ)
    world.say(YOU, FLAT, "wine", call("add_manual_bill", description="wine", amount="300"))
    world.say(
        YOU,
        FLAT,
        "Raj had none, and Sam paid",
        calling(
            "edit_draft",
            draft="@D",
            change={"type": "UnassignLine", "line": "L1", "people": ["@Raj"]},
        ),
        calling("edit_draft", draft="@D", change={"type": "SetPayer", "person": "@Sam"}),
    )
    assert "Saved: wine" in world.say(YOU, FLAT, "yes", SAVE)


def test_a_draft_changed_twice_in_one_turn_is_shown_once() -> None:
    # SPEC 8.5: only the summary as it ended up
    world = World()
    flat(world, YOU, SAM)
    photo(world)
    shown = world.say(
        YOU,
        FLAT,
        "line 2 is 120 and Sam paid",
        calling(
            "edit_draft",
            draft="@D",
            change={"type": "SetLineAmount", "line": "L2", "amount": "120"},
        ),
        calling("edit_draft", draft="@D", change={"type": "SetPayer", "person": "@Sam"}),
    )
    assert shown.count("Toit, ") == 1
    assert "paid by Sam" in shown


def test_new_matches_are_listed_once_and_briefly() -> None:
    # F11: shown the first time, at most three by name, so a long receipt stays readable
    names = {"2% MLK GAL": "milk", "Bread": "loaf", "Red Wine": "wine", "Chips": "crisps"}
    world = World(canonical=FakeCanonicalizer(names))
    flat(world, YOU, SAM)
    first = photo(world, "grocery_taxed_mix")
    assert "Read as: 2% MLK GAL → milk; Bread → loaf; Red Wine → wine (and 1 more)." in first
    again = edit(world, {"type": "SetLineAmount", "line": "L2", "amount": "50"})
    assert "Read as:" not in again


def test_a_yes_quoting_an_older_summary_is_not_a_yes_to_the_new_one() -> None:
    # G4: Sam changed the bill; Alex's yes answers the summary he quoted
    world = World()
    flat(world, YOU, SAM, RAJ)
    first = photo(world)
    world.say(
        SAM,
        FLAT,
        "raj wasn't there",
        calling("edit_draft", draft="@D", change={"type": "RemovePeople", "people": ["@Raj"]}),
    )
    quoting = world.message(
        YOU, FLAT, "yes", addressed=False, reply_to_bot=True, quoted_text=first[:40]
    )
    reshown = world.send(quoting, [SAVE])
    assert [d.state for d in world.drafts(FLAT)] == [DraftState.REVIEWING]
    assert "Toit, ₹2,047.00, paid by Alex." in reshown
    assert "Raj" not in reshown.split("paid by Alex.", 1)[1]


def test_a_queued_draft_is_checked_for_duplicates_when_it_starts() -> None:
    # C11: Sam saves the Toit bill while Alex's copy waits in Alex's queue
    world = World()
    flat(world, YOU, SAM)
    photo(world, "grocery_taxed_mix")
    photo(world)
    world.say(SAM, FLAT, "split", call("start_receipt"), image=receipt("restaurant_tip"))
    world.say(SAM, FLAT, "keep it", calling("confirm_draft", draft="@D", keep_duplicate=True))
    started = world.say(YOU, FLAT, "yes", calling("confirm_draft", draft="D1"))
    assert "Next up, the Toit bill:" in started
    assert "Looks like Sam already added this." in started
    world.say(YOU, FLAT, "yes", SAVE)
    assert "duplicate" in str(world.agent.requests[-1].history[-1][1][0].data["why"])
