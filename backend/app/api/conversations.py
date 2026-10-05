import json
import uuid
from datetime import UTC, datetime, timedelta
from collections.abc import AsyncIterator
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import get_current_user
from app.config import settings
from app.core.rate_limit import RateLimitError, limiter
from app.db.session import get_session, get_sessionmaker
from app.llm.base import LLMProvider
from app.llm.factory import get_provider
from app.memory.base import MemoryProvider
from app.memory.factory import get_memory_provider
from app.models import Conversation, Message, UsageEvent, User
from app.repositories.conversations import ConversationRepository
from app.repositories.messages import MessageRepository
from app.services.chat import ChatEvent, ChatService, ConversationNotFound, InvalidRegenerateTarget, Turn

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    memory_enabled: bool
    created_at: datetime
    updated_at: datetime


class ConversationIn(BaseModel):
    title: str = Field(default="New conversation", min_length=1, max_length=200)
    memory_enabled: bool = True


class ConversationPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    memory_enabled: bool | None = None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    role: str
    content: str
    created_at: datetime
    memories_used_count: int = 0


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=settings.max_message_chars)


def get_chat_service(
    maker: async_sessionmaker[AsyncSession] = Depends(get_sessionmaker),
    provider: LLMProvider = Depends(get_provider),
    memory: MemoryProvider = Depends(get_memory_provider),
) -> ChatService:
    return ChatService(maker, provider, memory)


NOT_FOUND = HTTPException(404, "Conversation not found")  # 404, not 403: don't reveal others' IDs


@router.post("", status_code=201, response_model=ConversationOut)
async def create(body: ConversationIn, user: User = Depends(get_current_user),
                 session: AsyncSession = Depends(get_session)) -> Conversation:
    return await ConversationRepository(session).create(user.id, body.title, body.memory_enabled)


@router.get("", response_model=list[ConversationOut])
async def list_(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0),
                user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    return await ConversationRepository(session).list(user.id, limit, offset)


@router.get("/{conversation_id}", response_model=ConversationOut)
async def get(conversation_id: uuid.UUID, user: User = Depends(get_current_user),
              session: AsyncSession = Depends(get_session)) -> Conversation:
    convo = await ConversationRepository(session).get(user.id, conversation_id)
    if convo is None:
        raise NOT_FOUND
    return convo


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def patch(conversation_id: uuid.UUID, body: ConversationPatch, user: User = Depends(get_current_user),
                session: AsyncSession = Depends(get_session)) -> Conversation:
    convo = await ConversationRepository(session).update(
        user.id, conversation_id, title=body.title, memory_enabled=body.memory_enabled)
    if convo is None:
        raise NOT_FOUND
    return convo


@router.delete("/{conversation_id}", status_code=204)
async def delete(conversation_id: uuid.UUID, user: User = Depends(get_current_user),
                 session: AsyncSession = Depends(get_session)) -> None:
    if not await ConversationRepository(session).delete(user.id, conversation_id):
        raise NOT_FOUND


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def messages(conversation_id: uuid.UUID, user: User = Depends(get_current_user),
                   session: AsyncSession = Depends(get_session)) -> list[Message]:
    if await ConversationRepository(session).get(user.id, conversation_id) is None:
        raise NOT_FOUND
    return list(await MessageRepository(session).list(user.id, conversation_id))


def _sse(event: ChatEvent) -> str:
    return f"event: {event.name}\ndata: {json.dumps(event.data)}\n\n"


def _stream_response(service: ChatService, user_id: uuid.UUID, turn: Turn) -> StreamingResponse:
    async def body() -> AsyncIterator[str]:
        async for event in service.stream(user_id, turn):
            yield _sse(event)

    return StreamingResponse(body(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/{conversation_id}/messages")
async def send_message(conversation_id: uuid.UUID, body: MessageIn, user: User = Depends(get_current_user),
                       service: ChatService = Depends(get_chat_service), session: AsyncSession = Depends(get_session)) -> StreamingResponse:
    try:
        limiter.check(f"chat:{user.id}", settings.rate_limit_chat_per_minute, timedelta(minutes=1))
    except RateLimitError:
        raise HTTPException(429, "Too many messages. Please wait a minute and try again.") from None
    started = datetime.now(UTC) - timedelta(days=1)
    used = (await session.scalar(__import__("sqlalchemy").select(__import__("sqlalchemy").func.count()).select_from(UsageEvent).where(UsageEvent.user_id == user.id, UsageEvent.kind == "chat", UsageEvent.created_at >= started))) or 0
    if used >= settings.daily_request_budget:
        raise HTTPException(429, "Today's free request budget is used. Try again tomorrow.")
    try:
        turn = await service.start_turn(user.id, conversation_id, body.content)
    except ConversationNotFound:
        raise NOT_FOUND from None
    return _stream_response(service, user.id, turn)


@router.post("/{conversation_id}/messages/{message_id}/regenerate")
async def regenerate(conversation_id: uuid.UUID, message_id: uuid.UUID, user: User = Depends(get_current_user),
                     service: ChatService = Depends(get_chat_service)) -> StreamingResponse:
    try:
        turn = await service.start_regenerate(user.id, conversation_id, message_id)
    except ConversationNotFound:
        raise NOT_FOUND from None
    except InvalidRegenerateTarget:
        raise HTTPException(409, "Only the latest message can be regenerated") from None
    return _stream_response(service, user.id, turn)
