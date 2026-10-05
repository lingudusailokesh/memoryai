from sqlalchemy.ext.asyncio import async_sessionmaker

from app.llm.fake import FakeLLMProvider
from app.repositories.conversations import ConversationRepository
from app.repositories.messages import MessageRepository
from app.repositories.users import UserRepository
from app.memory.fake import FakeMemoryProvider
from app.services.chat import ChatService


async def setup(engine):
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        user = await UserRepository(s).create("a@x.com", "h")
        convo = await ConversationRepository(s).create(user.id)
    return maker, user, convo


async def test_stop_saves_partial_reply(engine):
    maker, user, convo = await setup(engine)
    svc = ChatService(maker, FakeLLMProvider(), FakeMemoryProvider())
    turn = await svc.start_turn(user.id, convo.id, "one two three four")
    gen = svc.stream(user.id, turn)
    async for ev in gen:
        if ev.name == "token":
            break  # the user pressed Stop
    await gen.aclose()
    async with maker() as s:
        msgs = await MessageRepository(s).list(user.id, convo.id)
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert msgs[1].content.strip() == "[Fake"  # exactly what had streamed before stopping


async def test_context_window_is_bounded(engine):
    maker, user, convo = await setup(engine)
    async with maker() as s:
        for i in range(30):
            await MessageRepository(s).add(user.id, convo.id, "user" if i % 2 == 0 else "assistant", f"m{i}")
    turn = await ChatService(maker, FakeLLMProvider(), FakeMemoryProvider()).start_turn(user.id, convo.id, "latest")
    assert len(turn.messages) == 1 + 20 and turn.messages[0].role == "system"
    assert turn.messages[-1].content == "latest"
