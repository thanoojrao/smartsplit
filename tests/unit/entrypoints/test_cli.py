"""The CLI channel on the in-memory fakes: the demo flow end to end (SPEC section 11, K1)."""

from datetime import timedelta

import typer
from typer.testing import CliRunner

from smartsplit.adapters.fakes.agent import ScriptedAgent, call, say
from smartsplit.adapters.fakes.llm import DEMO_ITEMS, FakeCanonicalizer
from smartsplit.entrypoints.cli import Bot, make_cli
from tests.integration.world import RECEIPTS, World, calling

runner = CliRunner()


def bot_for(world: World, max_image_bytes: int) -> Bot:
    assert world.images is not None
    return Bot(
        world.bot,
        world.repository,
        world.images,
        world.clock,
        world.settings.currency,
        world.settings.default_region,
        max_image_bytes,
    )


def cli_for(world: World, max_image_bytes: int = 5_000) -> typer.Typer:
    def connect_demo(agent: ScriptedAgent) -> Bot:
        return bot_for(World(model=agent, canonical=FakeCanonicalizer(DEMO_ITEMS)), max_image_bytes)

    return make_cli(lambda: bot_for(world, max_image_bytes), connect_demo)


def run(cli: typer.Typer, *args: str) -> str:
    result = runner.invoke(cli, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def test_the_cli_flow() -> None:
    world = World()
    cli = cli_for(world)
    added = run(cli, "person", "add", "Alex", "+919876500001")
    assert added.startswith("[you]\n  Hi Alex! I split bills")
    run(cli, "person", "add", "Sam", "+919876500002")
    created = run(cli, "group", "create", "Flat 4B", "--as", "Alex")
    assert created.startswith("[Flat 4B]\n  Hi Flat 4B! I split bills")
    assert 'reply to this message with "join"' in created
    world.agent.queue(call("join_group"))
    assert run(cli, "member", "add", "Flat 4B", "Sam") == "[Flat 4B]\n  Sam joined Flat 4B.\n"
    world.agent.queue(call("start_receipt"))
    receipt = str(RECEIPTS / "restaurant_tip.json")
    shown = run(cli, "receipt", "add", receipt, "--as", "Alex", "--in", "Flat 4B")
    assert "  Toit, ₹2,047.00, paid by Alex." in shown
    world.agent.queue(calling("confirm_draft", draft="@D"))
    saved = run(cli, "say", "yes", "--as", "Alex", "--in", "Flat 4B")
    assert "Sam owes Alex ₹1,023.50" in saved
    assert run(cli, "balances", "--as", "Sam") == (
        "Alex: you owe ₹1,023.50\n  Flat 4B: you owe ₹1,023.50\n"
    )
    world.agent.queue(call("add_rule", subject="me", item="milk", kind="exclude"))
    run(cli, "say", "I don't drink milk", "--as", "Sam", "--in", "personal")
    assert run(cli, "rules", "--about", "Sam") == "milk: exclude (everywhere, set by Sam)\n"
    assert run(cli, "tick") == ""


def test_messages_to_other_peoples_chats_are_labelled() -> None:
    world = World()
    cli = cli_for(world)
    run(cli, "person", "add", "Alex", "+919876500001")
    run(cli, "person", "add", "Sam", "+919876500002")
    world.agent.queue(call("add_person", name="Sam", phone="+919876500002"))
    run(cli, "say", "add Sam +919876500002", "--as", "Alex", "--in", "personal")
    world.agent.queue(calling("add_manual_bill", description="chai", amount="100", people=["@Sam"]))
    run(cli, "say", "chai 100 with Sam", "--as", "Alex", "--in", "personal")
    world.agent.queue(calling("confirm_draft", draft="@D"))
    out = run(cli, "say", "yes", "--as", "Alex", "--in", "personal")
    assert "[you]\n  Saved: chai" in out
    assert "[to Sam]\n  Alex added chai" in out


def test_the_scripted_demo_needs_no_key() -> None:
    # K1
    out = run(cli_for(World()), "demo")
    assert "Raj skipped: 2% MLK GAL" in out
    assert "# Sam records a payment; it waits for his yes" in out
    assert "  Recorded." in out
    assert out.endswith("[you]\n  Raj owes you ₹50.00\n")


def test_unknown_people_are_refused() -> None:
    cli = cli_for(World())
    result = runner.invoke(cli, ["balances", "--as", "Nobody"])
    assert result.exit_code != 0
    assert "no person called Nobody" in result.output
    result = runner.invoke(cli, ["rules", "--about", "Nobody"])
    assert result.exit_code != 0


def test_nothing_owed_and_no_rules() -> None:
    cli = cli_for(World())
    run(cli, "person", "add", "Alex", "+919876500001")
    assert run(cli, "balances", "--as", "Alex") == "All settled up.\n"
    assert run(cli, "rules", "--about", "Alex") == "No rules.\n"


def test_input_the_cli_refuses() -> None:
    cli = cli_for(World(), max_image_bytes=100)
    bad_phone = runner.invoke(cli, ["person", "add", "Bob", "notaphone"])
    assert bad_phone.exit_code != 0 and "isn't a phone number" in bad_phone.output
    big = RECEIPTS / "grocery_taxed_mix.json"
    assert big.stat().st_size > 100
    run(cli, "person", "add", "Alex", "+919876500001")
    too_large = runner.invoke(cli, ["receipt", "add", str(big), "--as", "Alex", "--in", "personal"])
    assert too_large.exit_code != 0 and "too large" in too_large.output


def test_replies_in_your_own_chat_are_yours() -> None:
    world = World()
    cli = cli_for(world)
    run(cli, "person", "add", "Alex", "+919876500001")
    world.agent.queue(say("Hm?"))
    assert run(cli, "say", "what", "--as", "Alex", "--in", "personal").startswith("[you]\n")
    assert run(cli, "say", "hi", "--as", "Nobody", "--in", "personal").startswith("[you]\n")


def test_old_images_are_pruned() -> None:
    world = World()
    cli = cli_for(world)
    run(cli, "person", "add", "Alex", "+919876500001")
    receipt = str(RECEIPTS / "total_mismatch.json")
    run(cli, "receipt", "add", receipt, "--as", "Alex", "--in", "personal")
    assert run(cli, "images", "prune", "--older-than-days", "30") == "Deleted 0 images.\n"
    world.clock.advance(timedelta(days=31))
    assert run(cli, "images", "prune", "--older-than-days", "30") == "Deleted 1 images.\n"
