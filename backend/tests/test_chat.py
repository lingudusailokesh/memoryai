import json

from app.llm.base import LLMBusyError

PW = "correct-horse-1"


async def login(client, email="a@x.com") -> dict[str, str]:
    r = await client.post("/api/auth/register", json={"email": email, "password": PW})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def new_convo(client, h) -> str:
    return (await client.post("/api/conversations", json={}, headers=h)).json()["id"]


def parse_sse(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        name, data = block.splitlines()
        out.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


async def send(client, h, cid, content):
    r = await client.post(f"/api/conversations/{cid}/messages", json={"content": content}, headers=h)
    assert r.status_code == 200, r.text
    return parse_sse(r.text)


async def history(client, h, cid):
    return (await client.get(f"/api/conversations/{cid}/messages", headers=h)).json()


async def test_stream_tokens_then_done_and_persist(client):
    h = await login(client)
    cid = await new_convo(client, h)
    events = await send(client, h, cid, "hello there")
    names = [n for n, _ in events]
    assert names[-1] == "done" and set(names[:-1]) == {"token"}
    streamed = "".join(d["text"] for n, d in events if n == "token")
    assert "[Fake AI]" in streamed and "hello there" in streamed
    msgs = await history(client, h, cid)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["content"] == streamed and msgs[1]["id"] == events[-1][1]["message_id"]


async def test_auto_title_only_on_first_exchange(client):
    h = await login(client)
    cid = await new_convo(client, h)
    first = (await send(client, h, cid, "plan my dsa study week please"))[-1][1]
    assert first["title"] == "plan my dsa study week"
    assert (await client.get(f"/api/conversations/{cid}", headers=h)).json()["title"] == first["title"]
    assert (await send(client, h, cid, "thanks"))[-1][1]["title"] is None


async def test_busy_error_event_keeps_user_message_and_retry_works(client, provider):
    h = await login(client)
    cid = await new_convo(client, h)
    provider.fail_next = LLMBusyError("429")
    events = await send(client, h, cid, "hi")
    assert events == [("error", {"code": "model_busy", "message": "The model is busy right now. Try again in a moment.",
                                 "retryable": True})]
    msgs = await history(client, h, cid)
    assert [m["role"] for m in msgs] == ["user"]  # nothing fake saved, user text kept
    r = await client.post(f"/api/conversations/{cid}/messages/{msgs[-1]['id']}/regenerate", headers=h)  # retry
    assert parse_sse(r.text)[-1][0] == "done"
    assert [m["role"] for m in await history(client, h, cid)] == ["user", "assistant"]


async def test_error_markers_and_no_internal_leak(client):
    h = await login(client)
    cid = await new_convo(client, h)
    ev = await send(client, h, cid, "x [[fail]]")
    assert ev[0][1]["code"] == "model_unavailable" and "fake" not in json.dumps(ev)


async def test_regenerate_replaces_last_reply_only(client):
    h = await login(client)
    cid = await new_convo(client, h)
    await send(client, h, cid, "hi")
    msgs = await history(client, h, cid)
    old_assistant = msgs[-1]["id"]
    r = await client.post(f"/api/conversations/{cid}/messages/{old_assistant}/regenerate", headers=h)
    new_id = parse_sse(r.text)[-1][1]["message_id"]
    after = await history(client, h, cid)
    assert [m["role"] for m in after] == ["user", "assistant"] and after[-1]["id"] == new_id != old_assistant
    stale = await client.post(f"/api/conversations/{cid}/messages/{msgs[0]['id']}/regenerate", headers=h)
    assert stale.status_code == 409


async def test_chat_isolation_and_auth(client):
    a, b = await login(client, "a@x.com"), await login(client, "b@x.com")
    cid = await new_convo(client, a)
    await send(client, a, cid, "secret")
    mid = (await history(client, a, cid))[-1]["id"]
    body = {"content": "intrude"}
    assert (await client.post(f"/api/conversations/{cid}/messages", json=body, headers=b)).status_code == 404
    assert (await client.post(f"/api/conversations/{cid}/messages/{mid}/regenerate", headers=b)).status_code == 404
    assert (await client.get(f"/api/conversations/{cid}/messages", headers=b)).status_code == 404
    assert (await client.patch(f"/api/conversations/{cid}", json={"title": "x"}, headers=b)).status_code == 404
    assert (await client.delete(f"/api/conversations/{cid}", headers=b)).status_code == 404
    assert len(await history(client, a, cid)) == 2  # untouched
    assert (await client.post(f"/api/conversations/{cid}/messages", json=body)).status_code == 401


async def test_validation_patch_delete(client):
    h = await login(client)
    cid = await new_convo(client, h)
    assert (await client.post(f"/api/conversations/{cid}/messages", json={"content": ""}, headers=h)).status_code == 422
    big = {"content": "x" * 9000}
    assert (await client.post(f"/api/conversations/{cid}/messages", json=big, headers=h)).status_code == 422
    p = await client.patch(f"/api/conversations/{cid}", json={"title": "Renamed", "memory_enabled": False}, headers=h)
    assert p.json()["title"] == "Renamed" and p.json()["memory_enabled"] is False
    assert (await client.delete(f"/api/conversations/{cid}", headers=h)).status_code == 204
    assert (await client.get(f"/api/conversations/{cid}", headers=h)).status_code == 404
