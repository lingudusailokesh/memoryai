import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_session
from app.models import User
from app.repositories.messages import MessageRepository

router = APIRouter(prefix="/api/messages", tags=["messages"])


class MemoryUsedOut(BaseModel):
    id: str
    text: str
    score: float | None = None
    category: str | None = None


@router.get("/{message_id}/memories-used", response_model=list[MemoryUsedOut])
async def memories_used(message_id: uuid.UUID, user: User = Depends(get_current_user),
                        session: AsyncSession = Depends(get_session)) -> list[dict[str, object]]:
    msg = await MessageRepository(session).get_for_user(user.id, message_id)
    if msg is None:
        raise HTTPException(404, "Message not found")
    return msg.memories_used or []
