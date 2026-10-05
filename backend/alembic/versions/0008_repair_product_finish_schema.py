"""repair databases stamped 0007 without its DDL

Some deployments were stamped at 0007 while the Stage 9/10 schema changes were
not present.  Do not edit 0007: deployed Alembic history is immutable.  This
forward-only, idempotent migration safely repairs both those databases and
fresh installs that already received the 0007 DDL.

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table)}


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    return {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    user_columns = _columns("users")
    additions = (
        ("name", sa.Column("name", sa.String(100), nullable=False, server_default="")),
        ("memory_globally_enabled", sa.Column("memory_globally_enabled", sa.Boolean(), nullable=False, server_default=sa.true())),
        ("memory_top_k", sa.Column("memory_top_k", sa.Integer(), nullable=False, server_default="5")),
        ("memory_threshold", sa.Column("memory_threshold", sa.Float(), nullable=False, server_default="0.45")),
        ("custom_instructions", sa.Column("custom_instructions", sa.Text(), nullable=False, server_default="")),
    )
    for name, column in additions:
        if name not in user_columns:
            op.add_column("users", column)

    tables = _tables()
    if "usage_events" not in tables:
        op.create_table(
            "usage_events",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("kind", sa.String(32), nullable=False),
            sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("estimated_cost", sa.Float(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    if "ix_usage_events_user_id" not in _indexes("usage_events"):
        op.create_index("ix_usage_events_user_id", "usage_events", ["user_id"])

    if "memory_retrievals" not in tables:
        op.create_table(
            "memory_retrievals",
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("message_id", sa.Uuid(), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
            sa.Column("memory_id", sa.String(64), nullable=False),
            sa.Column("score", sa.Float(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
    if "ix_memory_retrievals_message_id" not in _indexes("memory_retrievals"):
        op.create_index("ix_memory_retrievals_message_id", "memory_retrievals", ["message_id"])


def downgrade() -> None:
    """No-op: this repair cannot know which objects pre-dated the repair."""
