import asyncio
import os
from collections.abc import Sequence
from typing import Any

from sqlalchemy.engine import make_url

from app.config import Settings, settings
from app.memory.base import MemoryItem, MemoryProvider


def build_mem0_config(s: Settings) -> dict[str, Any]:
    """Free/local setup: Gemini or Ollama for extraction, fastembed for embeddings, our Postgres+pgvector for vectors."""
    if s.llm_provider == "gemini":
        llm: dict[str, Any] = {"provider": "gemini", "config": {"model": s.gemini_model, "api_key": s.gemini_api_key}}
    elif s.llm_provider == "ollama":
        llm = {"provider": "ollama", "config": {"model": s.ollama_model, "ollama_base_url": s.ollama_base_url}}
    else:
        raise ValueError("MEMORY_PROVIDER=mem0 needs LLM_PROVIDER=gemini or ollama (Mem0 uses an LLM to extract memories)")
    url = make_url(s.database_url).set(drivername="postgresql")  # psycopg wants a plain postgresql:// URL
    return {
        "llm": llm,
        "embedder": {"provider": "fastembed", "config": {"model": s.embedding_model, "embedding_dims": s.embedding_dims}},
        "vector_store": {"provider": "pgvector", "config": {
            "connection_string": url.render_as_string(hide_password=False),
            "collection_name": "mem0_memories", "embedding_model_dims": s.embedding_dims}},
    }


def _item(r: dict[str, Any]) -> MemoryItem:
    return MemoryItem(str(r["id"]), str(r["memory"]), r.get("score"), r.get("created_at"), r.get("updated_at"))


class Mem0Provider(MemoryProvider):
    """Adapter over Mem0's synchronous client; calls run in worker threads so the event loop stays free."""

    def __init__(self, config: dict[str, Any] | None = None, *, client: Any = None) -> None:
        if client is None:
            os.environ.setdefault("MEM0_TELEMETRY", "false")  # no anonymous usage data leaves the machine
            from mem0 import Memory  # optional dependency: see requirements-mem0.txt

            client = Memory.from_config(config)
        self.client = client

    async def search(self, user_id: str, query: str, *, top_k: int) -> list[MemoryItem]:
        raw = await asyncio.to_thread(
            self.client.search, query, top_k=top_k, filters={"user_id": user_id}, threshold=settings.memory_threshold)
        rows = raw.get("results", []) if isinstance(raw, dict) else raw  # Mem0 versions differ in shape
        return [_item(r) for r in rows]

    async def add_exchange(self, user_id: str, user_text: str, assistant_text: str, *, source: str | None = None) -> None:
        messages = [{"role": "user", "content": user_text}, {"role": "assistant", "content": assistant_text}]
        await asyncio.to_thread(self.client.add, messages, user_id=user_id)

    async def list_all(self, user_id: str, *, limit: int) -> Sequence[MemoryItem]:
        raw = await asyncio.to_thread(self.client.get_all, filters={"user_id": user_id}, top_k=limit)
        rows = raw.get("results", []) if isinstance(raw, dict) else raw
        return sorted((_item(r) for r in rows), key=lambda m: m.created_at or "", reverse=True)

    async def _owned(self, user_id: str, memory_id: str) -> dict[str, Any] | None:
        # Mem0's get/update/delete take only a memory id, so ownership is checked here, every time.
        row = await asyncio.to_thread(self.client.get, memory_id)
        return row if row and row.get("user_id") == user_id else None

    async def get(self, user_id: str, memory_id: str) -> MemoryItem | None:
        row = await self._owned(user_id, memory_id)
        return _item(row) if row else None

    async def update(self, user_id: str, memory_id: str, text: str) -> MemoryItem | None:
        if await self._owned(user_id, memory_id) is None:
            return None
        await asyncio.to_thread(self.client.update, memory_id, text=text)
        return await self.get(user_id, memory_id)

    async def delete(self, user_id: str, memory_id: str) -> bool:
        if await self._owned(user_id, memory_id) is None:
            return False
        await asyncio.to_thread(self.client.delete, memory_id)
        return True

    async def delete_all(self, user_id: str) -> int:
        count = len(await self.list_all(user_id, limit=10_000))
        await asyncio.to_thread(self.client.delete_all, user_id=user_id)
        return count
