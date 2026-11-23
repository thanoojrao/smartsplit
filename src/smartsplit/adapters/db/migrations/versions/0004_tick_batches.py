"""tick batches: what one tick returned, kept until the gateway acknowledges it

Revision ID: 0004
Revises: 0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tick_batches",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("messages", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seq"),
    )
    op.create_index(
        "tick_batches_unacked",
        "tick_batches",
        ["created_at"],
        postgresql_where=sa.text("acked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("tick_batches_unacked", table_name="tick_batches")
    op.drop_table("tick_batches")
