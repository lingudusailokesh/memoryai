import json

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import settings
from app.llm.base import LLMProvider, LLMUnavailableError
from app.llm.fake import FakeLLMProvider
from app.llm.prompts import DEDUPE_PROMPT, EXTRACT_PROMPT
from app.main import app
from app.memory.custom import CustomMemoryProvider
from app.memory.dedupe import decide_pairs, parse_decisions
from app.memory.embeddings import FakeEmbedder
from app.memory.extraction import Candidate, refine_importance
from app.memory.factory import get_memory_provider
from app.memory.sensitive import check_sensitive
from app.repositories.users import UserRepository
from app.services.chat import drain_background
from tests.test_chat import login, new_convo, send


class RouterLLM(LLMProvider):
    """Answers extraction with a canned reply and same/different/conflicting with the offline heuristics."""

    def __init__(self, extract: str | None = "[]") -> None:
        self.extract_reply, self.extract_calls, self.decide_calls = extract, 0, 0
        self.decide_error: Exception | None = None
        self._fake = FakeLLMProvider()

    async def stream_chat(self, messages, *, max_tokens):
        if messages[0].content == EXTRACT_PROMPT:
            self.extract_calls += 1
            if self.extract_reply is None:  # delegate to the offline heuristics (the user's "I ..." sentences)
                async for chunk in self._fake.stream_chat(messages, max_tokens=max_tokens):
                    yield chunk
            else:
                yield self.extract_reply
        elif messages[0].content == DEDUPE_PROMPT:
            self.decide_calls += 1
            if self.decide_error:
                raise self.decide_error
            async for chunk in self._fake.stream_chat(messages, max_tokens=max_tokens):
                yield chunk


def facts(*items: tuple[str, str, float]) -> str:
    return json.dumps([{"content": c, "category": cat, "importance": imp} for c, cat, imp in items])


async def make(engine, reply="[]", mode="auto"):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        a = await UserRepository(s).create("a@x.com", "h")
        b = await UserRepository(s).create("b@x.com", "h")
        await UserRepository(s).set_memory_mode(a.id, mode)
    llm = RouterLLM(reply)
    return CustomMemoryProvider(maker, llm, FakeEmbedder()), llm, str(a.id), str(b.id)


async def add(p, llm, uid, reply):
    llm.extract_reply = reply
    await p.add_exchange(uid, "x", "y")


# ---------- sensitive-data guard ----------
@pytest.mark.parametrize("text", [
    "My password is hunter2", "The API key = sk-abcdefghijklmnopqrstuvwx", "my PIN is 4821",
    "card number 4111 1111 1111 1111", "aws AKIAIOSFODNN7EXAMPLE", "SSN 123-45-6789", "PAN ABCDE1234F",
    "Aadhaar 2345 6789 0123", "-----BEGIN RSA PRIVATE KEY-----", "token eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.abcdefghijkl",
])
def test_guard_blocks_secrets_and_ids(text):
    assert check_sensitive(text) is not None


@pytest.mark.parametrize("text", [
    "User is learning Python", "User's password manager is Bitwarden", "User prefers strong passwords",
    "User is preparing for 2026 exams", "User lives in Guwahati since 2019", "User has 3 years of experience since 2023",
])
def test_guard_allows_ordinary_facts(text):
    assert check_sensitive(text) is None


def test_importance_nudges():
    base = Candidate("User is preparing for SDE interviews", "goal", 0.5)
    assert refine_importance(base).importance == 0.7
    assert refine_importance(Candidate("User mentioned the weather today", "other", 0.5)).importance == 0.45
    assert refine_importance(Candidate("User always studies at night", "goal", 1.0)).importance == 1.0


# ---------- decision parsing ----------
def test_parse_decisions_is_forgiving_and_safe():
    assert parse_decisions('[{"id": 1, "decision": "SAME"}, {"id": 2, "decision": "conflicting"}]', 2) == ["same", "conflicting"]
    assert parse_decisions('[{"id": 2, "decision": "same"}]', 2) == ["different", "same"]
    assert parse_decisions("garbage", 2) == ["different", "different"]
    assert parse_decisions('[{"id": 9, "decision": "same"}, {"id": 1, "decision": "maybe"}]', 1) == ["different"]


