"""The real composition roots on Postgres: the console script and the API factory."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from smartsplit.entrypoints.api.server import from_environment
from smartsplit.entrypoints.cli import app

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
    # K1: no key; the real tools and database; Raj's rule keeps him off the milk
    result = CliRunner().invoke(app, ["demo"])
    assert result.exit_code == 0, result.output
    assert "Raj skipped: 2% MLK GAL" in result.output
    assert "Waiting for Sam to say yes." in result.output
    assert "  Recorded." in result.output
    assert "[to Alex]" in result.output


def test_operator_commands_need_no_key_but_talking_does(environment: None) -> None:
    runner = CliRunner()
    assert runner.invoke(app, ["tick"]).exit_code == 0
    said = runner.invoke(app, ["person", "add", "Alex", "+919876500001"])
    assert said.exit_code != 0
    assert "This needs ANTHROPIC_API_KEY" in said.output


def test_the_api_factory(
    environment: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    with pytest.raises(SystemExit, match="SMARTSPLIT_API_TOKEN"):
        from_environment()
    monkeypatch.setenv("SMARTSPLIT_API_TOKEN", "t0ken")
    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
        from_environment()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    monkeypatch.delenv("SMARTSPLIT_BOT_LINK", raising=False)
    with pytest.raises(SystemExit, match="SMARTSPLIT_BOT_LINK"):
        from_environment()
    monkeypatch.setenv("SMARTSPLIT_BOT_LINK", "https://wa.me/15550001")
    api = TestClient(from_environment())
    assert api.get("/healthz").json() == {"status": "ok"}
    assert api.get("/readyz").json() == {"status": "ready"}
    auth = {"Authorization": "Bearer t0ken"}
    batch = api.post("/v1/tick", headers=auth).json()
    assert batch["messages"] == []
    assert api.post(f"/v1/tick/{batch['batch_id']}/ack", headers=auth).status_code == 204
    chatter = {
        "message_id": "m1",
        "conversation": {"channel": "whatsapp", "ref": "g1"},
        "conversation_kind": "group",
        "sender_ref": "+919876500001",
        "sender_name": "Alex",
        "addressed_to_bot": False,
        "reply_to_bot": False,
        "text": "lunch?",
    }
    assert api.post("/v1/messages", headers=auth, json=chatter).json() == []
    # SPEC 12.4: the factory makes the INFO line visible without any test setup
    assert any("outcome=silent" in r.getMessage() for r in caplog.records)
