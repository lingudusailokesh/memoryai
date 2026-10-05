import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.llm.base import LLMProvider, LLMUnavailableError
from app.memory.custom import CustomMemoryProvider
from app.memory.embeddings import CachedEmbedder, FakeEmbedder
from app.memory.extraction import parse_candidates
from app.memory.factory import get_memory_provider
from app.memory.scoring import relevance
from app.models import Memory
from app.repositories.conversations import ConversationRepository
from app.repositories.users import UserRepository
from app.services.chat import drain_background
from tests.test_chat import history, login, new_convo, send


class ScriptedLLM(LLMProvider):
    """Returns a canned extraction reply and counts calls."""

    def __init__(self, reply: str = "[]") -> None:
        self.reply, self.calls, self.error = reply, 0, None

    async def stream_chat(self, messages, *, max_tokens):
        self.calls += 1
        if self.error:
            raise self.error
        yield self.reply


def facts(*items: tuple[str, str, float]) -> str:
    return json.dumps([{"content": c, "category": cat, "importance": imp} for c, cat, imp in items])


async def make(engine, reply="[]"):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        user = await UserRepository(s).create("a@x.com", "h")
        other = await UserRepository(s).create("b@x.com", "h")
    llm, emb = ScriptedLLM(reply), FakeEmbedder()
    return CustomMemoryProvider(maker, llm, emb), llm, emb, str(user.id), str(other.id)


# ---------- extraction parsing ----------
def test_parse_valid_fenced_and_wrapped_output():
    raw = '```json\n[{"content": "User is learning Python", "category": "Skill", "importance": 0.8}]\n```'
    [c] = parse_candidates(raw)
    assert (c.content, c.category, c.importance) == ("User is learning Python", "skill", 0.8)
    assert len(parse_candidates('Sure! [{"content": "User likes graph problems", "importance": 0.4}] Hope that helps')) == 1
    assert len(parse_candidates('{"memories": [{"content": "User studies at night daily"}]}')) == 1


def test_parse_rejects_and_normalises_bad_items():
    items = [
        {"content": "", "category": "skill"}, {"content": "too short"}, {"content": "x " * 200},
        {"content": "User likes tea a lot", "category": "nonsense", "importance": 7},
        {"content": "User likes tea a lot"},  # duplicate within the reply
        {"content": "User dislikes noisy offices", "importance": "high"}, "not a dict",
    ]
    out = parse_candidates(json.dumps(items))
    assert [(c.content, c.category, c.importance) for c in out] == [
        ("User likes tea a lot", "other", 1.0), ("User dislikes noisy offices", "other", 0.5)]


@pytest.mark.parametrize("raw", ["", "not json", "[1, 2", "{}", '"text"', "null"])
def test_parse_garbage_means_no_memories(raw):
    assert parse_candidates(raw) == []


def test_parse_caps_per_exchange():
    many = [{"content": f"User likes topic number {i}"} for i in range(20)]
    assert len(parse_candidates(json.dumps(many))) == settings.memory_max_per_exchange


# ---------- scoring ----------
def test_relevance_formula_and_ordering():
    now = datetime(2026, 10, 5, tzinfo=timezone.utc)
    base = dict(created_at=now, pinned=False, now=now)
    assert relevance(0.8, 0.5, **base) == pytest.approx(0.7 * 0.8 + 0.15 * 0.5 + 0.10 * 1.0)
    assert relevance(0.8, 0.9, **base) > relevance(0.8, 0.1, **base)  # importance
    old = dict(created_at=now - timedelta(days=settings.memory_recency_half_life_days), pinned=False, now=now)
    assert relevance(0.8, 0.5, **base) - relevance(0.8, 0.5, **old) == pytest.approx(0.10 * 0.5)  # recency halves
    assert relevance(0.8, 0.5, **{**base, "pinned": True}) - relevance(0.8, 0.5, **base) == pytest.approx(0.05)
    assert relevance(0.9, 0.0, **old) > relevance(0.5, 1.0, **base)  # similarity dominates by default weights


