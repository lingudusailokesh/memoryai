"""memories table with pgvector embeddings

Revision ID: 0004
Revises: 0003
"""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

DIMS = 384  # BAAI/bge-small-en-v1.5. Changing the model's dimension needs a new migration + re-embedding.


def upgrade() -> None:
    pg = op.get_bind().dialect.name == "postgresql"  # SQLite (unit tests) stores the vector as JSON
    op.create_table(
        "memories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("embedding", Vector(DIMS) if pg else sa.JSON(), nullable=False),
        sa.Column("embedding_model", sa.String(length=100), nullable=False),
        sa.Column("source_conversation_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('active','pending','superseded','deleted')", name=op.f("ck_memories_status_valid")),
        sa.ForeignKeyConstraint(["source_conversation_id"], ["conversations.id"],
                                name=op.f("fk_memories_source_conversation_id_conversations"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_memories_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memories")),
    )
    op.create_index(op.f("ix_memories_user_id"), "memories", ["user_id"])
    if pg:
        op.create_index("ix_memories_embedding_hnsw", "memories", ["embedding"], postgresql_using="hnsw",
                        postgresql_with={"m": 16, "ef_construction": 64},
                        postgresql_ops={"embedding": "vector_cosine_ops"})


def downgrade() -> None:
    op.drop_table("memories")  # drops its indexes with it
