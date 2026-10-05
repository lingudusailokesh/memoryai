import uuid

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User


class EmailAlreadyExists(Exception):
    pass


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, email: str, password_hash: str) -> User:
        user = User(email=email.strip().lower(), password_hash=password_hash)
        self.session.add(user)
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise EmailAlreadyExists(email) from exc
        return user

    async def get(self, user_id: uuid.UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        res = await self.session.execute(select(User).where(User.email == email.strip().lower()))
        return res.scalar_one_or_none()

    async def set_password(self, user_id: uuid.UUID, password_hash: str) -> None:
        await self.session.execute(update(User).where(User.id == user_id).values(password_hash=password_hash))
        await self.session.commit()

    async def set_memory_mode(self, user_id: uuid.UUID, mode: str) -> None:
        await self.update_settings(user_id, memory_mode=mode)

    async def update_settings(self, user_id: uuid.UUID, **values: object) -> None:
        await self.session.execute(update(User).where(User.id == user_id).values(**values))
        await self.session.commit()
