import os
from collections.abc import AsyncIterator

os.environ.setdefault("JWT_SECRET", "test-only-secret-0123456789-0123456789")

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import app.models  # noqa: E402,F401  (register tables)
from app.db.base import Base  # noqa: E402
from app.api.conversations import get_chat_service  # noqa: E402,F401
from app.db.session import get_session, get_sessionmaker  # noqa: E402
from app.llm.factory import get_provider  # noqa: E402
from app.mailer.senders import EmailSender, get_email_sender  # noqa: E402
from app.llm.fake import FakeLLMProvider  # noqa: E402
from app.memory.factory import get_memory_provider  # noqa: E402
from app.memory.fake import FakeMemoryProvider  # noqa: E402
from app.services.chat import drain_background  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    # In-memory SQLite: fast, no Docker needed. StaticPool = one shared connection for all sessions.
    eng = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})

    @event.listens_for(eng.sync_engine, "connect")
    def _fk_on(dbapi_conn, _):  # SQLite ignores foreign keys unless enabled
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s


@pytest.fixture
def provider() -> FakeLLMProvider:
    return FakeLLMProvider()


class OutboxEmailSender(EmailSender):
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append((to, subject, body))


@pytest.fixture
def mailer() -> OutboxEmailSender:
    return OutboxEmailSender()


@pytest.fixture
def memory() -> FakeMemoryProvider:
    return FakeMemoryProvider()


@pytest.fixture
async def client(engine: AsyncEngine, provider: FakeLLMProvider, memory: FakeMemoryProvider,
                 mailer: OutboxEmailSender) -> AsyncIterator[AsyncClient]:
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def override() -> AsyncIterator[AsyncSession]:
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = override
    app.dependency_overrides[get_sessionmaker] = lambda: maker
    app.dependency_overrides[get_provider] = lambda: provider
    app.dependency_overrides[get_memory_provider] = lambda: memory
    app.dependency_overrides[get_email_sender] = lambda: mailer
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await drain_background()
    app.dependency_overrides.clear()
