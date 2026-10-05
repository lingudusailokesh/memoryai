"""Runs against a REAL Postgres with pgvector; skipped unless TEST_POSTGRES_URL is set, e.g.
TEST_POSTGRES_URL=postgresql+asyncpg://memoryai:memoryai@localhost:5432/memoryai_test pytest tests/test_pgvector.py
(CI uses a pgvector service container. Never point this at a database you care about: it drops all tables.)"""
import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.db.base import Base
from app.memory.custom import CustomMemoryProvider
from app.memory.embeddings import FakeEmbedder
from app.repositories.users import UserRepository
from tests.test_custom_memory import ScriptedLLM, facts

URL = os.environ.get("TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set TEST_POSTGRES_URL to run pgvector tests")


@pytest.fixture
async def pg():
    engine = create_async_engine(URL)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


async def provider_for(pg, reply):
    maker = async_sessionmaker(pg, expire_on_commit=False)
    async with maker() as s:
        a = await UserRepository(s).create("a@x.com", "h")
        b = await UserRepository(s).create("b@x.com", "h")
    return CustomMemoryProvider(maker, ScriptedLLM(reply), FakeEmbedder()), str(a.id), str(b.id)


async def test_schema_uses_vector_column_and_hnsw_cosine_index(pg):
    async with pg.connect() as conn:
        col = (await conn.execute(text(
            "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
            "WHERE attrelid = 'memories'::regclass AND attname = 'embedding'"))).scalar_one()
        index = (await conn.execute(text(
            "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_memories_embedding_hnsw'"))).scalar_one()
    assert col == "vector(384)"
    assert "USING hnsw" in index and "vector_cosine_ops" in index


async def test_similarity_search_ranks_gates_and_isolates_in_postgres(pg):
    p, a, b = await provider_for(pg, facts(
        ("User is learning Python", "skill", 0.8), ("User likes graph problems", "preference", 0.5),
        ("User lives near Guwahati city", "personal", 0.3)))
    await p.add_exchange(a, "x", "y")
    hits = await p.search(a, "learning python tips", top_k=5)  # runs the `<=>` query
    assert [h.text for h in hits] == ["User is learning Python"] and 0.45 < hits[0].score <= 1.0
    assert await p.search(a, "weather in paris", top_k=5) == []
    assert await p.search(b, "learning python tips", top_k=5) == []
    assert len(await p.list_all(a, limit=10)) == 3 and await p.list_all(b, limit=10) == []


async def test_edit_delete_and_user_cascade_in_postgres(pg):
    p, a, b = await provider_for(pg, facts(("User is learning Python", "skill", 0.8)))
    await p.add_exchange(a, "x", "y")
    mid = (await p.list_all(a, limit=1))[0].id
    assert await p.update(b, mid, "pwned") is None and await p.delete(b, mid) is False
    await p.update(a, mid, "User enjoys Rust programming")
    assert [h.text for h in await p.search(a, "rust programming", top_k=3)] == ["User enjoys Rust programming"]
    assert await p.search(a, "learning python", top_k=3) == []
    async with pg.begin() as conn:  # deleting the user removes their memories (ON DELETE CASCADE)
        await conn.execute(text("DELETE FROM users WHERE id = :i"), {"i": a})
        assert (await conn.execute(text("SELECT count(*) FROM memories"))).scalar_one() == 0


async def test_dedupe_conflict_restore_and_inbox_in_postgres(pg, monkeypatch):
    from app.config import settings
    from tests.test_memory_lifecycle import RouterLLM, facts

    monkeypatch.setattr(settings, "memory_review_similarity", 0.4)
    maker = async_sessionmaker(pg, expire_on_commit=False)
    async with maker() as s:
        user = await UserRepository(s).create("a@x.com", "h")
    uid, llm = str(user.id), RouterLLM()
    p = CustomMemoryProvider(maker, llm, FakeEmbedder())
    llm.extract_reply = facts(("User prefers Java for coding", "preference", 0.5))
    await p.add_exchange(uid, "x", "y")
    llm.extract_reply = facts(("User switched from Java to Python", "preference", 0.6))
    await p.add_exchange(uid, "x", "y")
    [new] = await p.list_all(uid, limit=5)
    [old] = await p.list_superseded(uid, limit=5)
    assert old.superseded_by == new.id and llm.decide_calls == 1
    assert (await p.restore(uid, old.id)).status == "active"
    assert (await p.list_superseded(uid, limit=5))[0].id == new.id
    assert {v.reason for v in await p.versions(uid, old.id)} == {"superseded", "restored"}
    async with maker() as s:
        await UserRepository(s).set_memory_mode(user.id, "ask")
    llm.extract_reply = facts(("User likes tea a lot", "preference", 0.5))
    await p.add_exchange(uid, "x", "y")
    [pending] = await p.list_pending(uid, limit=5)
    assert (await p.approve(uid, pending.id)).status == "active"