async def test_decide_pairs_failure_keeps_both():
    llm = RouterLLM()
    llm.decide_error = LLMUnavailableError("down")
    assert await decide_pairs(llm, [("a b c", "a b d")]) == ["different"]
    assert await decide_pairs(llm, []) == []


# ---------- de-duplication ----------
async def test_near_identical_is_merged_without_an_llm_call(engine):
    p, llm, uid, _ = await make(engine)
    await add(p, llm, uid, facts(("User learning Python", "skill", 0.4)))
    await add(p, llm, uid, facts(("User is learning Python", "skill", 0.9)))  # same words once stop-words are removed
    [m] = await p.list_all(uid, limit=10)
    assert llm.decide_calls == 0 and m.text == "User learning Python" and m.importance == pytest.approx(0.9 - 0.0)


async def test_ambiguous_pair_asks_once_and_a_fuller_wording_wins_with_history(engine):
    p, llm, uid, _ = await make(engine)
    await add(p, llm, uid, facts(("User is learning Python", "skill", 0.5)))
    await add(p, llm, uid, facts(("User is learning Python daily", "skill", 0.5)))
    [m] = await p.list_all(uid, limit=10)
    assert llm.decide_calls == 1 and m.text == "User is learning Python daily"
    assert [(v.reason, v.content) for v in await p.versions(uid, m.id)] == [("merged", "User is learning Python")]


async def test_unrelated_facts_are_both_kept_with_no_extra_call(engine):
    p, llm, uid, _ = await make(engine)
    await add(p, llm, uid, facts(("User likes graph problems", "preference", 0.5)))
    await add(p, llm, uid, facts(("User likes tea a lot", "preference", 0.5)))
    assert len(await p.list_all(uid, limit=10)) == 2 and llm.decide_calls == 0


async def test_all_ambiguous_pairs_of_an_exchange_share_one_llm_call(engine, monkeypatch):
    monkeypatch.setattr(settings, "memory_review_similarity", 0.4)
    p, llm, uid, _ = await make(engine)
    await add(p, llm, uid, facts(("User prefers Java for coding", "preference", 0.5), ("User studies algorithms every night", "goal", 0.5)))
    await add(p, llm, uid, facts(("User switched from Java to Python", "preference", 0.6), ("User studies algorithms daily", "goal", 0.5)))
    assert llm.decide_calls == 1


async def test_decision_failure_keeps_both_memories(engine, monkeypatch):
    monkeypatch.setattr(settings, "memory_review_similarity", 0.4)
    p, llm, uid, _ = await make(engine)
    await add(p, llm, uid, facts(("User prefers Java for coding", "preference", 0.5)))
    llm.decide_error = LLMUnavailableError("down")
    await add(p, llm, uid, facts(("User switched from Java to Python", "preference", 0.6)))
    assert len(await p.list_all(uid, limit=10)) == 2


# ---------- conflicts, history, restore ----------
async def conflict(engine, monkeypatch, mode="auto"):
    monkeypatch.setattr(settings, "memory_review_similarity", 0.4)
    p, llm, uid, other = await make(engine, mode=mode)
    await add(p, llm, uid, facts(("User prefers Java for coding", "preference", 0.5)))
    if mode == "ask":
        old = (await p.list_pending(uid, limit=5))[0]
        await p.approve(uid, old.id)
    await add(p, llm, uid, facts(("User switched from Java to Python", "preference", 0.6)))
    return p, llm, uid, other


async def test_conflict_supersedes_the_old_memory_and_keeps_it_restorable(engine, monkeypatch):
    p, _, uid, _ = await conflict(engine, monkeypatch)
    [new] = await p.list_all(uid, limit=10)
    [old] = await p.list_superseded(uid, limit=10)
    assert new.text == "User switched from Java to Python" and old.text == "User prefers Java for coding"
    assert old.status == "superseded" and old.superseded_by == new.id
    assert await p.search(uid, "prefers java coding", top_k=5) == []  # the old memory matches perfectly but is superseded
    assert [h.text for h in await p.search(uid, "java python switched", top_k=5)] == [new.text]
    assert [v.reason for v in await p.versions(uid, old.id)] == ["superseded"]

    back = await p.restore(uid, old.id)  # the user disagrees with the resolution
    assert back.status == "active" and back.superseded_by is None
    [now_superseded] = await p.list_superseded(uid, limit=10)
    assert now_superseded.id == new.id and now_superseded.superseded_by == back.id
    assert {v.reason for v in await p.versions(uid, back.id)} == {"superseded", "restored"}


