from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_session
from app.models import Conversation, Memory, Message, User, UsageEvent

router = APIRouter(prefix="/api", tags=["analytics"])


class FocusOut(BaseModel):
    text: str
    generated_at: datetime


@router.get("/search")
async def search(q: str = Query(min_length=1, max_length=100), user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    term = f"%{q.strip()}%"
    conversations = (await session.execute(select(Conversation).where(Conversation.user_id == user.id, Conversation.title.ilike(term)).order_by(Conversation.updated_at.desc()).limit(8))).scalars().all()
    memories = (await session.execute(select(Memory).where(Memory.user_id == user.id, Memory.status == "active", Memory.content.ilike(term)).order_by(Memory.updated_at.desc()).limit(8))).scalars().all()
    return {"conversations": [{"id": str(item.id), "title": item.title} for item in conversations], "memories": [{"id": str(item.id), "text": item.content} for item in memories]}


@router.get("/dashboard/summary")
async def dashboard_summary(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    uid = user.id
    conversations = (await session.scalar(select(func.count()).select_from(Conversation).where(Conversation.user_id == uid))) or 0
    memories = (await session.scalar(select(func.count()).select_from(Memory).where(Memory.user_id == uid, Memory.status == "active"))) or 0
    messages = (await session.scalar(select(func.count()).select_from(Message).join(Conversation).where(Conversation.user_id == uid))) or 0
    assistant = (await session.scalar(select(func.count()).select_from(Message).join(Conversation).where(Conversation.user_id == uid, Message.role == "assistant"))) or 0
    used = (await session.scalar(select(func.count()).select_from(Message).join(Conversation).where(Conversation.user_id == uid, Message.role == "assistant", Message.memories_used.is_not(None)))) or 0
    start = datetime.now(UTC) - timedelta(days=6)
    rows = (await session.execute(select(func.date(Message.created_at), func.count()).join(Conversation).where(Conversation.user_id == uid, Message.created_at >= start).group_by(func.date(Message.created_at)).order_by(func.date(Message.created_at)))).all()
    activity = [{"date": str(day), "messages": count} for day, count in rows]
    recent = (await session.execute(select(Memory).where(Memory.user_id == uid, Memory.status == "active").order_by(Memory.updated_at.desc()).limit(5))).scalars().all()
    return {"stats": {"conversations": conversations, "memories": memories, "messages": messages, "retrieval_rate": round(used / assistant * 100) if assistant else 0}, "activity": activity, "recent_memories": [{"id": str(m.id), "text": m.content, "category": m.category, "importance": m.importance, "created_at": m.created_at} for m in recent]}


@router.get("/analytics")
async def analytics(days: int = 30, user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> dict:
    if days not in (7, 30, 90):
        raise HTTPException(422, "days must be 7, 30, or 90")
    start = datetime.now(UTC) - timedelta(days=days - 1)
    msg_rows = (await session.execute(select(func.date(Message.created_at), func.count()).join(Conversation).where(Conversation.user_id == user.id, Message.created_at >= start).group_by(func.date(Message.created_at)).order_by(func.date(Message.created_at)))).all()
    memory_rows = (await session.execute(select(func.date(Memory.created_at), func.count()).where(Memory.user_id == user.id, Memory.created_at >= start).group_by(func.date(Memory.created_at)).order_by(func.date(Memory.created_at)))).all()
    usage = (await session.execute(select(func.avg(UsageEvent.latency_ms), func.sum(UsageEvent.tokens_in), func.sum(UsageEvent.tokens_out)).where(UsageEvent.user_id == user.id, UsageEvent.created_at >= start))).one()
    return {"messages": [{"date": str(day), "value": value} for day, value in msg_rows], "memories": [{"date": str(day), "value": value} for day, value in memory_rows], "average_latency_ms": round(usage[0] or 0), "tokens_in": usage[1] or 0, "tokens_out": usage[2] or 0}


@router.get("/dashboard/focus", response_model=FocusOut)
async def focus(user: User = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> FocusOut:
    goals = (await session.execute(select(Memory).where(Memory.user_id == user.id, Memory.status == "active").order_by(Memory.pinned.desc(), Memory.importance.desc()).limit(2))).scalars().all()
    text = "Add a goal or project memory to receive a tailored focus suggestion."
    if goals:
        text = "Today's focus: make one small, concrete step on " + " and ".join(m.content.rstrip(".") for m in goals) + "."
    return FocusOut(text=text, generated_at=datetime.now(UTC))
