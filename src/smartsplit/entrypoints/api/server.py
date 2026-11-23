"""The API process: `uvicorn --factory smartsplit.entrypoints.api.server:from_environment`.

It refuses to start without `SMARTSPLIT_API_TOKEN` and an API key (SPEC 11).
"""

from fastapi import FastAPI

from smartsplit.config import Settings
from smartsplit.entrypoints.api import create_app
from smartsplit.entrypoints.wiring import build


def from_environment() -> FastAPI:
    """Settings from the environment, wired for real."""
    settings = Settings()
    if settings.api_token is None:
        raise SystemExit("SMARTSPLIT_API_TOKEN is not set; the API won't start without it")
    if settings.anthropic_api_key is None:
        raise SystemExit("ANTHROPIC_API_KEY is not set; the API won't start without it")
    built = build(settings)
    return create_app(
        built.orchestrator,
        built.repository,
        api_token=settings.api_token.get_secret_value(),
        max_image_bytes=settings.max_image_bytes,
    )
