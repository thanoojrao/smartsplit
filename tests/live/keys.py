"""The API key for live runs, under either name the app accepts (see config.Settings)."""

import os


def live_key() -> str | None:
    """None lets the SDK report the missing key itself."""
    return os.environ.get("SMARTSPLIT_ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
