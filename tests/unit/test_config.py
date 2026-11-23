"""Settings from the environment (SPEC section 12.1)."""

import os

import pytest
from pydantic import ValidationError

from smartsplit.config import Settings


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings in the developer's shell must not leak into these tests."""
    for name in list(os.environ):
        if name.startswith("SMARTSPLIT_") or name == "ANTHROPIC_API_KEY":
            monkeypatch.delenv(name)


def test_defaults_and_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:dbpass@x/y")
    monkeypatch.setenv("SMARTSPLIT_API_TOKEN", "s3cret")
    monkeypatch.setenv("SMARTSPLIT_CURRENCY", "USD")

    settings = Settings()

    assert settings.currency == "USD"
    assert settings.api_token is not None
    assert settings.api_token.get_secret_value() == "s3cret"
    assert "s3cret" not in repr(settings)
    assert "dbpass" not in repr(settings)
    assert settings.database_url.get_secret_value().endswith("@x/y")
    assert settings.fuzzy_threshold == 85
    assert settings.anthropic_api_key is None
    assert settings.invite_template.endswith("https://wa.me/<bot-number>?text=hi")


def test_an_empty_key_in_a_copied_env_file_counts_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x/y")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("SMARTSPLIT_API_TOKEN", "")

    settings = Settings()

    assert settings.anthropic_api_key is None
    assert settings.api_token is None


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("SMARTSPLIT_TIMEZONE", "Mars/Olympus"),
        ("SMARTSPLIT_CURRENCY", "rupees"),
        ("SMARTSPLIT_FUZZY_THRESHOLD", "101"),
        ("SMARTSPLIT_FUZZY_THRESHOLD", "0"),
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


def test_the_project_key_name_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://x/y")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "plain")
    monkeypatch.setenv("SMARTSPLIT_ANTHROPIC_API_KEY", "project")
    key = Settings().anthropic_api_key
    assert key is not None
    assert key.get_secret_value() == "project"
    monkeypatch.delenv("SMARTSPLIT_ANTHROPIC_API_KEY")
    key = Settings().anthropic_api_key
    assert key is not None
    assert key.get_secret_value() == "plain"
