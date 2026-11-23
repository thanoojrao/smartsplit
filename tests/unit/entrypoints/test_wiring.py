"""Configuration reaches the conversation logic, and `--live` picks the model (K2, K9)."""

from datetime import timedelta

import pytest

from smartsplit.adapters.fakes.interpreter import KeywordInterpreter
from smartsplit.adapters.fakes.llm import FakeReceiptParser
from smartsplit.adapters.llm.commands import AnthropicCommandInterpreter
from smartsplit.adapters.llm.receipts import AnthropicReceiptParser
from smartsplit.config import Settings
from smartsplit.entrypoints.wiring import model_adapters, orchestrator_settings
from smartsplit.services import OrchestratorSettings

CHANGED = {
    "SMARTSPLIT_CURRENCY": "USD",
    "SMARTSPLIT_DEFAULT_REGION": "US",
    "SMARTSPLIT_TIMEZONE": "America/New_York",
    "SMARTSPLIT_FUZZY_THRESHOLD": "77",
    "SMARTSPLIT_MIN_LINE_CONFIDENCE": "0.4",
    "SMARTSPLIT_MAX_RECEIPT_LINES": "42",
    "SMARTSPLIT_MAX_AMOUNT_CENTS": "123456",
    "SMARTSPLIT_MAX_QUEUED_DRAFTS": "5",
    "SMARTSPLIT_LLM_CALLS_PER_PERSON_PER_DAY": "9",
    "SMARTSPLIT_MAX_NOTIFICATIONS_PER_DAY": "7",
    "SMARTSPLIT_INVITE_TEMPLATE": "come join",
}


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x/y")
    for key_name in ("SMARTSPLIT_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key_name, raising=False)  # a real key in the shell must not leak in
    for name, value in CHANGED.items():
        monkeypatch.setenv(name, value)
    return Settings()


def test_every_setting_reaches_the_orchestrator(settings: Settings) -> None:
    assert orchestrator_settings(settings) == OrchestratorSettings(
        currency="USD",
        default_region="US",
        timezone="America/New_York",
        fuzzy_threshold=77,
        min_line_confidence=0.4,
        max_receipt_lines=42,
        max_amount_cents=123456,
        max_queued_drafts=5,
        llm_calls_per_person_per_day=9,
        max_notifications_per_day=7,
        invite_template="come join",
        draft_reminder_after=timedelta(hours=24),
        draft_expires_after=timedelta(days=3),
    )


def test_offline_uses_the_stand_ins(settings: Settings) -> None:
    parser, interpreter = model_adapters(settings, live=False)
    assert isinstance(parser, FakeReceiptParser)
    assert isinstance(interpreter, KeywordInterpreter)


def test_live_uses_the_model_and_needs_a_key(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
        model_adapters(settings, live=True)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    parser, interpreter = model_adapters(Settings(), live=True)
    assert isinstance(parser, AnthropicReceiptParser)
    assert isinstance(interpreter, AnthropicCommandInterpreter)
