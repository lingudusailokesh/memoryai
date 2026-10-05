import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core import security
from app.models import User
from app.repositories.password_resets import PasswordResetRepository
from app.repositories.refresh_tokens import RefreshTokenRepository
from app.repositories.users import EmailAlreadyExists, UserRepository

__all__ = ["AuthService", "InvalidCredentials", "EmailAlreadyExists"]


class InvalidCredentials(Exception):
    pass


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.users = UserRepository(session)
        self.tokens = RefreshTokenRepository(session)
        self.resets = PasswordResetRepository(session)

    async def register(self, email: str, password: str) -> User:
        return await self.users.create(email, security.hash_password(password))

    async def login(self, email: str, password: str) -> User:
        user = await self.users.get_by_email(email)
        if user is None:
            security.burn_password_time()
            raise InvalidCredentials
        if not security.verify_password(password, user.password_hash):
            raise InvalidCredentials
        return user

    async def issue(self, user_id: uuid.UUID) -> tuple[str, str]:
        """Return (access_token, raw_refresh_token)."""
        raw, hashed = security.new_refresh_token()
        expires = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_days)
        await self.tokens.add(user_id, hashed, expires)
        return security.create_access_token(user_id), raw

    async def rotate(self, raw_refresh: str) -> tuple[str, str] | None:
        """Use a refresh token once; hand back a fresh pair."""
        user_id = await self.tokens.consume(security.hash_token(raw_refresh))
        return None if user_id is None else await self.issue(user_id)

    async def logout(self, raw_refresh: str) -> None:
        await self.tokens.consume(security.hash_token(raw_refresh))

    async def request_reset(self, email: str) -> tuple[User, str] | None:
        """Create a reset token. None when the email is unknown or a link was requested a moment ago.

        Callers must answer identically either way, so nobody can probe which emails have accounts.
        """
        user = await self.users.get_by_email(email)
        now = datetime.now(timezone.utc)
        if user is None or await self.resets.requested_since(user.id, now - timedelta(seconds=settings.reset_cooldown_seconds)):
            return None
        raw, hashed = security.new_opaque_token()
        await self.resets.create(user.id, hashed, now + timedelta(minutes=settings.reset_token_minutes))
        return user, raw

    async def reset_password(self, raw_token: str, new_password: str) -> bool:
        new_hash = security.hash_password(new_password)
        user_id = await self.resets.consume(security.hash_token(raw_token))  # single use
        if user_id is None:
            return False
        await self.users.set_password(user_id, new_hash)
        await self.tokens.revoke_all(user_id)  # everyone signed in with the old password is signed out
        return True
