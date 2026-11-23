"""Settings from the environment (SPEC section 12.1). Read only by entrypoints, then injected."""

from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every setting has a safe default except the database URL; secrets are SecretStr.

    The API refuses to start without `api_token` (checked by the API entrypoint).
    """

    model_config = SettingsConfigDict(env_prefix="SMARTSPLIT_", extra="ignore")

    database_url: SecretStr = Field(validation_alias="DATABASE_URL")
    """Usually holds the database password, so it is a secret too."""
    anthropic_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("SMARTSPLIT_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
    )
    """`SMARTSPLIT_ANTHROPIC_API_KEY` wins: hosts that run Claude Code reserve the plain name."""
    api_token: SecretStr | None = None
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    default_region: str = Field(default="IN", pattern=r"^[A-Z]{2}$")
    timezone: str = "Asia/Kolkata"
    llm_model: str = "claude-sonnet-5-5"
    llm_timeout_seconds: float = Field(default=30, gt=0)
    message_seconds: float = Field(default=60, gt=0)
    """The whole message: photo read, lock wait and agent loop (SPEC 12.2)."""
    agent_max_steps: int = Field(default=6, ge=1, le=20)
    llm_max_tokens: int = Field(default=16000, gt=0)
    """Room for a long receipt (about 40 tokens per line) plus thinking."""
    llm_calls_per_person_per_day: int = Field(default=150, gt=0)
    llm_calls_per_day: int = Field(default=3000, gt=0)
    chat_history_messages: int = Field(default=10, ge=0, le=50)
    chat_history_keep: int = Field(default=50, ge=1)
    chat_history_days: int = Field(default=30, ge=1)
    fuzzy_threshold: int = Field(default=85, ge=1, le=100)
    """At 0, an empty name would fuzzy-match any item."""
    min_line_confidence: float = Field(default=0.6, ge=0, le=1)
    max_receipt_lines: int = Field(default=150, gt=0)
    max_amount_cents: int = Field(default=100_000_000, gt=0)
    max_image_bytes: int = Field(default=5_000_000, gt=0)
    """The API refuses images over 5 MB, so larger uploads are refused up front."""
    max_queued_drafts: int = Field(default=3, ge=0)
    max_notifications_per_day: int = Field(default=20, gt=0)
    bot_link: str = "https://wa.me/<bot-number>?text=hi"
    """A one-tap link to the bot's chat, used in invites and "message me 1:1 first"."""
    image_dir: Path = Path("./data/images")

    @field_validator("anthropic_api_key", "api_token", mode="before")
    @classmethod
    def _empty_secret_is_unset(cls, value: object) -> object:
        """`ANTHROPIC_API_KEY=` in a copied .env means "not set", not an empty key."""
        return None if value == "" else value

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        """A typo in the timezone fails at startup, not on the first "this month"."""
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"unknown timezone {value!r}") from error
        return value
