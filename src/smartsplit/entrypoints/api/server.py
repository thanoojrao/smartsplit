"""The API process: `uvicorn --factory smartsplit.entrypoints.api.server:from_environment`.

It refuses to start without `SMARTSPLIT_API_TOKEN`. With `ANTHROPIC_API_KEY` set it uses the
real model; without one it runs on the offline stand-ins, for trying the API locally.
"""

from fastapi import FastAPI

from smartsplit.config import Settings
from smartsplit.entrypoints.api import create_app
from smartsplit.entrypoints.wiring import build


def from_environment() -> FastAPI:
    """Settings from the environment, wired for real (see the module docstring)."""
    settings = Settings()
    if settings.api_token is None:
        raise SystemExit("SMARTSPLIT_API_TOKEN is not set; the API won't start without it")
    built = build(settings, live=settings.anthropic_api_key is not None)
    return create_app(
        built.orchestrator,
        built.repository,
        api_token=settings.api_token.get_secret_value(),
        max_image_bytes=settings.max_image_bytes,
    )
