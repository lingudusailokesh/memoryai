import logging
import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.llm.base import LLMProvider
from app.memory.base import MemoryItem, MemoryProvider, MemoryVersionItem
from app.memory.dedupe import decide_pairs
from app.memory.embeddings import EmbeddingProvider
from app.memory.extraction import MemoryExtractor, refine_importance
from app.memory.scoring import relevance
from app.memory.sensitive import check_sensitive
from app.models import Memory
from app.repositories.memories import MemoryRepository


log = logging.getLogger(__name__)


def _item(m: Memory, score: float | None = None) -> MemoryItem:
    return MemoryItem(str(m.id), m.content, score, m.created_at.isoformat(), m.updated_at.isoformat(), m.category,
                      m.importance, m.status, str(m.superseded_by) if m.superseded_by else None,
                      str(m.supersedes_id) if m.supersedes_id else None)


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None  # a malformed id is simply "not found"


class CustomMemoryProvider(MemoryProvider):
    """Our own pipeline: LLM extraction -> local embeddings -> Postgres/pgvector -> scored retrieval.

    Opens short DB sessions per call (none is held while waiting on the LLM or the embedder).
    """

    def __init__(self, maker: async_sessionmaker[AsyncSession], llm: LLMProvider, embedder: EmbeddingProvider) -> None:
        self.maker, self.embedder, self.llm = maker, embedder, llm
        self.extractor = MemoryExtractor(llm)

    async def search(self, user_id: str, query: str, *, top_k: int) -> list[MemoryItem]:
        uid = _uuid(user_id)
        if uid is None:
            return []
        vec = (await self.embedder.embed([query]))[0]
        async with self.maker() as s:
            rows = await MemoryRepository(s).similar(uid, vec, limit=top_k * 3)  # over-fetch, then re-rank
        scored = sorted(
            ((relevance(sim, m.importance, m.created_at, m.pinned), m) for m, sim in rows
             if sim >= settings.memory_min_similarity),  # the gate: only genuinely similar memories compete
            key=lambda x: -x[0])
        return [_item(m, round(score, 4)) for score, m in scored[:top_k]]

    async def add_exchange(self, user_id: str, user_text: str, assistant_text: str, *, source: str | None = None) -> None:
        """extract (1 LLM call) -> guard -> embed (1 batch) -> compare with what we know -> save.

        Each candidate is compared with its nearest active memory:
          sim >= auto-merge          same fact: merge, no LLM call
          review <= sim < auto-merge ambiguous: ONE LLM call decides same / different / conflicting for all such pairs
          sim < review               new fact
        conflicting: the old memory becomes `superseded` (kept, restorable) and the new one active.
        In "ask" mode new facts wait in the inbox as `pending` instead of being saved.
        """
        uid = _uuid(user_id)
        candidates = await self.extractor.extract(user_text, assistant_text)  # 1 LLM call
        candidates = [refine_importance(c) for c in candidates if check_sensitive(c.content) is None]
        if uid is None or not candidates:
            return
        async with self.maker() as s:
            have = await MemoryRepository(s).existing_lower(uid, [c.content.lower() for c in candidates])
        candidates = [c for c in candidates if c.content.lower() not in have]
        if not candidates:
            return
        vectors = await self.embedder.embed([c.content for c in candidates])  # 1 embedding batch
        async with self.maker() as s:
            repo = MemoryRepository(s)
            mode = await repo.memory_mode(uid)
            nearest = [(await repo.similar(uid, v, limit=1)) for v in vectors]
        near = [(n[0][0], n[0][1]) if n else (None, 0.0) for n in nearest]
        lo, hi = settings.memory_review_similarity, settings.memory_auto_merge_similarity
        ambiguous = [i for i, (m, sim) in enumerate(near) if m is not None and lo <= sim < hi]
        verdict = dict(zip(ambiguous, await decide_pairs(  # 1 LLM call for all ambiguous pairs, outside any DB session
            self.llm, [(near[i][0].content, candidates[i].content) for i in ambiguous]), strict=True))
        src = _uuid(source) if source else None
        async with self.maker() as s:
            repo = MemoryRepository(s)
            for i, (c, vec) in enumerate(zip(candidates, vectors, strict=True)):
                old, sim = near[i]
                decision = "different" if old is None or sim < lo else "same" if sim >= hi else verdict[i]
                if decision == "same":
                    longer = len(c.content) > 1.2 * len(old.content) and mode == "auto"  # in "ask" mode never rewrite silently
                    if await repo.merge(uid, old.id, importance=c.importance, new_content=c.content if longer else None,
                                        vec=vec if longer else None, model=self.embedder.model_name):
                        continue
                    decision = "different"  # the old memory vanished meanwhile: treat as new
                conflict = decision == "conflicting"
                new = await repo.add_one(uid, c, vec, self.embedder.model_name, src,
                                         status="pending" if mode == "ask" else "active",
                                         supersedes_id=old.id if conflict and mode == "ask" else None)
                if conflict and mode == "auto":
                    await repo.supersede(uid, old.id, new.id)
            await s.commit()

    async def list_all(self, user_id: str, *, limit: int) -> Sequence[MemoryItem]:
        uid = _uuid(user_id)
        if uid is None:
            return []
        async with self.maker() as s:
            return [_item(m) for m in await MemoryRepository(s).list_all(uid, limit)]

    async def get(self, user_id: str, memory_id: str) -> MemoryItem | None:
        uid, mid = _uuid(user_id), _uuid(memory_id)
        if uid is None or mid is None:
            return None
        async with self.maker() as s:
            m = await MemoryRepository(s).get(uid, mid)
            return _item(m) if m else None

    async def update(self, user_id: str, memory_id: str, text: str) -> MemoryItem | None:
        uid, mid = _uuid(user_id), _uuid(memory_id)
        if uid is None or mid is None:
            return None
        vec = (await self.embedder.embed([text]))[0]  # edited text must be searchable by its new meaning
        async with self.maker() as s:
            m = await MemoryRepository(s).update_text(uid, mid, text, vec, self.embedder.model_name)
            return _item(m) if m else None

    async def delete(self, user_id: str, memory_id: str) -> bool:
        uid, mid = _uuid(user_id), _uuid(memory_id)
        if uid is None or mid is None:
            return False
        async with self.maker() as s:
            return await MemoryRepository(s).delete(uid, mid)

    async def delete_all(self, user_id: str) -> int:
        uid = _uuid(user_id)
        if uid is None:
            return 0
        async with self.maker() as s:
            return await MemoryRepository(s).delete_all(uid)

    # ---- inbox, superseded, history ----
    async def list_pending(self, user_id: str, *, limit: int) -> Sequence[MemoryItem]:
        return await self._by_status(user_id, "pending", limit)

    async def list_superseded(self, user_id: str, *, limit: int) -> Sequence[MemoryItem]:
        return await self._by_status(user_id, "superseded", limit)

    async def _by_status(self, user_id: str, status: str, limit: int) -> Sequence[MemoryItem]:
        uid = _uuid(user_id)
        if uid is None:
            return []
        async with self.maker() as s:
            return [_item(m) for m in await MemoryRepository(s).list_by_status(uid, status, limit)]

    async def approve(self, user_id: str, memory_id: str) -> MemoryItem | None:
        uid, mid = _uuid(user_id), _uuid(memory_id)
        if uid is None or mid is None:
            return None
        async with self.maker() as s:
            m = await MemoryRepository(s).approve(uid, mid)
            return _item(m) if m else None

    async def reject(self, user_id: str, memory_id: str) -> bool:
        uid, mid = _uuid(user_id), _uuid(memory_id)
        if uid is None or mid is None:
            return False
        async with self.maker() as s:
            repo = MemoryRepository(s)
            if await repo.get(uid, mid, ("pending",)) is None:  # reject only applies to suggestions
                return False
            return await repo.delete(uid, mid)

    async def restore(self, user_id: str, memory_id: str) -> MemoryItem | None:
        uid, mid = _uuid(user_id), _uuid(memory_id)
        if uid is None or mid is None:
            return None
        async with self.maker() as s:
            m = await MemoryRepository(s).restore(uid, mid)
            return _item(m) if m else None

    async def versions(self, user_id: str, memory_id: str) -> Sequence[MemoryVersionItem] | None:
        uid, mid = _uuid(user_id), _uuid(memory_id)
        if uid is None or mid is None:
            return None
        async with self.maker() as s:
            rows = await MemoryRepository(s).versions(uid, mid)
            return None if rows is None else [MemoryVersionItem(v.content, v.reason, v.created_at.isoformat()) for v in rows]
