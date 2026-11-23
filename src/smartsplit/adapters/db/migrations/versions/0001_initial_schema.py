"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-11-23 06:34:24.436520
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "answer_observations",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("scope_kind", sa.Text(), nullable=False),
        sa.Column("scope_ref", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("item_key", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("bill_id", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("seq"),
    )
    op.create_table(
        "bills",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("context_group_id", sa.Text(), nullable=True),
        sa.Column("origin_channel", sa.Text(), nullable=False),
        sa.Column("origin_ref", sa.Text(), nullable=False),
        sa.Column("receipt_id", sa.Text(), nullable=True),
        sa.Column("payer_id", sa.Text(), nullable=False),
        sa.Column("added_by", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("purchased_at", sa.Date(), nullable=False),
        sa.Column("participants", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column("lines", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tax_cents", sa.BigInteger(), nullable=False),
        sa.Column("other_adjustments_cents", sa.BigInteger(), nullable=False),
        sa.Column("total_cents", sa.BigInteger(), nullable=False),
        sa.Column("shares", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reverses_id", sa.Text(), nullable=True),
        sa.Column("replaces_id", sa.Text(), nullable=True),
        sa.Column("edit_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seq"),
    )
    op.create_index("bills_by_context", "bills", ["context_group_id"], unique=False)
    op.create_index(
        "bills_by_participant", "bills", ["participants"], unique=False, postgresql_using="gin"
    )
    op.create_table(
        "conversations",
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("ref", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("group_id", sa.Text(), nullable=True),
        sa.Column("person_id", sa.Text(), nullable=True),
        sa.Column("last_listed_bill_ids", sa.ARRAY(sa.Text()), nullable=False),
        sa.CheckConstraint("(group_id IS NULL) <> (person_id IS NULL)", name="group_or_person"),
        sa.PrimaryKeyConstraint("channel", "ref"),
    )
    op.create_table(
        "drafts",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("ref", sa.Text(), nullable=False),
        sa.Column("context_group_id", sa.Text(), nullable=True),
        sa.Column("added_by", sa.Text(), nullable=False),
        sa.Column("payer_id", sa.Text(), nullable=False),
        sa.Column("receipt_id", sa.Text(), nullable=True),
        sa.Column("image_ref", sa.Text(), nullable=True),
        sa.Column("image_mime_type", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("purchased_at", sa.Date(), nullable=True),
        sa.Column("lines", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tax_cents", sa.BigInteger(), nullable=False),
        sa.Column("other_adjustments_cents", sa.BigInteger(), nullable=False),
        sa.Column("total_cents", sa.BigInteger(), nullable=False),
        sa.Column("accepted_difference_cents", sa.BigInteger(), nullable=False),
        sa.Column("participants", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column("overrides", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("owes_all_id", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reminded_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seq"),
    )
    op.create_index("drafts_by_conversation", "drafts", ["channel", "ref", "state"], unique=False)
    op.create_table(
        "groups",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=True),
        sa.Column("channel_ref", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("channel", "channel_ref"),
    )
    op.create_table(
        "item_aliases",
        sa.Column("scope_kind", sa.Text(), nullable=False),
        sa.Column("scope_ref", sa.Text(), nullable=False),
        sa.Column("raw_name", sa.Text(), nullable=False),
        sa.Column("item_key", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("scope_kind", "scope_ref", "raw_name"),
    )
    op.create_table(
        "items", sa.Column("key", sa.Text(), nullable=False), sa.PrimaryKeyConstraint("key")
    )
    op.create_table(
        "llm_usage",
        sa.Column("person_id", sa.Text(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("calls", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("person_id", "day"),
    )
    op.create_table(
        "people",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("phone", sa.Text(), nullable=False),
        sa.Column("phone_added_by", sa.Text(), nullable=True),
        sa.Column("notifications_enabled", sa.Boolean(), nullable=False),
        sa.Column("has_used_bot", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phone"),
    )
    op.create_table(
        "processed_messages",
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("ref", sa.Text(), nullable=False),
        sa.Column("message_id", sa.Text(), nullable=False),
        sa.Column("replies", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("channel", "ref", "message_id"),
    )
    op.create_table(
        "prompts",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("ref", sa.Text(), nullable=False),
        sa.Column("draft_id", sa.Text(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("asked_of", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seq"),
    )
    op.create_index(
        "prompts_by_conversation", "prompts", ["channel", "ref", "status"], unique=False
    )
    op.create_table(
        "receipts",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("image_ref", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("merchant", sa.Text(), nullable=True),
        sa.Column("purchased_at", sa.Date(), nullable=True),
        sa.Column("line_items", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("tax_cents", sa.BigInteger(), nullable=False),
        sa.Column("other_adjustments_cents", sa.BigInteger(), nullable=False),
        sa.Column("total_cents", sa.BigInteger(), nullable=False),
        sa.Column("warnings", sa.ARRAY(sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "rules",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.Column("item_key", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("scope_kind", sa.Text(), nullable=False),
        sa.Column("scope_ref", sa.Text(), nullable=False),
        sa.Column("author_id", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope_kind", "scope_ref", "subject_id", "item_key"),
    )
    op.create_table(
        "settlements",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("payment_id", sa.Text(), nullable=False),
        sa.Column("context_group_id", sa.Text(), nullable=True),
        sa.Column("from_id", sa.Text(), nullable=False),
        sa.Column("to_id", sa.Text(), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("recorded_by", sa.Text(), nullable=False),
        sa.Column("reverses_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seq"),
    )
    op.create_index(
        op.f("ix_settlements_context_group_id"), "settlements", ["context_group_id"], unique=False
    )
    op.create_index(op.f("ix_settlements_payment_id"), "settlements", ["payment_id"], unique=False)
    op.create_table(
        "chat_identities",
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("external_ref", sa.Text(), nullable=False),
        sa.Column("person_id", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["people.id"],
        ),
        sa.PrimaryKeyConstraint("channel", "external_ref"),
    )
    op.create_table(
        "memberships",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("group_id", sa.Text(), nullable=False),
        sa.Column("person_id", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["groups.id"],
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["people.id"],
        ),
        sa.PrimaryKeyConstraint("seq"),
    )
    op.create_index(
        "one_current_membership",
        "memberships",
        ["group_id", "person_id"],
        unique=True,
        postgresql_where=sa.text("left_at IS NULL"),
    )
    op.create_table(
        "nicknames",
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["people.id"],
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"],
            ["people.id"],
        ),
        sa.PrimaryKeyConstraint("owner_id", "name"),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("recipient_id", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("bill_ids", sa.ARRAY(sa.Text()), nullable=False),
        sa.Column("payment_id", sa.Text(), nullable=True),
        sa.Column("text_args", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["recipient_id"],
            ["people.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("seq"),
    )
    op.create_index(
        "notifications_unsent",
        "notifications",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("sent_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "notifications_unsent",
        table_name="notifications",
        postgresql_where=sa.text("sent_at IS NULL"),
    )
    op.drop_table("notifications")
    op.drop_table("nicknames")
    op.drop_index(
        "one_current_membership",
        table_name="memberships",
        postgresql_where=sa.text("left_at IS NULL"),
    )
    op.drop_table("memberships")
    op.drop_table("chat_identities")
    op.drop_index(op.f("ix_settlements_payment_id"), table_name="settlements")
    op.drop_index(op.f("ix_settlements_context_group_id"), table_name="settlements")
    op.drop_table("settlements")
    op.drop_table("rules")
    op.drop_table("receipts")
    op.drop_index("prompts_by_conversation", table_name="prompts")
    op.drop_table("prompts")
    op.drop_table("processed_messages")
    op.drop_table("people")
    op.drop_table("llm_usage")
    op.drop_table("items")
    op.drop_table("item_aliases")
    op.drop_table("groups")
    op.drop_index("drafts_by_conversation", table_name="drafts")
    op.drop_table("drafts")
    op.drop_table("conversations")
    op.drop_index("bills_by_participant", table_name="bills", postgresql_using="gin")
    op.drop_index("bills_by_context", table_name="bills")
    op.drop_table("bills")
    op.drop_table("answer_observations")
