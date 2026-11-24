"""Configuration reaches the conversation logic, and the real models need a key (K2, K9)."""

import re

import pytest

from smartsplit.adapters.llm.agent import AnthropicAgent
from smartsplit.adapters.llm.canonicalizer import AnthropicCanonicalizer
from smartsplit.adapters.llm.receipts import AnthropicReceiptParser
from smartsplit.config import Settings
from smartsplit.entrypoints.wiring import NEEDS_KEY, orchestrator_settings, real_models
from smartsplit.ports.agent import AgentRequest
from smartsplit.services import OrchestratorSettings

CHANGED = {
    "SMARTSPLIT_CURRENCY": "USD",
    "SMARTSPLIT_DEFAULT_REGION": "US",
    "SMARTSPLIT_TIMEZONE": "America/New_York",
    "SMARTSPLIT_BOT_LINK": "https://wa.me/1555?text=hi",
    "SMARTSPLIT_FUZZY_THRESHOLD": "77",
    "SMARTSPLIT_MIN_LINE_CONFIDENCE": "0.4",
    "SMARTSPLIT_MAX_RECEIPT_LINES": "42",
    "SMARTSPLIT_MAX_AMOUNT_CENTS": "123456",
    "SMARTSPLIT_MAX_QUEUED_DRAFTS": "5",
    "SMARTSPLIT_LLM_CALLS_PER_PERSON_PER_DAY": "9",
    "SMARTSPLIT_LLM_CALLS_PER_DAY": "99",
    "SMARTSPLIT_LLM_TIMEOUT_SECONDS": "12",
    "SMARTSPLIT_MESSAGE_SECONDS": "45",
    "SMARTSPLIT_AGENT_MAX_STEPS": "4",
    "SMARTSPLIT_CHAT_HISTORY_MESSAGES": "8",
    "SMARTSPLIT_CHAT_HISTORY_KEEP": "40",
    "SMARTSPLIT_CHAT_HISTORY_DAYS": "20",
    "SMARTSPLIT_MAX_NOTIFICATIONS_PER_DAY": "7",
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
        bot_link="https://wa.me/1555?text=hi",
        fuzzy_threshold=77,
        min_line_confidence=0.4,
        max_receipt_lines=42,
        max_amount_cents=123456,
        max_queued_drafts=5,
        llm_calls_per_person_per_day=9,
        llm_calls_per_day=99,
        llm_timeout_seconds=12,
        message_seconds=45,
        agent_max_steps=4,
        chat_history_messages=8,
        chat_history_keep=40,
        chat_history_days=20,
        max_notifications_per_day=7,
    )


def test_spec_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    # SPEC 12.1
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x/y")
    assert orchestrator_settings(Settings()) == OrchestratorSettings(
        bot_link="https://wa.me/<bot-number>?text=hi"
    )


def test_without_a_key_the_first_model_call_stops_with_a_clear_message(
    settings: Settings,
) -> None:
    models = real_models(settings)
    with pytest.raises(SystemExit, match=re.escape(NEEDS_KEY)):
        models.agent.step(AgentRequest("", (), "", (), 1.0))
    with pytest.raises(SystemExit, match=re.escape(NEEDS_KEY)):
        models.canonicalizer.canonicalize("milk", ())
    with pytest.raises(SystemExit, match=re.escape(NEEDS_KEY)):
        models.parser.parse(b"", "image/png", "USD", 1.0)


def test_with_a_key_every_model_port_is_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x/y")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-real")
    models = real_models(Settings())
    assert isinstance(models.parser, AnthropicReceiptParser)
    assert isinstance(models.canonicalizer, AnthropicCanonicalizer)
    assert isinstance(models.agent, AnthropicAgent)
    # chat on Haiku, receipts on Sonnet (DECISIONS M12)
    assert (models.agent.model, models.canonicalizer.model) == ("claude-haiku-5-5",) * 2
    assert models.parser.model == "claude-sonnet-5-5"
    monkeypatch.setenv("SMARTSPLIT_LLM_MODEL", "chat-model")
    monkeypatch.setenv("SMARTSPLIT_RECEIPT_MODEL", "receipt-model")
    chosen = real_models(Settings())
    assert isinstance(chosen.agent, AnthropicAgent)
    assert isinstance(chosen.parser, AnthropicReceiptParser)
    assert (chosen.agent.model, chosen.parser.model) == ("chat-model", "receipt-model")
