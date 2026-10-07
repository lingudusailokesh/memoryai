import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from sqlalchemy import select

from app.config import settings
from app.models import User

PW = "correct-horse-1"


async def register(client, email="a@x.com", pw=PW) -> str:
    r = await client.post("/api/auth/register", json={"email": email, "password": pw})
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_register_returns_token_and_httponly_cookie(client):
    token = await register(client)
    set_cookie = (await client.post("/api/auth/login", json={"email": "a@x.com", "password": PW})).headers["set-cookie"]
    assert "HttpOnly" in set_cookie and "Path=/api/auth" in set_cookie and "SameSite=lax" in set_cookie
    me = await client.get("/api/me", headers=bearer(token))
    assert me.status_code == 200 and me.json()["email"] == "a@x.com"
    assert "password" not in me.text


async def test_password_is_stored_hashed(client, session):
    await register(client)
    user = (await session.execute(select(User))).scalar_one()
    assert user.password_hash.startswith("$argon2id$") and PW not in user.password_hash


async def test_duplicate_email_is_409_case_insensitive(client):
    await register(client, "a@x.com")
    r = await client.post("/api/auth/register", json={"email": "A@X.com", "password": PW})
    assert r.status_code == 409


async def test_register_validation(client):
    assert (await client.post("/api/auth/register", json={"email": "a@x.com", "password": "short"})).status_code == 422
    assert (await client.post("/api/auth/register", json={"email": "nope", "password": PW})).status_code == 422


async def test_login_success_and_failures_look_identical(client):
    await register(client)
    ok = await client.post("/api/auth/login", json={"email": "a@x.com", "password": PW})
    assert ok.status_code == 200
    bad_pw = await client.post("/api/auth/login", json={"email": "a@x.com", "password": "wrong-password"})
    no_user = await client.post("/api/auth/login", json={"email": "ghost@x.com", "password": PW})
    assert bad_pw.status_code == no_user.status_code == 401
    assert bad_pw.json() == no_user.json()


async def test_email_normalization_survives_logout_and_login(client):
    await register(client, "  Ada@EXAMPLE.com  ")
    assert (await client.post("/api/auth/logout")).status_code == 204
    assert (await client.post("/api/auth/refresh")).status_code == 401
    r = await client.post("/api/auth/login", json={"email": " ADA@example.COM ", "password": PW})
    assert r.status_code == 200, r.text
    me = await client.get("/api/me", headers=bearer(r.json()["access_token"]))
    assert me.status_code == 200 and me.json()["email"] == "ada@example.com"


@pytest.mark.parametrize("password", [" CaseSensitive-123 ", "Pässwörd-漢字-123"])
async def test_password_is_verified_exactly_as_registered(client, password):
    await register(client, pw=password)
    correct = await client.post("/api/auth/login", json={"email": "a@x.com", "password": password})
    assert correct.status_code == 200
    changed = await client.post("/api/auth/login", json={"email": "a@x.com", "password": password.swapcase()})
    assert changed.status_code == 401
    if password != password.strip():
        trimmed = await client.post("/api/auth/login", json={"email": "a@x.com", "password": password.strip()})
        assert trimmed.status_code == 401


async def test_registration_is_scoped_to_its_database(client):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.db.base import Base
    from app.services.auth import AuthService, InvalidCredentials

    await register(client)
    other_database = create_async_engine("sqlite+aiosqlite://")
    try:
        async with other_database.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(other_database)() as session:
            with pytest.raises(InvalidCredentials):
                await AuthService(session).login("a@x.com", PW)
    finally:
        await other_database.dispose()


async def test_seeded_demo_can_log_in_through_validated_api(client, engine, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from scripts import seed

    monkeypatch.setattr(seed, "SessionLocal", async_sessionmaker(engine, expire_on_commit=False))
    await seed.main()
    async with async_sessionmaker(engine)() as session:
        email = (await session.execute(select(User.email))).scalar_one()
    r = await client.post("/api/auth/login", json={"email": email, "password": "demo-password-123"})
    assert r.status_code == 200, r.text
    me = await client.get("/api/me", headers=bearer(r.json()["access_token"]))
    assert me.status_code == 200 and me.json()["name"] == "Demo User"


async def test_refresh_rotates_and_old_token_is_dead(client):
    await register(client)
    old = client.cookies.get("refresh_token")
    r = await client.post("/api/auth/refresh")
    assert r.status_code == 200
    assert client.cookies.get("refresh_token") != old
    assert (await client.get("/api/me", headers=bearer(r.json()["access_token"]))).status_code == 200
    client.cookies.clear()
    reuse = await client.post("/api/auth/refresh", headers={"Cookie": f"refresh_token={old}"})
    assert reuse.status_code == 401


async def test_refresh_without_cookie_is_401(client):
    assert (await client.post("/api/auth/refresh")).status_code == 401


async def test_logout_revokes_refresh_token(client):
    await register(client)
    token = client.cookies.get("refresh_token")
    assert (await client.post("/api/auth/logout")).status_code == 204
    client.cookies.clear()
    r = await client.post("/api/auth/refresh", headers={"Cookie": f"refresh_token={token}"})
    assert r.status_code == 401


async def test_protected_route_rejects_bad_tokens(client):
    assert (await client.get("/api/me")).status_code == 401
    assert (await client.get("/api/me", headers=bearer("garbage"))).status_code == 401
    now = datetime.now(timezone.utc)
    claims = {"sub": str(uuid.uuid4()), "type": "access", "exp": now - timedelta(minutes=1)}
    expired = jwt.encode(claims, settings.jwt_secret, algorithm="HS256")
    assert (await client.get("/api/me", headers=bearer(expired))).status_code == 401
    forged = jwt.encode({**claims, "exp": now + timedelta(hours=1)}, "x" * 40, algorithm="HS256")
    assert (await client.get("/api/me", headers=bearer(forged))).status_code == 401


async def test_valid_token_for_unknown_user_is_401(client):
    claims = {"sub": str(uuid.uuid4()), "type": "access", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}
    token = jwt.encode(claims, settings.jwt_secret, algorithm="HS256")
    assert (await client.get("/api/me", headers=bearer(token))).status_code == 401


async def test_users_cannot_see_each_others_conversations(client):
    a = await register(client, "a@x.com")
    b = await register(client, "b@x.com")
    created = await client.post("/api/conversations", json={"title": "A private"}, headers=bearer(a))
    cid = created.json()["id"]
    assert (await client.get(f"/api/conversations/{cid}", headers=bearer(a))).status_code == 200
    assert (await client.get(f"/api/conversations/{cid}", headers=bearer(b))).status_code == 404
    assert (await client.get("/api/conversations", headers=bearer(b))).json() == []
    assert [c["id"] for c in (await client.get("/api/conversations", headers=bearer(a))).json()] == [cid]
    assert (await client.get("/api/conversations")).status_code == 401
