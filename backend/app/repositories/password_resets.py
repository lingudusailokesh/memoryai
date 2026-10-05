import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PasswordResetToken


class PasswordResetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, user_id: uuid.UUID, token_hash: str, expires_at: datetime) -> None:
        """Store a new token and void the user's earlier unused ones: only the newest link works."""
        await self.session.execute(
            update(PasswordResetToken).where(PasswordResetToken.user_id == user_id, PasswordResetToken.used_at.is_(None))
            .values(used_at=datetime.now(timezone.utc)).execution_options(synchronize_session=False))
        self.session.add(PasswordResetToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at))
        await self.session.commit()

    async def requested_since(self, user_id: uuid.UUID, since: datetime) -> bool:
        res = await self.session.execute(
            select(PasswordResetToken.id).where(PasswordResetToken.user_id == user_id,
                                                PasswordResetToken.created_at > since).limit(1))
        return res.first() is not None

    async def consume(self, token_hash: str) -> uuid.UUID | None:
        """Atomically mark a valid token used and return its user (None if unknown, used or expired)."""
        now = datetime.now(timezone.utc)
        res = await self.session.execute(
            update(PasswordResetToken)
            .where(PasswordResetToken.token_hash == token_hash, PasswordResetToken.used_at.is_(None),
                   PasswordResetToken.expires_at > now)
            .values(used_at=now).returning(PasswordResetToken.user_id).execution_options(synchronize_session=False))
        user_id = res.scalar_one_or_none()
        await self.session.commit()
        return user_id
