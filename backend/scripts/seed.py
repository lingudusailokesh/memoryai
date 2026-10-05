"""Create a safe local demo account and sample activity.

Run: cd backend && python scripts/seed.py
"""
import asyncio

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import Conversation, Memory, Message, User


async def main() -> None:
    async with SessionLocal() as session:
        user = User(email="demo@memoryai.local", name="Demo User", password_hash=hash_password("demo-password-123"))
        session.add(user)
        await session.flush()
        conversation = Conversation(user_id=user.id, title="Preparing for SDE interviews")
        session.add(conversation)
        await session.flush()
        session.add_all([
            Message(conversation_id=conversation.id, role="user", content="I'm preparing for SDE interviews and learning DSA in Python."),
            Message(conversation_id=conversation.id, role="assistant", content="A focused Python DSA routine is a great start."),
            Memory(user_id=user.id, content="User is preparing for SDE interviews.", category="goal", importance=0.9, pinned=True, embedding=[0.0] * 384, embedding_model="seed"),
            Memory(user_id=user.id, content="User is learning DSA in Python.", category="skill", importance=0.85, embedding=[0.0] * 384, embedding_model="seed"),
        ])
        await session.commit()
    print("Seeded demo@memoryai.local / demo-password-123")


if __name__ == "__main__":
    asyncio.run(main())
