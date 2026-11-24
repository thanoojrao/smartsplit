"""The API process: `uvicorn --factory smartsplit.entrypoints.api.server:from_environment`.

It refuses to start without `SMARTSPLIT_API_TOKEN`, an API key and `SMARTSPLIT_BOT_LINK`
(SPEC 11, 12.1), and logs one INFO line per message.
"""

import logging

from fastapi import FastAPI

from smartsplit.config import PLACEHOLDER_BOT_LINK, Settings
from smartsplit.entrypoints.api import create_app
from smartsplit.entrypoints.wiring import build


def turn_logs() -> None:
    """The per-turn lines are INFO, which uvicorn's logging config would drop (SPEC 12.4)."""
    logger = logging.getLogger("smartsplit")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)


def from_environment() -> FastAPI:
    """Settings from the environment, wired for real."""
    settings = Settings()
    if settings.api_token is None:
        raise SystemExit("SMARTSPLIT_API_TOKEN is not set; the API won't start without it")
    if settings.anthropic_api_key is None:
        raise SystemExit("ANTHROPIC_API_KEY is not set; the API won't start without it")
    if settings.bot_link == PLACEHOLDER_BOT_LINK:
        raise SystemExit("SMARTSPLIT_BOT_LINK is not set; people would get a broken link")
    turn_logs()
    built = build(settings)
    return create_app(
        built.orchestrator,
        built.repository,
        api_token=settings.api_token.get_secret_value(),
        max_image_bytes=settings.max_image_bytes,
        ready=built.ready,
    )