# ---------- embeddings ----------
async def test_fake_embedder_is_deterministic_normalised_and_similarity_ordered():
    e = FakeEmbedder()
    a, b, c = await e.embed(["learning python", "python interviews", "weather paris"])
    assert len(a) == settings.embedding_dims == 384 and abs(sum(x * x for x in a) - 1) < 1e-9
    assert (await e.embed(["learning python"]))[0] == a
    dot = lambda u, v: sum(x * y for x, y in zip(u, v))  # noqa: E731
    assert dot(a, b) > dot(a, c) == 0


async def test_cached_embedder_never_embeds_the_same_text_twice():
    inner = FakeEmbedder()
    e = CachedEmbedder(inner)
    first = await e.embed(["python", "rust", "python"])
    assert inner.calls == 1 and first[0] == first[2]
    await e.embed(["python", "rust"])
    assert inner.calls == 1


# ---------- provider ----------
async def test_add_exchange_uses_one_llm_call_and_one_embedding_batch(engine):
    p, llm, emb, uid, _ = await make(engine, facts(
        ("User is learning Python", "skill", 0.8), ("User prefers morning study sessions", "preference", 0.5)))
    await p.add_exchange(uid, "I'm learning Python and like mornings", "Great!")
    assert (llm.calls, emb.calls) == (1, 1)
    mems = await p.list_all(uid, limit=10)
    assert {m.text for m in mems} == {"User is learning Python", "User prefers morning study sessions"}
    assert {m.category for m in mems} == {"skill", "preference"}


async def test_search_gates_by_similarity_and_ranks(engine):
    p, _, _, uid, _ = await make(engine, facts(
        ("User is learning Python", "skill", 0.8), ("User likes graph problems", "preference", 0.5)))
    await p.add_exchange(uid, "x", "y")
    hits = await p.search(uid, "learning python tips", top_k=5)
    assert [h.text for h in hits] == ["User is learning Python"] and hits[0].score and hits[0].category == "skill"
    assert await p.search(uid, "weather in paris", top_k=5) == []  # below the gate: nothing is injected


async def test_importance_reranks_equally_similar_memories(engine):
    p, _, _, uid, _ = await make(engine, facts(
        ("User studies python alpha", "skill", 0.1), ("User studies python beta", "skill", 0.9)))
    await p.add_exchange(uid, "x", "y")
    hits = await p.search(uid, "python studies", top_k=2)
    assert [h.text for h in hits] == ["User studies python beta", "User studies python alpha"]


async def test_users_are_isolated(engine):
    p, _, _, uid, other = await make(engine, facts(("User is learning Python", "skill", 0.8)))
    await p.add_exchange(uid, "x", "y")
    mid = (await p.list_all(uid, limit=1))[0].id
    assert await p.search(other, "python", top_k=5) == [] and await p.list_all(other, limit=5) == []
    assert await p.get(other, mid) is None
    assert await p.update(other, mid, "pwned") is None and await p.delete(other, mid) is False
    assert await p.delete_all(other) == 0
    assert (await p.get(uid, mid)).text == "User is learning Python"


async def test_exact_duplicates_are_not_stored_twice(engine):
    p, _, _, uid, _ = await make(engine, facts(("User is learning Python", "skill", 0.8)))
    await p.add_exchange(uid, "x", "y")
    p.extractor.llm.reply = facts(("user is learning python", "skill", 0.8))  # same text, different case
    await p.add_exchange(uid, "x", "y")
    assert len(await p.list_all(uid, limit=10)) == 1


async def test_edit_reembeds_so_search_follows_the_new_text(engine):
    p, _, emb, uid, _ = await make(engine, facts(("User is learning Python", "skill", 0.8)))
    await p.add_exchange(uid, "x", "y")
    mid = (await p.list_all(uid, limit=1))[0].id
    assert (await p.update(uid, mid, "User enjoys Rust programming")).text == "User enjoys Rust programming"
    assert [h.text for h in await p.search(uid, "rust", top_k=3)] == ["User enjoys Rust programming"]
    assert await p.search(uid, "python", top_k=3) == []


