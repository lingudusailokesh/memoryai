import uuid
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, Message


class MessageRepository:
    """Ownership is checked through the parent conversation's user_id."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _owned(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> bool:
        res = await self.session.execute(
            select(Conversation.id).where(Conversation.id == conversation_id, Conversation.user_id == user_id)
        )
        return res.scalar_one_or_none() is not None

    async def add(self, user_id: uuid.UUID, conversation_id: uuid.UUID, role: str, content: str,
                  memories_used: list[dict[str, object]] | None = None) -> Message | None:
        if not await self._owned(user_id, conversation_id):
            return None
        msg = Message(conversation_id=conversation_id, role=role, content=content, memories_used=memories_used)
        self.session.add(msg)
        await self.session.commit()
        return msg

    async def list(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> Sequence[Message]:
        res = await self.session.execute(
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Message.conversation_id == conversation_id, Conversation.user_id == user_id)
            .order_by(Message.created_at, Message.id)
        )
        return res.scalars().all()

    async def recent(self, user_id: uuid.UUID, conversation_id: uuid.UUID, limit: int) -> Sequence[Message]:
        """The last `limit` messages, oldest first."""
        res = await self.session.execute(
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Message.conversation_id == conversation_id, Conversation.user_id == user_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
        return list(reversed(res.scalars().all()))

    async def last(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> Message | None:
        rows = await self.recent(user_id, conversation_id, 1)
        return rows[0] if rows else None

    async def delete(self, user_id: uuid.UUID, conversation_id: uuid.UUID, message_id: uuid.UUID) -> bool:
        owned = select(Conversation.id).where(Conversation.id == conversation_id, Conversation.user_id == user_id)
        res = await self.session.execute(
            delete(Message).where(Message.id == message_id, Message.conversation_id.in_(owned))
        )
        await self.session.commit()
        return res.rowcount > 0

    async def get_for_user(self, user_id: uuid.UUID, message_id: uuid.UUID) -> Message | None:
        res = await self.session.execute(
            select(Message).join(Conversation, Conversation.id == Message.conversation_id)
            .where(Message.id == message_id, Conversation.user_id == user_id)
        )
        return res.scalar_one_or_none()

    async def scrub_memories_used(self, user_id: uuid.UUID, memory_ids: set[str] | None) -> int:
        """Remove deleted memories from the "used" snapshots (None = remove all of this user's).

        Deleting a memory must also delete its text everywhere we copied it.
        """
        res = await self.session.execute(
            select(Message).join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.user_id == user_id, Message.role == "assistant")
        )
        changed = 0
        for m in res.scalars():
            if not m.memories_used:
                continue
            kept = [] if memory_ids is None else [x for x in m.memories_used if x.get("id") not in memory_ids]
            if len(kept) != len(m.memories_used):
                m.memories_used = kept or None  # new object, so SQLAlchemy sees the change
                changed += 1
        await self.session.commit()
        return changed
