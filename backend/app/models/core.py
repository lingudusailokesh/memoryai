import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import settings
from app.db.base import Base
from app.db.types import Embedding


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("memory_mode IN ('auto','ask')", name="memory_mode_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))  # filled by auth in Stage 3
    memory_mode: Mapped[str] = mapped_column(String(8), default="auto", server_default="auto")  # auto | ask
    name: Mapped[str] = mapped_column(String(100), default="")
    memory_globally_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    memory_top_k: Mapped[int] = mapped_column(default=5, server_default="5")
    memory_threshold: Mapped[float] = mapped_column(Float, default=0.45, server_default="0.45")
    custom_instructions: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), default="New conversation")
    memory_enabled: Mapped[bool] = mapped_column(Boolean, default=True)  # per-chat memory switch (Stage 5)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", passive_deletes=True
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('user','assistant','system')", name="role_valid"),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    # Set in Python (microseconds) rather than DB now(): message order must not tie within a second.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Snapshot of the memories that shaped this reply: [{"id", "text", "score"}]. Snapshot, not a FK,
    # because the memory may later be edited or deleted and the user should still see what was used.
    memories_used: Mapped[list[dict[str, object]] | None] = mapped_column(JSON, default=None)

    @property
    def memories_used_count(self) -> int:
        return len(self.memories_used or [])

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)  # never store the raw token
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Memory(Base):
    """Our own memory store (Stage 7). Mem0 keeps its own tables; the two are independent."""

    __tablename__ = "memories"
    __table_args__ = (
        CheckConstraint("status IN ('active','pending','superseded','deleted')", name="status_valid"),
        # HNSW + cosine: needs no training data (works on an empty table, unlike IVFFlat), good recall at small scale.
        Index("ix_memories_embedding_hnsw", "embedding", postgresql_using="hnsw",
              postgresql_with={"m": 16, "ef_construction": 64}, postgresql_ops={"embedding": "vector_cosine_ops"}),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(32), default="other")
    importance: Mapped[float] = mapped_column(Float, default=0.5)  # 0..1, set by the extractor
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="active")
    embedding: Mapped[list[float]] = mapped_column(Embedding(settings.embedding_dims))
    embedding_model: Mapped[str] = mapped_column(String(100))  # a model change must be detectable (re-embedding)
    source_conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), default=None)
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("memories.id", ondelete="SET NULL"), default=None)
    # For a pending memory that contradicts an active one: the memory it will supersede once approved.
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("memories.id", ondelete="SET NULL"), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)


class MemoryVersion(Base):
    """What a memory said before it was edited, merged into, superseded or restored."""

    __tablename__ = "memory_versions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    memory_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("memories.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(String(16))  # edited | merged | superseded | restored
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)  # never store the raw token
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    tokens_in: Mapped[int] = mapped_column(default=0)
    tokens_out: Mapped[int] = mapped_column(default=0)
    latency_ms: Mapped[int] = mapped_column(default=0)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class MemoryRetrieval(Base):
    __tablename__ = "memory_retrievals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    memory_id: Mapped[str] = mapped_column(String(64))
    score: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
