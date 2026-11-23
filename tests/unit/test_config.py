"""Settings from the environment (SPEC section 12.1)."""

import pytest
from pydantic import ValidationError

from smartsplit.config import Settings


def test_defaults_and_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x/y")
    monkeypatch.setenv("SMARTSPLIT_API_TOKEN", "s3cret")
    monkeypatch.setenv("SMARTSPLIT_CURRENCY", "USD")

    settings = Settings()

    assert settings.currency == "USD"
    assert settings.api_token is not None
    assert settings.api_token.get_secret_value() == "s3cret"
    assert "s3cret" not in repr(settings)
    assert settings.fuzzy_threshold == 85


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SMARTSPLIT_TIMEZONE", "Mars/Olympus"),
        ("SMARTSPLIT_CURRENCY", "rupees"),
        ("SMARTSPLIT_FUZZY_THRESHOLD", "101"),
        ("SMARTSPLIT_MAX_QUEUED_DRAFTS", "-1"),
    ],
)
def test_bad_settings_fail_at_startup(
    monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x/y")
    monkeypatch.setenv(name, value)

    with pytest.raises(ValidationError):
        Settings()


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError):
        Settings()