# ---------- review inbox ("ask" mode) ----------
async def test_ask_mode_parks_new_facts_in_the_inbox_until_approved(engine):
    p, llm, uid, _ = await make(engine, facts(("User is learning Python", "skill", 0.8)), mode="ask")
    await p.add_exchange(uid, "x", "y")
    assert await p.list_all(uid, limit=10) == [] and await p.search(uid, "learning python", top_k=5) == []
    [pending] = await p.list_pending(uid, limit=10)
    assert pending.status == "pending"
    approved = await p.approve(uid, pending.id)
    assert approved.status == "active" and [h.text for h in await p.search(uid, "learning python", top_k=5)] == [pending.text]
    assert await p.list_pending(uid, limit=10) == []


async def test_ask_mode_reject_and_repeat_suggestions(engine):
    p, llm, uid, _ = await make(engine, facts(("User is learning Python", "skill", 0.8)), mode="ask")
    await p.add_exchange(uid, "x", "y")
    await p.add_exchange(uid, "x", "y")  # the same suggestion again must not pile up
    [pending] = await p.list_pending(uid, limit=10)
    assert await p.reject(uid, pending.id) is True and await p.reject(uid, pending.id) is False
    assert await p.list_pending(uid, limit=10) == [] and await p.list_all(uid, limit=10) == []


async def test_ask_mode_conflict_waits_for_approval_before_superseding(engine, monkeypatch):
    p, _, uid, _ = await conflict(engine, monkeypatch, mode="ask")
    [active] = await p.list_all(uid, limit=10)
    [pending] = await p.list_pending(uid, limit=10)
    assert active.text == "User prefers Java for coding" and pending.supersedes == active.id  # nothing changed yet
    await p.approve(uid, pending.id)
    assert [m.text for m in await p.list_all(uid, limit=10)] == ["User switched from Java to Python"]
    assert [m.id for m in await p.list_superseded(uid, limit=10)] == [active.id]


async def test_ask_mode_never_rewrites_an_existing_memory_silently(engine):
    p, llm, uid, _ = await make(engine, facts(("User is learning Python", "skill", 0.5)))
    await p.add_exchange(uid, "x", "y")  # created while still in auto mode
    async with p.maker() as s:
        await UserRepository(s).set_memory_mode(__import__("uuid").UUID(uid), "ask")
    await add(p, llm, uid, facts(("User is learning Python daily", "skill", 0.5)))
    assert [m.text for m in await p.list_all(uid, limit=10)] == ["User is learning Python"]
    assert await p.list_pending(uid, limit=10) == []  # same fact: nothing to ask


# ---------- guard inside the pipeline, edits, isolation ----------
async def test_sensitive_candidates_are_dropped_before_anything_is_embedded_or_saved(engine):
    p, llm, uid, _ = await make(engine, facts(("User's password is hunter2 today", "personal", 0.9),
                                              ("User is learning Python", "skill", 0.8)))
    await p.add_exchange(uid, "x", "y")
    assert [m.text for m in await p.list_all(uid, limit=10)] == ["User is learning Python"]


async def test_edits_keep_the_previous_text_in_history(engine):
    p, llm, uid, _ = await make(engine, facts(("User is learning Python", "skill", 0.8)))
    await p.add_exchange(uid, "x", "y")
    mid = (await p.list_all(uid, limit=1))[0].id
    await p.update(uid, mid, "User is learning Rust")
    await p.update(uid, mid, "User is learning Go")
    assert [(v.reason, v.content) for v in await p.versions(uid, mid)] == [
        ("edited", "User is learning Rust"), ("edited", "User is learning Python")]


