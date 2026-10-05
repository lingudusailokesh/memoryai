import uuid
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import RefreshToken


class RefreshTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, user_id: uuid.UUID, token_hash: str, expires_at: datetime) -> None:
        self.session.add(RefreshToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at))
        await self.session.commit()

    async def consume(self, token_hash: str) -> uuid.UUID | None:
        """Atomically revoke a valid token and return its user id (None if unknown, used or expired).

        One UPDATE ... RETURNING means two concurrent requests can't both use the same token.
        """
        now = datetime.now(timezone.utc)
        res = await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.token_hash == token_hash, RefreshToken.revoked_at.is_(None),
                   RefreshToken.expires_at > now)
            .values(revoked_at=now)
            .returning(RefreshToken.user_id)
            .execution_options(synchronize_session=False)
        )
        user_id = res.scalar_one_or_none()
        await self.session.commit()
        return user_id

    async def revoke_all(self, user_id: uuid.UUID) -> None:
        """Log the user out everywhere (used after a password reset)."""
        await self.session.execute(
            update(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc)).execution_options(synchronize_session=False))
        await self.session.commit()
