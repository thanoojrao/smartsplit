"""The CLI channel on the in-memory fakes: the demo flow end to end (SPEC section 11, K1)."""

import typer
from typer.testing import CliRunner

from smartsplit.entrypoints.cli import Bot, make_cli
from tests.integration.world import RECEIPTS, World

runner = CliRunner()


def cli_for(world: World, live_flags: list[bool] | None = None) -> typer.Typer:
    bot = Bot(world.bot, world.repository, world.settings.currency)

    def connect(live: bool) -> Bot:
        if live_flags is not None:
            live_flags.append(live)
        return bot

    return make_cli(connect)


def run(cli: typer.Typer, *args: str) -> str:
    result = runner.invoke(cli, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def test_the_demo_flow() -> None:
    cli = cli_for(World())
    assert "[you]\n  Hi Alex! I split bills." in run(cli, "person", "add", "Alex", "+919876500001")
    run(cli, "person", "add", "Sam", "+919876500002")
    created = run(cli, "group", "create", "Flat 4B", "--as", "Alex")
    assert created.startswith("[Flat 4B]\n  Hi Flat 4B! Alex is in.")
    assert run(cli, "member", "add", "Flat 4B", "Sam") == "[Flat 4B]\n  Sam joined Flat 4B.\n"
    receipt = str(RECEIPTS / "restaurant_tip.json")
    shown = run(cli, "receipt", "add", receipt, "--as", "Alex", "--in", "Flat 4B")
    assert "  Toit, ₹2,047.00, paid by Alex." in shown
    saved = run(cli, "say", "yes", "--as", "Alex", "--in", "Flat 4B")
    assert "Sam owes Alex ₹1,023.50" in saved
    assert run(cli, "balances", "--as", "Sam") == (
        "Alex: you owe ₹1,023.50\n  Flat 4B: you owe ₹1,023.50\n"
    )
    run(cli, "say", "I don't drink milk", "--as", "Sam", "--in", "personal")
    assert run(cli, "rules", "--about", "Sam") == "milk: exclude (everywhere, stated)\n"
    assert run(cli, "tick") == ""


def test_messages_to_other_peoples_chats_are_labelled() -> None:
    cli = cli_for(World())
    run(cli, "person", "add", "Alex", "+919876500001")
    run(cli, "person", "add", "Sam", "+919876500002")
    run(cli, "say", "add Sam +919876500002", "--as", "Alex", "--in", "personal")
    run(cli, "say", "chai 100 with Sam", "--as", "Alex", "--in", "personal")
    out = run(cli, "say", "yes", "--as", "Alex", "--in", "personal")
    assert "[you]\n  Saved: chai" in out
    assert "[to Sam]\n  Alex added chai" in out


def test_receipt_with_a_caption_and_the_live_flag() -> None:
    flags: list[bool] = []
    cli = cli_for(World(), flags)
    run(cli, "person", "add", "Alex", "+919876500001")
    run(cli, "person", "add", "Sam", "+919876500002")
    run(cli, "say", "add Sam +919876500002", "--as", "Alex", "--in", "personal")
    receipt = str(RECEIPTS / "restaurant_tip.json")
    out = run(
        cli,
        "--live",
        "receipt",
        "add",
        receipt,
        "--as",
        "Alex",
        "--in",
        "personal",
        "--caption",
        "split with Sam",
    )
    assert "Sam: ₹1,023.50" in out
    assert flags[-1] is True and flags[0] is False


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
