"""analytics, settings, and usage events

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("name", sa.String(100), nullable=False, server_default=""))
        batch.add_column(sa.Column("memory_globally_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column("memory_top_k", sa.Integer(), nullable=False, server_default="5"))
        batch.add_column(sa.Column("memory_threshold", sa.Float(), nullable=False, server_default="0.45"))
        batch.add_column(sa.Column("custom_instructions", sa.Text(), nullable=False, server_default=""))
    op.create_table("usage_events",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False), sa.Column("tokens_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_out", sa.Integer(), nullable=False, server_default="0"), sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost", sa.Float(), nullable=False, server_default="0"), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_usage_events_user_id", "usage_events", ["user_id"])
    op.create_table("memory_retrievals",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("message_id", sa.Uuid(), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("memory_id", sa.String(64), nullable=False), sa.Column("score", sa.Float(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_memory_retrievals_message_id", "memory_retrievals", ["message_id"])


def downgrade() -> None:
    op.drop_table("memory_retrievals")
    op.drop_table("usage_events")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("custom_instructions")
        batch.drop_column("memory_threshold")
        batch.drop_column("memory_top_k")
        batch.drop_column("memory_globally_enabled")
        batch.drop_column("name")