async def test_delete_and_delete_all(engine):
    p, _, _, uid, _ = await make(engine, facts(("User is learning Python", "skill", 0.8), ("User likes graph problems", "other", 0.5)))
    await p.add_exchange(uid, "x", "y")
    first = (await p.list_all(uid, limit=5))[0].id
    assert await p.delete(uid, first) is True and await p.delete(uid, first) is False
    assert await p.delete_all(uid) == 1 and await p.list_all(uid, limit=5) == []


async def test_bad_ids_are_simply_not_found(engine):
    p, _, _, uid, _ = await make(engine)
    assert await p.get(uid, "not-a-uuid") is None and await p.delete(uid, "nope") is False
    assert await p.update(uid, str(uuid.uuid4()), "x") is None and await p.search("garbage", "q", top_k=3) == []


async def test_failures_propagate_and_store_nothing(engine):
    p, llm, emb, uid, _ = await make(engine, facts(("User is learning Python", "skill", 0.8)))
    llm.error = LLMUnavailableError("down")
    with pytest.raises(LLMUnavailableError):
        await p.add_exchange(uid, "x", "y")
    llm.error, emb.fail = None, True
    with pytest.raises(RuntimeError):
        await p.add_exchange(uid, "x", "y")
    with pytest.raises(RuntimeError):  # query embedding failure: ChatService turns this into "answer without memory"
        await p.search(uid, "python", top_k=3)
    assert await p.list_all(uid, limit=5) == []


async def test_unusable_extraction_reply_is_a_no_op(engine):
    p, _, emb, uid, _ = await make(engine, "Sorry, I can't do that.")
    await p.add_exchange(uid, "x", "y")
    assert emb.calls == 0 and await p.list_all(uid, limit=5) == []


async def test_rows_record_model_and_source(engine, session):
    from sqlalchemy import select
    p, _, emb, uid, _ = await make(engine, facts(("User is learning Python", "skill", 0.8)))
    convo = await ConversationRepository(session).create(uuid.UUID(uid))
    await p.add_exchange(uid, "x", "y", source=str(convo.id))
    row = (await session.execute(select(Memory))).scalar_one()
    assert row.embedding_model == emb.model_name and len(row.embedding) == 384 and row.status == "active"
    assert row.source_conversation_id == convo.id


# ---------- through the HTTP API, offline fakes end to end ----------
async def test_chat_with_custom_provider_remembers_and_recalls(client, engine, provider):
    from app.main import app
    maker = async_sessionmaker(engine, expire_on_commit=False)
    app.dependency_overrides[get_memory_provider] = lambda: CustomMemoryProvider(maker, provider, FakeEmbedder())
    h = await login(client)
    await send(client, h, await new_convo(client, h), "I am learning Python for interviews.")
    await drain_background()
    listed = (await client.get("/api/memories", headers=h)).json()
    assert [m["text"] for m in listed] == ["I am learning Python for interviews."]
    assert listed[0]["category"] == "other" and listed[0]["importance"] == 0.45  # 0.5 minus the "other" nudge
    cid = await new_convo(client, h)
    assert (await send(client, h, cid, "python interviews help"))[-1][1]["memories_used"] == 1
    reply = (await history(client, h, cid))[-1]
    used = (await client.get(f"/api/messages/{reply['id']}/memories-used", headers=h)).json()
    assert used[0]["category"] == "other" and used[0]["score"] > 0.45
    mid = listed[0]["id"]
    assert (await client.patch(f"/api/memories/{mid}", json={"text": "I enjoy Rust."}, headers=h)).json()["text"] == "I enjoy Rust."
    assert (await client.delete(f"/api/memories/{mid}", headers=h)).status_code == 204
    assert (await client.get("/api/memories", headers=h)).json() == []
