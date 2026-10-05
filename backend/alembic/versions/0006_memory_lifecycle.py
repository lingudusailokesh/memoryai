"""memory lifecycle: modes, supersede links, version history

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as b:  # batch: SQLite can't ALTER constraints in place
        b.add_column(sa.Column("memory_mode", sa.String(length=8), nullable=False, server_default="auto"))
        b.create_check_constraint(op.f("ck_users_memory_mode_valid"), "memory_mode IN ('auto','ask')")
    with op.batch_alter_table("memories") as b:
        b.add_column(sa.Column("superseded_by", sa.Uuid(), nullable=True))
        b.add_column(sa.Column("supersedes_id", sa.Uuid(), nullable=True))
        b.create_foreign_key(op.f("fk_memories_superseded_by_memories"), "memories", ["superseded_by"], ["id"], ondelete="SET NULL")
        b.create_foreign_key(op.f("fk_memories_supersedes_id_memories"), "memories", ["supersedes_id"], ["id"], ondelete="SET NULL")
    op.create_table(
        "memory_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("reason", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["memory_id"], ["memories.id"], name=op.f("fk_memory_versions_memory_id_memories"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memory_versions")),
    )
    op.create_index(op.f("ix_memory_versions_memory_id"), "memory_versions", ["memory_id"])


def downgrade() -> None:
    op.drop_table("memory_versions")
    with op.batch_alter_table("memories") as b:
        b.drop_constraint(op.f("fk_memories_supersedes_id_memories"), type_="foreignkey")
        b.drop_constraint(op.f("fk_memories_superseded_by_memories"), type_="foreignkey")
        b.drop_column("supersedes_id")
        b.drop_column("superseded_by")
    with op.batch_alter_table("users") as b:
        b.drop_constraint(op.f("ck_users_memory_mode_valid"), type_="check")
        b.drop_column("memory_mode")
