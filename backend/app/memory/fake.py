import re
import uuid
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timezone

from app.memory.base import MemoryItem, MemoryProvider

_STOP = {"the", "a", "an", "is", "am", "are", "i", "my", "me", "to", "of", "in", "and", "for", "what", "should",
         "do", "you", "it", "on", "with", "that", "this", "today", "how", "can"}


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9+#]+", text.lower()) if w not in _STOP}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class FakeMemoryProvider(MemoryProvider):
    """Offline stand-in: keeps user sentences that start with "I ", matches by shared words (NOT semantic).

    In-process only, lost on restart. Counters and failure flags exist for tests.
    """

    def __init__(self) -> None:
        self.store: dict[str, list[MemoryItem]] = {}
        self.search_calls = 0
        self.add_calls = 0
        self.fail_search = False
        self.fail_add = False

    async def search(self, user_id: str, query: str, *, top_k: int) -> list[MemoryItem]:
        self.search_calls += 1
        if self.fail_search:
            raise RuntimeError("fake memory search failure")
        q = _tokens(query)
        scored = [(len(q & _tokens(m.text)), m) for m in self.store.get(user_id, [])]
        hits = sorted((x for x in scored if x[0] > 0), key=lambda x: -x[0])[:top_k]
        return [MemoryItem(m.id, m.text, float(n)) for n, m in hits]

    async def add_exchange(self, user_id: str, user_text: str, assistant_text: str, *, source: str | None = None) -> None:
        self.add_calls += 1
        if self.fail_add:
            raise RuntimeError("fake memory add failure")
        items = self.store.setdefault(user_id, [])
        for sentence in re.split(r"(?<=[.!?])\s+", user_text.strip()):
            if sentence.startswith("I ") and all(sentence != m.text for m in items):
                items.append(MemoryItem(str(uuid.uuid4()), sentence, created_at=_now(), updated_at=_now()))

    async def list_all(self, user_id: str, *, limit: int) -> Sequence[MemoryItem]:
        return list(reversed(self.store.get(user_id, [])))[:limit]

    async def get(self, user_id: str, memory_id: str) -> MemoryItem | None:
        return next((m for m in self.store.get(user_id, []) if m.id == memory_id), None)

    async def update(self, user_id: str, memory_id: str, text: str) -> MemoryItem | None:
        items = self.store.get(user_id, [])
        for i, m in enumerate(items):
            if m.id == memory_id:
                items[i] = replace(m, text=text, updated_at=_now())
                return items[i]
        return None

    async def delete(self, user_id: str, memory_id: str) -> bool:
        items = self.store.get(user_id, [])
        kept = [m for m in items if m.id != memory_id]
        self.store[user_id] = kept
        return len(kept) != len(items)

    async def delete_all(self, user_id: str) -> int:
        return len(self.store.pop(user_id, []))
