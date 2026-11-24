"""Alembic environment: online migrations only, against the URL passed in by migrate.py."""

from alembic import context
from sqlalchemy import create_engine

from smartsplit.adapters.db.tables import metadata

engine = create_engine(context.config.attributes["database_url"], hide_parameters=True)
with engine.begin() as connection:
    context.configure(connection=connection, target_metadata=metadata, compare_type=True)
    context.run_migrations()
engine.dispose()
