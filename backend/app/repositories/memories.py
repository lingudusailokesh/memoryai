import math
import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.extraction import Candidate
from app.models import Memory, MemoryVersion, User


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b, strict=True)) / (na * nb) if na and nb else 0.0


class MemoryRepository:
    """Every query is scoped by user_id and only sees status='active'."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_many(self, user_id: uuid.UUID, rows: Sequence[tuple[Candidate, list[float]]], model: str,
                       source: uuid.UUID | None) -> list[Memory]:
        mems = [Memory(user_id=user_id, content=c.content, category=c.category, importance=c.importance,
                       embedding=vec, embedding_model=model, source_conversation_id=source) for c, vec in rows]
        self.session.add_all(mems)
        await self.session.commit()
        return mems

    async def list_all(self, user_id: uuid.UUID, limit: int) -> Sequence[Memory]:
        res = await self.session.execute(
            select(Memory).where(Memory.user_id == user_id, Memory.status == "active")
            .order_by(Memory.created_at.desc(), Memory.id).limit(limit))
        return res.scalars().all()

    async def preferences(self, user_id: uuid.UUID, limit: int) -> Sequence[Memory]:
        """Explicit profile recall: only this user's approved, active preferences."""
        res = await self.session.execute(
            select(Memory).where(Memory.user_id == user_id, Memory.status == "active",
                                 Memory.category == "preference")
            .order_by(Memory.pinned.desc(), Memory.importance.desc(), Memory.created_at.desc(), Memory.id)
            .limit(limit))
        return res.scalars().all()

    async def get(self, user_id: uuid.UUID, memory_id: uuid.UUID, statuses: Sequence[str] = ("active",)) -> Memory | None:
        res = await self.session.execute(
            select(Memory).where(Memory.id == memory_id, Memory.user_id == user_id, Memory.status.in_(statuses)))
        return res.scalar_one_or_none()

    async def update_text(self, user_id: uuid.UUID, memory_id: uuid.UUID, text: str, vec: list[float],
                          model: str) -> Memory | None:
        mem = await self.get(user_id, memory_id, ("active", "pending"))
        if mem is None:
            return None
        if text != mem.content:
            self.session.add(MemoryVersion(memory_id=mem.id, content=mem.content, reason="edited"))
        mem.content, mem.embedding, mem.embedding_model = text, vec, model
        await self.session.commit()
        await self.session.refresh(mem)
        return mem

    async def delete(self, user_id: uuid.UUID, memory_id: uuid.UUID) -> bool:
        res = await self.session.execute(delete(Memory).where(Memory.id == memory_id, Memory.user_id == user_id))
        await self.session.commit()
        return res.rowcount > 0

    async def delete_all(self, user_id: uuid.UUID) -> int:
        res = await self.session.execute(delete(Memory).where(Memory.user_id == user_id))
        await self.session.commit()
        return res.rowcount

    async def existing_lower(self, user_id: uuid.UUID, lowered: Sequence[str]) -> set[str]:
        """Which of these texts (case-insensitive) this user already has. Semantic dedupe comes in Stage 8."""
        res = await self.session.execute(
            select(func.lower(Memory.content)).where(
                Memory.user_id == user_id, Memory.status.in_((("active", "pending"))), func.lower(Memory.content).in_(lowered)))
        return set(res.scalars().all())

    async def similar(self, user_id: uuid.UUID, vec: list[float], limit: int) -> list[tuple[Memory, float]]:
        """Nearest memories by cosine similarity (1 = identical direction), best first."""
        if self.session.sync_session.get_bind().dialect.name == "postgresql":
            dist = Memory.embedding.cosine_distance(vec)  # pgvector `<=>`, served by the HNSW index
            res = await self.session.execute(
                select(Memory, (1 - dist).label("sim"))
                .where(Memory.user_id == user_id, Memory.status == "active").order_by(dist).limit(limit))
            return [(m, float(sim)) for m, sim in res.all()]
        # SQLite (unit tests): same result, computed in Python.
        res = await self.session.execute(select(Memory).where(Memory.user_id == user_id, Memory.status == "active"))
        scored = [(m, _cosine(vec, m.embedding)) for m in res.scalars()]
        return sorted(scored, key=lambda x: -x[1])[:limit]

    # ---- Stage 8: modes, inbox, conflicts, history. The "no commit" methods are used inside one transaction. ----
    async def memory_mode(self, user_id: uuid.UUID) -> str:
        res = await self.session.execute(select(User.memory_mode).where(User.id == user_id))
        return res.scalar_one_or_none() or "auto"

    async def add_one(self, user_id: uuid.UUID, c: Candidate, vec: list[float], model: str, source: uuid.UUID | None,
                      status: str = "active", supersedes_id: uuid.UUID | None = None) -> Memory:
        mem = Memory(user_id=user_id, content=c.content, category=c.category, importance=c.importance, embedding=vec,
                     embedding_model=model, source_conversation_id=source, status=status, supersedes_id=supersedes_id)
        self.session.add(mem)
        await self.session.flush()
        return mem

    async def merge(self, user_id: uuid.UUID, memory_id: uuid.UUID, *, importance: float, new_content: str | None = None,
                    vec: list[float] | None = None, model: str | None = None) -> bool:
        """Fold a duplicate into an existing memory: keep the higher importance, optionally adopt the fuller wording."""
        mem = await self.get(user_id, memory_id)
        if mem is None:
            return False
        mem.importance = max(mem.importance, importance)
        if new_content is not None and vec is not None and new_content != mem.content:
            self.session.add(MemoryVersion(memory_id=mem.id, content=mem.content, reason="merged"))
            mem.content, mem.embedding, mem.embedding_model = new_content, vec, model or mem.embedding_model
        return True

    async def supersede(self, user_id: uuid.UUID, old_id: uuid.UUID, new_id: uuid.UUID) -> bool:
        old = await self.get(user_id, old_id)
        if old is None:
            return False
        self.session.add(MemoryVersion(memory_id=old.id, content=old.content, reason="superseded"))
        old.status, old.superseded_by = "superseded", new_id
        return True

    async def list_by_status(self, user_id: uuid.UUID, status: str, limit: int) -> Sequence[Memory]:
        res = await self.session.execute(
            select(Memory).where(Memory.user_id == user_id, Memory.status == status)
            .order_by(Memory.created_at.desc(), Memory.id).limit(limit))
        return res.scalars().all()

    async def approve(self, user_id: uuid.UUID, memory_id: uuid.UUID) -> Memory | None:
        mem = await self.get(user_id, memory_id, ("pending",))
        if mem is None:
            return None
        if mem.supersedes_id:
            await self.supersede(user_id, mem.supersedes_id, mem.id)  # no-op if that memory changed or is gone
        mem.status, mem.supersedes_id = "active", None
        await self.session.commit()
        await self.session.refresh(mem)
        return mem

    async def restore(self, user_id: uuid.UUID, memory_id: uuid.UUID) -> Memory | None:
        """Undo a conflict resolution: the old memory is active again and its replacement takes its place as superseded."""
        old = await self.get(user_id, memory_id, ("superseded",))
        if old is None:
            return None
        replacement_id = old.superseded_by
        old.status, old.superseded_by = "active", None
        self.session.add(MemoryVersion(memory_id=old.id, content=old.content, reason="restored"))
        await self.session.flush()
        if replacement_id:
            await self.supersede(user_id, replacement_id, old.id)
        await self.session.commit()
        await self.session.refresh(old)
        return old

    async def versions(self, user_id: uuid.UUID, memory_id: uuid.UUID) -> Sequence[MemoryVersion] | None:
        if await self.get(user_id, memory_id, ("active", "pending", "superseded")) is None:
            return None
        res = await self.session.execute(
            select(MemoryVersion).where(MemoryVersion.memory_id == memory_id)
            .order_by(MemoryVersion.created_at.desc(), MemoryVersion.id))
        return res.scalars().all()
