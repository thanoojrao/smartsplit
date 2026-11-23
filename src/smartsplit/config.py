"""Settings from the environment (SPEC section 12.1). Read only by entrypoints, then injected."""

from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every setting has a safe default except the database URL; secrets are SecretStr.

    The API refuses to start without `api_token` (checked by the API entrypoint).
    """

    model_config = SettingsConfigDict(env_prefix="SMARTSPLIT_", extra="ignore")

    database_url: str = Field(validation_alias="DATABASE_URL")
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    api_token: SecretStr | None = None
    currency: str = Field(default="INR", pattern=r"^[A-Z]{3}$")
    default_region: str = Field(default="IN", pattern=r"^[A-Z]{2}$")
    timezone: str = "Asia/Kolkata"
    llm_model: str = "claude-sonnet-5-5"
    llm_timeout_seconds: float = Field(default=60, gt=0)
    llm_max_tokens: int = Field(default=4096, gt=0)
    llm_calls_per_person_per_day: int = Field(default=50, gt=0)
    fuzzy_threshold: int = Field(default=85, ge=0, le=100)
    min_line_confidence: float = Field(default=0.6, ge=0, le=1)
    max_receipt_lines: int = Field(default=150, gt=0)
    max_amount_cents: int = Field(default=100_000_000, gt=0)
    max_image_bytes: int = Field(default=10_000_000, gt=0)
    max_queued_drafts: int = Field(default=3, ge=0)
    max_notifications_per_day: int = Field(default=20, gt=0)
    invite_template: str = "I added our split on SmartSplit. Say hi to the bot to see it."
    image_dir: Path = Path("./data/images")

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        ZoneInfo(value)  # raises for an unknown zone, so a typo fails at startup
        return value
