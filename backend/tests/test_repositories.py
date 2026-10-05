import pytest

from app.repositories.conversations import ConversationRepository
from app.repositories.messages import MessageRepository
from app.repositories.users import EmailAlreadyExists, UserRepository


async def test_user_create_and_lookup_normalizes_email(session):
    repo = UserRepository(session)
    u = await repo.create("  Ada@Example.com ", "hash")
    assert u.email == "ada@example.com"
    assert (await repo.get_by_email("ADA@example.com")).id == u.id


async def test_duplicate_email_rejected(session):
    repo = UserRepository(session)
    await repo.create("a@x.com", "h")
    with pytest.raises(EmailAlreadyExists):
        await repo.create("A@x.com", "h")


async def test_conversation_crud(session):
    u = await UserRepository(session).create("a@x.com", "h")
    repo = ConversationRepository(session)
    c = await repo.create(u.id, "Plan")
    assert (await repo.get(u.id, c.id)).title == "Plan"
    updated = await repo.update(u.id, c.id, title="Renamed", memory_enabled=False)
    assert updated.title == "Renamed" and updated.memory_enabled is False
    assert len(await repo.list(u.id)) == 1
    assert await repo.delete(u.id, c.id) is True
    assert await repo.get(u.id, c.id) is None


async def test_user_isolation(session):
    users = UserRepository(session)
    a, b = await users.create("a@x.com", "h"), await users.create("b@x.com", "h")
    convos, msgs = ConversationRepository(session), MessageRepository(session)
    c = await convos.create(a.id)
    await msgs.add(a.id, c.id, "user", "secret")
    assert await convos.get(b.id, c.id) is None
    assert await convos.update(b.id, c.id, title="hacked") is None
    assert await convos.delete(b.id, c.id) is False
    assert await msgs.add(b.id, c.id, "user", "x") is None
    assert list(await msgs.list(b.id, c.id)) == []
    assert len(await msgs.list(a.id, c.id)) == 1


async def test_messages_ordered_and_cascade_on_delete(session):
    u = await UserRepository(session).create("a@x.com", "h")
    convos, msgs = ConversationRepository(session), MessageRepository(session)
    c = await convos.create(u.id)
    for i, role in enumerate(["user", "assistant", "user"]):
        await msgs.add(u.id, c.id, role, f"m{i}")
    assert [m.content for m in await msgs.list(u.id, c.id)] == ["m0", "m1", "m2"]
    await convos.delete(u.id, c.id)
    assert list(await msgs.list(u.id, c.id)) == []


async def test_invalid_role_rejected(session):
    from sqlalchemy.exc import IntegrityError
    u = await UserRepository(session).create("a@x.com", "h")
    c = await ConversationRepository(session).create(u.id)
    with pytest.raises(IntegrityError):
        await MessageRepository(session).add(u.id, c.id, "robot", "x")
