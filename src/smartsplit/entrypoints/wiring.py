"""Composition root shared by the CLI and the API: settings in, an Orchestrator out."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from smartsplit.adapters.db.migrate import upgrade_to_head
from smartsplit.adapters.db.repository import connect
from smartsplit.adapters.files import FileImageStore
from smartsplit.adapters.llm.agent import AnthropicAgent
from smartsplit.adapters.llm.canonicalizer import AnthropicCanonicalizer
from smartsplit.adapters.llm.receipts import AnthropicReceiptParser, anthropic_client
from smartsplit.adapters.system import SystemClock, UuidIds
from smartsplit.config import Settings
from smartsplit.ports.agent import AgentModel, AgentRequest, ModelStep
from smartsplit.ports.images import ImageStore
from smartsplit.ports.llm import Canonicalizer, ParsedReceipt, ReceiptParser
from smartsplit.ports.repository import Repository
from smartsplit.ports.system import Clock
from smartsplit.services import Orchestrator, OrchestratorSettings


@dataclass(frozen=True, slots=True)
class App:
    orchestrator: Orchestrator
    repository: Repository
    images: ImageStore
    clock: Clock
    settings: Settings
    ready: Callable[[], bool]
    """The database answers and is migrated (`/readyz`)."""


@dataclass(frozen=True, slots=True)
class Models:
    """Everything that calls a model: the real ones, or the demo's scripted stand-ins."""

    parser: ReceiptParser
    canonicalizer: Canonicalizer
    agent: AgentModel


def orchestrator_settings(settings: Settings) -> OrchestratorSettings:
    """The one place config becomes what the conversation logic sees."""
    return OrchestratorSettings(
        currency=settings.currency,
        default_region=settings.default_region,
        timezone=settings.timezone,
        bot_link=settings.bot_link,
        fuzzy_threshold=settings.fuzzy_threshold,
        min_line_confidence=settings.min_line_confidence,
        max_receipt_lines=settings.max_receipt_lines,
        max_amount_cents=settings.max_amount_cents,
        max_queued_drafts=settings.max_queued_drafts,
        llm_calls_per_person_per_day=settings.llm_calls_per_person_per_day,
        llm_calls_per_day=settings.llm_calls_per_day,
        llm_timeout_seconds=settings.llm_timeout_seconds,
        message_seconds=settings.message_seconds,
        lock_wait_seconds=settings.lock_wait_seconds,
        max_image_bytes=settings.max_image_bytes,
        agent_max_steps=settings.agent_max_steps,
        chat_history_messages=settings.chat_history_messages,
        chat_history_keep=settings.chat_history_keep,
        chat_history_days=settings.chat_history_days,
        max_notifications_per_day=settings.max_notifications_per_day,
    )


NEEDS_KEY = "This needs ANTHROPIC_API_KEY (or SMARTSPLIT_ANTHROPIC_API_KEY)."


class _NoKey:
    """Stands in for every model port when no key is set: operator commands (balances, rules,
    tick) still work, and the first model call stops with a clear message."""

    def parse(
        self, image: bytes, mime_type: str, currency: str, timeout_seconds: float
    ) -> ParsedReceipt:
        raise SystemExit(NEEDS_KEY)

    def canonicalize(self, name: str, known_keys: Sequence[str]) -> str:
        raise SystemExit(NEEDS_KEY)

    def step(self, request: AgentRequest) -> ModelStep:
        raise SystemExit(NEEDS_KEY)


def real_models(settings: Settings) -> Models:
    """One client for every model call, with the configured model and limits; without a key,
    a stand-in that refuses to call the model."""
    if settings.anthropic_api_key is None:
        missing = _NoKey()
        return Models(missing, missing, missing)
    client = anthropic_client(
        settings.anthropic_api_key.get_secret_value(), settings.llm_timeout_seconds
    )
    model, max_tokens = settings.llm_model, settings.llm_max_tokens
    return Models(
        AnthropicReceiptParser(
            client, model=model, max_tokens=max_tokens, max_lines=settings.max_receipt_lines
        ),
        AnthropicCanonicalizer(
            client, model=model, max_tokens=max_tokens, timeout_seconds=settings.llm_timeout_seconds
        ),
        AnthropicAgent(client, model=model, max_tokens=max_tokens),
    )


def build(settings: Settings, models: Models | None = None) -> App:
    """Postgres (migrated to the latest schema), the image directory, and the real models
    unless others are given (the scripted demo)."""
    url = settings.database_url.get_secret_value()
    upgrade_to_head(url)
    repository = connect(url)
    chosen = models or real_models(settings)
    images = FileImageStore(settings.image_dir)
    clock = SystemClock()
    orchestrator = Orchestrator(
        repository=repository,
        images=images,
        parser=chosen.parser,
        canonicalizer=chosen.canonicalizer,
        agent=chosen.agent,
        clock=clock,
        ids=UuidIds(),
        settings=orchestrator_settings(settings),
    )
    return App(orchestrator, repository, images, clock, settings, repository.ready)
