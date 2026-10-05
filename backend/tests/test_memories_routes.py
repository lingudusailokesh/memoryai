import pytest

from app.main import app
from tests.test_chat import login

MEMORY_ROUTES = [
    ("get", "/api/memories"),
    ("patch", "/api/memories/{memory_id}"),
    ("delete", "/api/memories/{memory_id}"),
    ("post", "/api/memories/delete-all"),
    ("post", "/api/memories/{memory_id}/approve"), ("post", "/api/memories/{memory_id}/reject"),
    ("post", "/api/memories/{memory_id}/restore"), ("get", "/api/memories/{memory_id}/versions"),
]
EXISTING_ROUTES = [  # Stage 1-5 routes must stay registered
    ("get", "/api/health"), ("post", "/api/auth/register"), ("post", "/api/auth/login"),
    ("post", "/api/auth/refresh"), ("post", "/api/auth/logout"),
    ("post", "/api/auth/forgot-password"), ("post", "/api/auth/reset-password"), ("get", "/api/me"), ("patch", "/api/me/settings"),
    ("get", "/api/conversations"), ("post", "/api/conversations"),
    ("get", "/api/conversations/{conversation_id}"), ("patch", "/api/conversations/{conversation_id}"),
    ("delete", "/api/conversations/{conversation_id}"),
    ("get", "/api/conversations/{conversation_id}/messages"),
    ("post", "/api/conversations/{conversation_id}/messages"),
    ("post", "/api/conversations/{conversation_id}/messages/{message_id}/regenerate"),
    ("get", "/api/messages/{message_id}/memories-used"),
]


@pytest.mark.parametrize(("method", "path"), MEMORY_ROUTES + EXISTING_ROUTES)
def test_route_is_registered_in_the_app(method, path):
    # Reads the same OpenAPI document that http://localhost:8000/docs renders.
    assert method in app.openapi()["paths"].get(path, {}), f"{method.upper()} {path} is not registered"


@pytest.mark.parametrize(("method", "path"), MEMORY_ROUTES)
async def test_memory_endpoints_require_authentication(client, method, path):
    r = await client.request(method.upper(), path.format(memory_id="abc"), json={"text": "x", "confirm": "DELETE"})
    assert r.status_code == 401  # 401 = route exists but needs a token; 404/405 would mean it's missing


async def test_memories_api_end_to_end_with_ownership(client, memory):
    a, b = await login(client, "a@x.com"), await login(client, "b@x.com")
    uid_a = (await client.get("/api/me", headers=a)).json()["id"]
    for fact in ("I like Python.", "I study at night."):
        await memory.add_exchange(uid_a, fact, "ok")

    # list memories (own only)
    mine = await client.get("/api/memories", headers=a)
    assert mine.status_code == 200 and [m["text"] for m in mine.json()] == ["I study at night.", "I like Python."]
    assert (await client.get("/api/memories", headers=b)).json() == []
    first, second = mine.json()[0]["id"], mine.json()[1]["id"]

    # another user's memory cannot be modified or deleted
    assert (await client.patch(f"/api/memories/{first}", json={"text": "hacked"}, headers=b)).status_code == 404
    assert (await client.delete(f"/api/memories/{first}", headers=b)).status_code == 404
    assert [m["text"] for m in (await client.get("/api/memories", headers=a)).json()] == ["I study at night.", "I like Python."]

    # update own memory
    upd = await client.patch(f"/api/memories/{first}", json={"text": "I study in the morning."}, headers=a)
    assert upd.status_code == 200 and upd.json()["text"] == "I study in the morning."

    # delete own memory
    assert (await client.delete(f"/api/memories/{second}", headers=a)).status_code == 204
    assert [m["id"] for m in (await client.get("/api/memories", headers=a)).json()] == [first]

    # delete-all requires {"confirm": "DELETE"}
    for bad in ({}, {"confirm": "delete"}, {"confirm": "yes"}):
        assert (await client.post("/api/memories/delete-all", json=bad, headers=a)).status_code == 422
    assert len((await client.get("/api/memories", headers=a)).json()) == 1
    ok = await client.post("/api/memories/delete-all", json={"confirm": "DELETE"}, headers=a)
    assert ok.status_code == 200 and ok.json() == {"deleted": 1}
    assert (await client.get("/api/memories", headers=a)).json() == []
