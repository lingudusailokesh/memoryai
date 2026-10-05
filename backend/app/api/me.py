import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_session
from app.models import User
from app.repositories.users import UserRepository

router = APIRouter(prefix="/api", tags=["me"])


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    created_at: datetime
    memory_mode: str = "auto"
    name: str = ""
    memory_globally_enabled: bool = True
    memory_top_k: int = 5
    memory_threshold: float = 0.45
    custom_instructions: str = ""


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> User:
    return user


class SettingsIn(BaseModel):
    memory_mode: Literal["auto", "ask"] | None = None
    name: str | None = Field(default=None, max_length=100)
    memory_globally_enabled: bool | None = None
    memory_top_k: int | None = Field(default=None, ge=1, le=10)
    memory_threshold: float | None = Field(default=None, ge=0, le=1)
    custom_instructions: str | None = Field(default=None, max_length=2000)


@router.patch("/me/settings", response_model=UserOut)
async def update_settings(body: SettingsIn, user: User = Depends(get_current_user),
                          session: AsyncSession = Depends(get_session)) -> User:
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(422, "Provide at least one setting")
    await UserRepository(session).update_settings(user.id, **fields)
    await session.refresh(user)
    return user


@router.get("/me/export")
async def export_data(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    from app.models import Conversation, Memory, Message
    conversations = (await session.execute(__import__('sqlalchemy').select(Conversation).where(Conversation.user_id == user.id))).scalars().all()
    messages = (await session.execute(__import__('sqlalchemy').select(Message).join(Conversation).where(Conversation.user_id == user.id))).scalars().all()
    memories = (await session.execute(__import__('sqlalchemy').select(Memory).where(Memory.user_id == user.id))).scalars().all()
    return {"user": {"email": user.email, "name": user.name}, "conversations": [{"id": str(c.id), "title": c.title, "created_at": c.created_at} for c in conversations], "messages": [{"conversation_id": str(m.conversation_id), "role": m.role, "content": m.content, "created_at": m.created_at} for m in messages], "memories": [{"text": m.content, "category": m.category, "importance": m.importance, "status": m.status} for m in memories]}


@router.delete("/me", status_code=204)
async def delete_account(response: Response, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> None:
    await session.delete(user)
    await session.commit()
    response.delete_cookie("refresh_token", path="/api/auth")
