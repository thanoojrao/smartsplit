"""one active draft per conversation

Revision ID: 0002
Revises: 0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "one_active_draft",
        "drafts",
        ["channel", "ref"],
        unique=True,
        postgresql_where=sa.text("state IN ('awaiting_people', 'parsing', 'reviewing')"),
    )


def downgrade() -> None:
    op.drop_index("one_active_draft", table_name="drafts")
