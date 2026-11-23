"""Run the Alembic migrations programmatically, so no alembic.ini is needed at deploy time."""

from pathlib import Path

from alembic import command
from alembic.config import Config

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def alembic_config(database_url: str) -> Config:
    """An Alembic config pointing at the packaged migrations; env.py reads the URL from it."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.attributes["database_url"] = database_url
    return config


def upgrade_to_head(database_url: str) -> None:
    """Bring the database schema up to date."""
    command.upgrade(alembic_config(database_url), "head")
