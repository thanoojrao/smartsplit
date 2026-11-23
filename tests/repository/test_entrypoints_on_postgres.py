"""The real composition roots on Postgres: the console script and the API factory."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from smartsplit.entrypoints.api.server import from_environment
from smartsplit.entrypoints.cli import app
from tests.integration.world import RECEIPTS

pytestmark = pytest.mark.db


@pytest.fixture
def environment(
    clean_pg: object, pg_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setenv("SMARTSPLIT_IMAGE_DIR", str(tmp_path / "images"))
    monkeypatch.delenv("SMARTSPLIT_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SMARTSPLIT_API_TOKEN", raising=False)


def test_the_console_script_runs_the_demo(environment: None) -> None:
    runner = CliRunner()

    def run(*args: str) -> str:
        result = runner.invoke(app, list(args))
        assert result.exit_code == 0, result.output
        return result.output

    # the README walkthrough: Raj's rule keeps him off the milk
    run("person", "add", "Alex", "+919876500001")
    run("person", "add", "Sam", "+919876500002")
    run("person", "add", "Raj", "+919876500003")
    run("group", "create", "Flat 4B", "--as", "Alex")
    run("member", "add", "Flat 4B", "Sam")
    run("member", "add", "Flat 4B", "Raj")
    run("say", "Raj doesn't drink milk", "--as", "Raj", "--in", "Flat 4B")
    receipt = str(RECEIPTS / "grocery_taxed_mix.json")
    shown = run("receipt", "add", receipt, "--as", "Alex", "--in", "Flat 4B")
    assert "Raj skipped: 2% MLK GAL (group rule)" in shown
    details = run("say", "details", "--as", "Alex", "--in", "Flat 4B")
    assert "1. 2% MLK GAL ₹120.00: Alex and Sam" in details
    assert "Sam owes Alex" in run("say", "yes", "--as", "Alex", "--in", "Flat 4B")
    assert "Alex: you owe" in run("balances", "--as", "Sam")


def test_live_needs_a_key(environment: None) -> None:
    result = CliRunner().invoke(app, ["--live", "tick"])
    assert result.exit_code != 0
    assert "--live needs ANTHROPIC_API_KEY" in result.output


def test_the_api_factory(environment: None, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit, match="SMARTSPLIT_API_TOKEN"):
        from_environment()
    monkeypatch.setenv("SMARTSPLIT_API_TOKEN", "t0ken")
    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
        from_environment()
    monkeypatch.setenv("SMARTSPLIT_OFFLINE", "1")
    api = TestClient(from_environment())
    assert api.get("/healthz").json() == {"status": "ok"}
    assert api.post("/v1/tick", headers={"Authorization": "Bearer t0ken"}).json() == []
