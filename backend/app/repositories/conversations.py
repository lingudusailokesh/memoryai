import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation


class ConversationRepository:
    """Every query takes user_id: a user can never read or change another user's data."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, user_id: uuid.UUID, title: str = "New conversation",
                     memory_enabled: bool = True) -> Conversation:
        convo = Conversation(user_id=user_id, title=title, memory_enabled=memory_enabled)
        self.session.add(convo)
        await self.session.commit()
        return convo

    async def get(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> Conversation | None:
        res = await self.session.execute(
            select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id)
        )
        return res.scalar_one_or_none()

    async def list(self, user_id: uuid.UUID, limit: int = 50, offset: int = 0) -> Sequence[Conversation]:
        res = await self.session.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc(), Conversation.id)
            .limit(limit)
            .offset(offset)
        )
        return res.scalars().all()

    async def update(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, *, title: str | None = None,
        memory_enabled: bool | None = None,
    ) -> Conversation | None:
        convo = await self.get(user_id, conversation_id)
        if convo is None:
            return None
        if title is not None:
            convo.title = title
        if memory_enabled is not None:
            convo.memory_enabled = memory_enabled
        await self.session.commit()
        await self.session.refresh(convo)  # updated_at is set by the DB (onupdate); reload it
        return convo

    async def delete(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> bool:
        res = await self.session.execute(
            delete(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id)
        )
        await self.session.commit()
        return res.rowcount > 0

    async def touch(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
        await self.session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id, Conversation.user_id == user_id)
            .values(updated_at=func.now())
        )
        await self.session.commit()
