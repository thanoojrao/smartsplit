"""Postgres schema (SQLAlchemy Core). Alembic migrations must match this metadata exactly.

Scopes are stored as (scope_kind, scope_ref) with `scope_ref = ''` for Everywhere, so the
one-rule-per-(scope, subject, item) constraint is a plain unique key. A null
`context_group_id` means the personal-splits context. Nested value tuples are tagged JSONB
(see codec.py). `seq` columns keep insertion order for records that share a timestamp.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

metadata = MetaData()


def _seq() -> Column[int]:
    return Column("seq", BigInteger, Identity(), nullable=False, unique=True)


def _ts(name: str, *, nullable: bool = False) -> Column[object]:
    return Column(name, DateTime(timezone=True), nullable=nullable)


def _cents(name: str) -> Column[int]:
    return Column(name, BigInteger, nullable=False)


people = Table(
    "people",
    metadata,
    Column("id", Text, primary_key=True),
    Column("display_name", Text, nullable=False),
    Column("phone", Text, nullable=False, unique=True),
    Column("phone_added_by", Text),
    Column("notifications_enabled", Boolean, nullable=False),
    Column("has_used_bot", Boolean, nullable=False),
    _ts("created_at"),
)

chat_identities = Table(
    "chat_identities",
    metadata,
    Column("channel", Text, nullable=False),
    Column("external_ref", Text, nullable=False),
    Column("person_id", Text, ForeignKey("people.id"), nullable=False),
    PrimaryKeyConstraint("channel", "external_ref"),
)

nicknames = Table(
    "nicknames",
    metadata,
    Column("owner_id", Text, ForeignKey("people.id"), nullable=False),
    Column("name", Text, nullable=False),
    Column("subject_id", Text, ForeignKey("people.id"), nullable=False),
    PrimaryKeyConstraint("owner_id", "name"),
)

groups = Table(
    "groups",
    metadata,
    Column("id", Text, primary_key=True),
    Column("name", Text, nullable=False),
    Column("channel", Text),
    Column("channel_ref", Text),
    _ts("created_at"),
    UniqueConstraint("channel", "channel_ref"),
)

memberships = Table(
    "memberships",
    metadata,
    Column("seq", BigInteger, Identity(), primary_key=True),
    Column("group_id", Text, ForeignKey("groups.id"), nullable=False),
    Column("person_id", Text, ForeignKey("people.id"), nullable=False),
    Column("position", Integer, nullable=False),
    _ts("joined_at"),
    _ts("left_at", nullable=True),
    Index(
        "one_current_membership",
        "group_id",
        "person_id",
        unique=True,
        postgresql_where=text("left_at IS NULL"),
    ),
)

conversations = Table(
    "conversations",
    metadata,
    Column("channel", Text, nullable=False),
    Column("ref", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("name", Text),
    Column("group_id", Text),
    Column("person_id", Text),
    Column("last_listed_bill_ids", ARRAY(Text), nullable=False),
    PrimaryKeyConstraint("channel", "ref"),
)

items = Table("items", metadata, Column("key", Text, primary_key=True))

item_aliases = Table(
    "item_aliases",
    metadata,
    Column("scope_kind", Text, nullable=False),
    Column("scope_ref", Text, nullable=False),
    Column("raw_name", Text, nullable=False),
    Column("item_key", Text, nullable=False),
    PrimaryKeyConstraint("scope_kind", "scope_ref", "raw_name"),
)

rules = Table(
    "rules",
    metadata,
    Column("id", Text, primary_key=True),
    Column("subject_id", Text, nullable=False),
    Column("item_key", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("scope_kind", Text, nullable=False),
    Column("scope_ref", Text, nullable=False),
    Column("author_id", Text, nullable=False),
    Column("source", Text, nullable=False),
    _ts("created_at"),
    UniqueConstraint("scope_kind", "scope_ref", "subject_id", "item_key"),
)

answer_observations = Table(
    "answer_observations",
    metadata,
    Column("seq", BigInteger, Identity(), primary_key=True),
    Column("scope_kind", Text, nullable=False),
    Column("scope_ref", Text, nullable=False),
    Column("subject_id", Text, nullable=False),
    Column("item_key", Text, nullable=False),
    Column("outcome", Text, nullable=False),
    Column("bill_id", Text, nullable=False),
    _ts("observed_at"),
)

llm_usage = Table(
    "llm_usage",
    metadata,
    Column("person_id", Text, nullable=False),
    Column("day", Date, nullable=False),
    Column("calls", Integer, nullable=False),
    PrimaryKeyConstraint("person_id", "day"),
)

receipts = Table(
    "receipts",
    metadata,
    Column("id", Text, primary_key=True),
    Column("image_ref", Text, nullable=False),
    Column("mime_type", Text, nullable=False),
    Column("merchant", Text),
    Column("purchased_at", Date),
    Column("line_items", JSONB, nullable=False),
    _cents("tax_cents"),
    _cents("other_adjustments_cents"),
    _cents("total_cents"),
    Column("warnings", ARRAY(Text), nullable=False),
)

drafts = Table(
    "drafts",
    metadata,
    Column("id", Text, primary_key=True),
    _seq(),
    Column("channel", Text, nullable=False),
    Column("ref", Text, nullable=False),
    Column("context_group_id", Text),
    Column("added_by", Text, nullable=False),
    Column("payer_id", Text, nullable=False),
    Column("receipt_id", Text),
    Column("image_ref", Text),
    Column("image_mime_type", Text),
    Column("description", Text, nullable=False),
    Column("purchased_at", Date),
    Column("lines", JSONB, nullable=False),
    _cents("tax_cents"),
    _cents("other_adjustments_cents"),
    _cents("total_cents"),
    _cents("accepted_difference_cents"),
    Column("participants", ARRAY(Text), nullable=False),
    Column("overrides", JSONB, nullable=False),
    Column("owes_all_id", Text),
    Column("state", Text, nullable=False),
    _ts("created_at"),
    _ts("last_activity_at"),
    _ts("reminded_at", nullable=True),
    Index("drafts_by_conversation", "channel", "ref", "state"),
)

prompts = Table(
    "prompts",
    metadata,
    Column("id", Text, primary_key=True),
    _seq(),
    Column("channel", Text, nullable=False),
    Column("ref", Text, nullable=False),
    Column("draft_id", Text),
    Column("kind", Text, nullable=False),
    Column("payload", JSONB, nullable=False),
    Column("status", Text, nullable=False),
    Column("asked_of", Text),
    Column("created_by", Text, nullable=False),
    _ts("created_at"),
    Column("answers", JSONB, nullable=False),
    Index("prompts_by_conversation", "channel", "ref", "status"),
)

bills = Table(
    "bills",
    metadata,
    Column("id", Text, primary_key=True),
    _seq(),
    Column("context_group_id", Text),
    Column("origin_channel", Text, nullable=False),
    Column("origin_ref", Text, nullable=False),
    Column("receipt_id", Text),
    Column("payer_id", Text, nullable=False),
    Column("added_by", Text, nullable=False),
    Column("description", Text, nullable=False),
    Column("purchased_at", Date, nullable=False),
    Column("participants", ARRAY(Text), nullable=False),
    Column("lines", JSONB, nullable=False),
    _cents("tax_cents"),
    _cents("other_adjustments_cents"),
    _cents("total_cents"),
    Column("shares", JSONB, nullable=False),
    Column("reverses_id", Text),
    Column("replaces_id", Text),
    Column("edit_reason", Text),
    _ts("created_at"),
    Index("bills_by_context", "context_group_id"),
    Index("bills_by_participant", "participants", postgresql_using="gin"),
)

settlements = Table(
    "settlements",
    metadata,
    Column("id", Text, primary_key=True),
    _seq(),
    Column("payment_id", Text, nullable=False, index=True),
    Column("context_group_id", Text, index=True),
    Column("from_id", Text, nullable=False),
    Column("to_id", Text, nullable=False),
    _cents("amount_cents"),
    Column("kind", Text, nullable=False),
    Column("recorded_by", Text, nullable=False),
    Column("reverses_id", Text),
    _ts("created_at"),
)

notifications = Table(
    "notifications",
    metadata,
    Column("id", Text, primary_key=True),
    _seq(),
    Column("recipient_id", Text, ForeignKey("people.id"), nullable=False),
    Column("actor_id", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("bill_ids", ARRAY(Text), nullable=False),
    Column("payment_id", Text),
    Column("text_args", JSONB, nullable=False),
    _ts("created_at"),
    _ts("sent_at", nullable=True),
    Index("notifications_unsent", "created_at", postgresql_where=text("sent_at IS NULL")),
)

processed_messages = Table(
    "processed_messages",
    metadata,
    Column("channel", Text, nullable=False),
    Column("ref", Text, nullable=False),
    Column("message_id", Text, nullable=False),
    Column("replies", JSONB, nullable=False),
    _ts("processed_at"),
    PrimaryKeyConstraint("channel", "ref", "message_id"),
)
