"""Composition root shared by the CLI and the API: settings in, an Orchestrator out."""

from dataclasses import dataclass

from smartsplit.adapters.db.migrate import upgrade_to_head
from smartsplit.adapters.db.repository import connect
from smartsplit.adapters.fakes.interpreter import KeywordInterpreter
from smartsplit.adapters.fakes.llm import DEMO_ITEMS, FakeCanonicalizer, FakeReceiptParser
from smartsplit.adapters.files import FileImageStore
from smartsplit.adapters.llm.commands import AnthropicCommandInterpreter
from smartsplit.adapters.llm.receipts import AnthropicReceiptParser, anthropic_client
from smartsplit.adapters.system import SystemClock, UuidIds
from smartsplit.config import Settings
from smartsplit.ports.images import ImageStore
from smartsplit.ports.llm import CommandInterpreter, ReceiptParser
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


def orchestrator_settings(settings: Settings) -> OrchestratorSettings:
    """The one place config becomes what the conversation logic sees."""
    return OrchestratorSettings(
        currency=settings.currency,
        default_region=settings.default_region,
        timezone=settings.timezone,
        fuzzy_threshold=settings.fuzzy_threshold,
        min_line_confidence=settings.min_line_confidence,
        max_receipt_lines=settings.max_receipt_lines,
        max_amount_cents=settings.max_amount_cents,
        max_queued_drafts=settings.max_queued_drafts,
        llm_calls_per_person_per_day=settings.llm_calls_per_person_per_day,
        max_notifications_per_day=settings.max_notifications_per_day,
        invite_template=settings.invite_template,
    )


def model_adapters(settings: Settings, *, live: bool) -> tuple[ReceiptParser, CommandInterpreter]:
    """The real model (one client for both, the configured model and limits) or the offline
    stand-ins, which know the recorded receipts' item names."""
    if not live:
        return (
            FakeReceiptParser(settings.max_receipt_lines),
            KeywordInterpreter(FakeCanonicalizer(DEMO_ITEMS)),
        )
    if settings.anthropic_api_key is None:
        raise SystemExit("--live needs ANTHROPIC_API_KEY")
    client = anthropic_client(
        settings.anthropic_api_key.get_secret_value(), settings.llm_timeout_seconds
    )
    parser = AnthropicReceiptParser(
        client,
        model=settings.llm_model,
        max_tokens=settings.llm_max_tokens,
        max_lines=settings.max_receipt_lines,
    )
    interpreter = AnthropicCommandInterpreter(
        client, model=settings.llm_model, max_tokens=settings.llm_max_tokens
    )
    return parser, interpreter


def build(settings: Settings, *, live: bool) -> App:
    """Postgres (migrated to the latest schema), the image directory, and either the real
    model (`live`) or the offline stand-ins: the keyword interpreter and a parser that
    reads recorded receipts (JSON)."""
    url = settings.database_url.get_secret_value()
    upgrade_to_head(url)
    repository = connect(url)
    parser, interpreter = model_adapters(settings, live=live)
    images = FileImageStore(settings.image_dir)
    clock = SystemClock()
    orchestrator = Orchestrator(
        repository=repository,
        images=images,
        parser=parser,
        interpreter=interpreter,
        clock=clock,
        ids=UuidIds(),
        settings=orchestrator_settings(settings),
    )
    return App(orchestrator, repository, images, clock, settings)
