from functools import lru_cache

from app.config import settings
from app.memory.base import MemoryProvider
from app.memory.fake import FakeMemoryProvider


@lru_cache
def get_memory_provider() -> MemoryProvider:
    if settings.memory_provider == "mem0":
        from app.memory.mem0_provider import Mem0Provider, build_mem0_config

        return Mem0Provider(build_mem0_config(settings))
    if settings.memory_provider == "custom":
        from app.db.session import SessionLocal
        from app.llm.factory import get_provider
        from app.memory.custom import CustomMemoryProvider
        from app.memory.embeddings import get_embedder

        return CustomMemoryProvider(SessionLocal, get_provider(), get_embedder())
    return FakeMemoryProvider()
