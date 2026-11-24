"""Run the Alembic migrations programmatically, so no alembic.ini is needed at deploy time."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, create_engine, func, select

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def alembic_config(database_url: str) -> Config:
    """An Alembic config pointing at the packaged migrations; env.py reads the URL from it."""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.attributes["database_url"] = database_url
    return config


MIGRATION_LOCK_ID = 0x534D53_4D49475241
"""Advisory-lock id ("SMS" "MIGRA" in hex): one process migrates at a time."""


def upgrade_to_head(database_url: str) -> None:
    """Bring the database schema up to date; several workers starting at once take turns."""
    engine = create_engine(database_url, hide_parameters=True)
    try:
        with engine.connect() as connection:
            connection.execute(select(func.pg_advisory_lock(MIGRATION_LOCK_ID)))
            try:
                command.upgrade(alembic_config(database_url), "head")
            finally:
                connection.execute(select(func.pg_advisory_unlock(MIGRATION_LOCK_ID)))
    finally:
        engine.dispose()


def at_head(connection: Connection) -> bool:
    """The schema is at the newest migration (the API is ready only then, SPEC 11)."""
    current = set(MigrationContext.configure(connection).get_current_heads())
    wanted = set(ScriptDirectory.from_config(alembic_config("")).get_heads())
    return current == wanted