async def test_other_users_cannot_use_the_lifecycle_methods(engine, monkeypatch):
    p, _, uid, other = await conflict(engine, monkeypatch)
    [old] = await p.list_superseded(uid, limit=5)
    [new] = await p.list_all(uid, limit=5)
    assert await p.restore(other, old.id) is None and await p.versions(other, old.id) is None
    assert await p.approve(other, new.id) is None and await p.reject(other, new.id) is False
    assert await p.list_pending(other, limit=5) == [] and await p.list_superseded(other, limit=5) == []
    assert (await p.list_superseded(uid, limit=5))[0].id == old.id  # untouched


# ---------- through the HTTP API ----------
@pytest.fixture
async def api(client, engine, provider):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    llm = RouterLLM(None)
    llm._fake = provider
    custom = CustomMemoryProvider(maker, llm, FakeEmbedder())
    app.dependency_overrides[get_memory_provider] = lambda: custom
    return client, custom, llm


async def test_inbox_over_http(api):
    client, _, _ = api
    h = await login(client)
    assert (await client.patch("/api/me/settings", json={"memory_mode": "ask"}, headers=h)).json()["memory_mode"] == "ask"
    assert (await client.patch("/api/me/settings", json={"memory_mode": "sometimes"}, headers=h)).status_code == 422
    await send(client, h, await new_convo(client, h), "I am learning Python for interviews.")
    await drain_background()
    assert (await client.get("/api/memories", headers=h)).json() == []
    [pending] = (await client.get("/api/memories?status=pending", headers=h)).json()
    assert pending["status"] == "pending"
    edited = await client.patch(f"/api/memories/{pending['id']}", json={"text": "I am learning Python every day."}, headers=h)
    assert edited.status_code == 200
    ok = await client.post(f"/api/memories/{pending['id']}/approve", headers=h)
    assert ok.status_code == 200 and ok.json()["status"] == "active"
    assert (await client.post(f"/api/memories/{pending['id']}/approve", headers=h)).status_code == 404
    versions = (await client.get(f"/api/memories/{pending['id']}/versions", headers=h)).json()
    assert [v["reason"] for v in versions] == ["edited"] and versions[0]["content"] == "I am learning Python for interviews."
    assert (await client.get("/api/me", headers=h)).json()["memory_mode"] == "ask"


async def test_lifecycle_endpoints_are_owner_only_and_need_a_token(api):
    client, custom, _ = api
    a, b = await login(client, "a@x.com"), await login(client, "b@x.com")
    await client.patch("/api/me/settings", json={"memory_mode": "ask"}, headers=a)
    await send(client, a, await new_convo(client, a), "I am learning Python for interviews.")
    await drain_background()
    [pending] = (await client.get("/api/memories?status=pending", headers=a)).json()
    mid = pending["id"]
    assert (await client.get("/api/memories?status=pending", headers=b)).json() == []
    for method, path in [("post", f"/api/memories/{mid}/approve"), ("post", f"/api/memories/{mid}/reject"),
                         ("post", f"/api/memories/{mid}/restore"), ("get", f"/api/memories/{mid}/versions")]:
        assert (await client.request(method.upper(), path, headers=b)).status_code == 404, path
        assert (await client.request(method.upper(), path)).status_code == 401, path
    assert (await client.post(f"/api/memories/{mid}/reject", headers=a)).status_code == 204
    assert (await client.get("/api/memories?status=pending", headers=a)).json() == []


async def test_editing_a_memory_into_a_secret_is_refused(api):
    client, custom, _ = api
    h = await login(client)
    await send(client, h, await new_convo(client, h), "I am learning Python for interviews.")
    await drain_background()
    mid = (await client.get("/api/memories", headers=h)).json()[0]["id"]
    r = await client.patch(f"/api/memories/{mid}", json={"text": "My password is hunter2"}, headers=h)
    assert r.status_code == 422 and "password" in r.json()["detail"]
    assert (await client.get("/api/memories", headers=h)).json()[0]["text"] == "I am learning Python for interviews."


async def test_default_providers_have_empty_lifecycle_lists(client, memory):
    h = await login(client)
    for status in ("pending", "superseded"):
        assert (await client.get(f"/api/memories?status={status}", headers=h)).json() == []
    assert (await client.post("/api/memories/abc/approve", headers=h)).status_code == 404
