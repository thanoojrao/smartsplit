"""The API process: `uvicorn --factory smartsplit.entrypoints.api.server:from_environment`.

It refuses to start without `SMARTSPLIT_API_TOKEN`, and without `ANTHROPIC_API_KEY` unless
`SMARTSPLIT_OFFLINE=1` asks for the offline stand-ins: a gateway must never end up on them by
accident.
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
    if not settings.offline and settings.anthropic_api_key is None:
        raise SystemExit("Set ANTHROPIC_API_KEY, or SMARTSPLIT_OFFLINE=1 to use the stand-ins")
    built = build(settings, live=not settings.offline)
    return create_app(
        built.orchestrator,
        built.repository,
        api_token=settings.api_token.get_secret_value(),
        max_image_bytes=settings.max_image_bytes,
    )
