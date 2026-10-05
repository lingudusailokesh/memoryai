from unittest.mock import MagicMock

from app.memory.mem0_provider import Mem0Provider
from app.services.chat import drain_background
from tests.test_chat import history, login, new_convo, send

FACTS = ["I am learning Python.", "I prefer morning study sessions.", "I like graph problems."]


async def seed(client, memory, h, facts=FACTS) -> str:
    uid = (await client.get("/api/me", headers=h)).json()["id"]
    for f in facts:
        await memory.add_exchange(uid, f, "ok")
    return uid


async def test_list_newest_first_limit_and_search(client, memory):
    h = await login(client)
    await seed(client, memory, h)
    r = await client.get("/api/memories", headers=h)
    assert [m["text"] for m in r.json()] == FACTS[::-1]
    assert r.json()[0]["created_at"]
    assert len((await client.get("/api/memories?limit=2", headers=h)).json()) == 2
    found = (await client.get("/api/memories?q=python", headers=h)).json()
    assert [m["text"] for m in found] == [FACTS[0]]
    assert (await client.get("/api/memories?q=nonexistent", headers=h)).json() == []
    assert (await client.get("/api/memories")).status_code == 401


async def test_edit_and_validation(client, memory):
    h = await login(client)
    await seed(client, memory, h, FACTS[:1])
    mid = (await client.get("/api/memories", headers=h)).json()[0]["id"]
    r = await client.patch(f"/api/memories/{mid}", json={"text": "  I am learning Rust.  "}, headers=h)
    assert r.status_code == 200 and r.json()["text"] == "I am learning Rust."
    assert (await client.get("/api/memories", headers=h)).json()[0]["text"] == "I am learning Rust."
    assert (await client.patch(f"/api/memories/{mid}", json={"text": ""}, headers=h)).status_code == 422
    assert (await client.patch(f"/api/memories/{mid}", json={"text": "   "}, headers=h)).status_code == 422
    assert (await client.patch(f"/api/memories/{mid}", json={"text": "x" * 501}, headers=h)).status_code == 422


async def test_delete_one_then_404(client, memory):
    h = await login(client)
    await seed(client, memory, h)
    mid = (await client.get("/api/memories", headers=h)).json()[0]["id"]
    assert (await client.delete(f"/api/memories/{mid}", headers=h)).status_code == 204
    assert len((await client.get("/api/memories", headers=h)).json()) == 2
    assert (await client.delete(f"/api/memories/{mid}", headers=h)).status_code == 404


async def test_users_cannot_touch_each_others_memories(client, memory):
    a, b = await login(client, "a@x.com"), await login(client, "b@x.com")
    await seed(client, memory, a)
    mid = (await client.get("/api/memories", headers=a)).json()[0]["id"]
    assert (await client.get("/api/memories", headers=b)).json() == []
    assert (await client.patch(f"/api/memories/{mid}", json={"text": "pwned"}, headers=b)).status_code == 404
    assert (await client.delete(f"/api/memories/{mid}", headers=b)).status_code == 404
    await seed(client, memory, b, ["I like tea."])
    assert (await client.post("/api/memories/delete-all", json={"confirm": "DELETE"}, headers=b)).json() == {"deleted": 1}
    mine = (await client.get("/api/memories", headers=a)).json()
    assert len(mine) == 3 and mine[0]["text"] == FACTS[-1]  # untouched


async def test_delete_all_needs_exact_confirmation(client, memory):
    h = await login(client)
    await seed(client, memory, h)
    for bad in ({"confirm": "delete"}, {"confirm": ""}, {}):
        assert (await client.post("/api/memories/delete-all", json=bad, headers=h)).status_code == 422
    assert len((await client.get("/api/memories", headers=h)).json()) == 3
    assert (await client.post("/api/memories/delete-all", json={"confirm": "DELETE"}, headers=h)).json() == {"deleted": 3}
    assert (await client.get("/api/memories", headers=h)).json() == []


async def test_deleting_memories_also_scrubs_the_used_snapshots(client, memory):
    h = await login(client)
    await seed(client, memory, h, [FACTS[0], FACTS[2]])
    cid = await new_convo(client, h)
    await send(client, h, cid, "Any python or graph problems for me?")
    reply = (await history(client, h, cid))[-1]
    assert reply["memories_used_count"] == 2
    python_id = next(m["id"] for m in (await client.get("/api/memories", headers=h)).json() if "Python" in m["text"])
    await client.delete(f"/api/memories/{python_id}", headers=h)
    left = (await client.get(f"/api/messages/{reply['id']}/memories-used", headers=h)).json()
    assert [m["text"] for m in left] == [FACTS[2]]  # deleted text is gone from history too
    await client.post("/api/memories/delete-all", json={"confirm": "DELETE"}, headers=h)
    assert (await client.get(f"/api/messages/{reply['id']}/memories-used", headers=h)).json() == []
    assert (await history(client, h, cid))[-1]["memories_used_count"] == 0
    await drain_background()


async def test_mem0_adapter_checks_ownership_before_mutating():
    client = MagicMock()
    client.get.return_value = {"id": "m1", "memory": "secret", "user_id": "someone-else"}
    p = Mem0Provider(client=client)
    assert await p.get("me", "m1") is None
    assert await p.update("me", "m1", "pwned") is None and await p.delete("me", "m1") is False
    client.update.assert_not_called()
    client.delete.assert_not_called()
    client.get.return_value = {"id": "m1", "memory": "mine", "user_id": "me", "created_at": "2026-10-01"}
    assert await p.delete("me", "m1") is True
    client.delete.assert_called_once_with("m1")
    client.get_all.return_value = {"results": [{"id": "a", "memory": "x", "created_at": "1"},
                                               {"id": "b", "memory": "y", "created_at": "2"}]}
    assert [m.id for m in await p.list_all("me", limit=5)] == ["b", "a"]
    assert client.get_all.call_args.kwargs == {"filters": {"user_id": "me"}, "top_k": 5}
    assert await p.delete_all("me") == 2
    client.delete_all.assert_called_once_with(user_id="me")
