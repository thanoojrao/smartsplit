"""the conversation agent: photo reads, transcript, draft versions, usage counters

Revision ID: 0003
Revises: 0002

Revision 2 (SPEC 8): drafts are versioned and one is active per (chat, adder); the `parsing`
state and its image columns go (photos are read on arrival); prompts are engine questions or
pending actions with new payloads, so old prompts are deleted (a draft's questions are asked
again from the engine when it is next shown); the per-chat "last listed" numbering gives way
to the transcript.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIVE_BEFORE = "state IN ('awaiting_people', 'parsing', 'reviewing')"
_ACTIVE_NOW = "state IN ('awaiting_people', 'reviewing')"


def upgrade() -> None:
    op.execute("UPDATE drafts SET state = 'cancelled' WHERE state = 'parsing'")
    op.execute("DELETE FROM prompts")
    op.execute("DELETE FROM notifications WHERE kind = 'requested_reply'")
    op.drop_index("one_active_draft", table_name="drafts")
    op.drop_column("drafts", "image_ref")
    op.drop_column("drafts", "image_mime_type")
    op.drop_column("drafts", "accepted_difference_cents")
    op.add_column(
        "drafts",
        sa.Column(
            "possible_duplicate_of",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'null'::jsonb"),
        ),
    )
    op.add_column(
        "drafts",
        sa.Column(
            "waiting_for",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column("drafts", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    for column in ("possible_duplicate_of", "waiting_for", "version"):
        op.alter_column("drafts", column, server_default=None)
    op.create_index(
        "one_active_draft_per_adder",
        "drafts",
        ["channel", "ref", "added_by"],
        unique=True,
        postgresql_where=sa.text(_ACTIVE_NOW),
    )
    op.add_column("prompts", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.drop_column("conversations", "last_listed_bill_ids")
    op.alter_column("notifications", "text_args", new_column_name="args")
    op.alter_column("llm_usage", "person_id", new_column_name="counter")
    op.create_table(
        "photo_reads",
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("ref", sa.Text(), nullable=False),
        sa.Column("message_id", sa.Text(), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("sender_id", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("receipt_id", sa.Text(), nullable=True),
        sa.Column("used_by_draft_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("channel", "ref", "message_id"),
        sa.UniqueConstraint("seq"),
    )
    op.create_table(
        "chat_messages",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("ref", sa.Text(), nullable=False),
        sa.Column("sender_id", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("refs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("seq"),
    )
    op.create_index("chat_by_conversation", "chat_messages", ["channel", "ref", "seq"])
    op.create_index("chat_by_age", "chat_messages", ["created_at"])


def downgrade() -> None:
    op.drop_index("chat_by_age", table_name="chat_messages")
    op.drop_index("chat_by_conversation", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_table("photo_reads")
    op.alter_column("llm_usage", "counter", new_column_name="person_id")
    op.execute("DELETE FROM llm_usage WHERE person_id = 'install'")
    op.alter_column("notifications", "args", new_column_name="text_args")
    op.add_column(
        "conversations",
        sa.Column(
            "last_listed_bill_ids",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.alter_column("conversations", "last_listed_bill_ids", server_default=None)
    op.drop_column("prompts", "expires_at")
    op.execute("DELETE FROM prompts")
    op.drop_index("one_active_draft_per_adder", table_name="drafts")
    op.execute(
        "UPDATE drafts d SET state = 'cancelled' WHERE state IN ('awaiting_people', 'reviewing') "
        "AND EXISTS (SELECT 1 FROM drafts o WHERE o.channel = d.channel AND o.ref = d.ref "
        "AND o.state IN ('awaiting_people', 'reviewing') AND o.seq < d.seq)"
    )
    op.drop_column("drafts", "version")
    op.drop_column("drafts", "waiting_for")
    op.drop_column("drafts", "possible_duplicate_of")
    op.add_column(
        "drafts",
        sa.Column(
            "accepted_difference_cents",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
    )
    op.alter_column("drafts", "accepted_difference_cents", server_default=None)
    op.add_column("drafts", sa.Column("image_mime_type", sa.Text(), nullable=True))
    op.add_column("drafts", sa.Column("image_ref", sa.Text(), nullable=True))
    op.create_index(
        "one_active_draft",
        "drafts",
        ["channel", "ref"],
        unique=True,
        postgresql_where=sa.text(_ACTIVE_BEFORE),
    )
