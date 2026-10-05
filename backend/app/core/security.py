import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.config import settings

_hasher = PasswordHasher()  # Argon2id with library defaults
_DUMMY_HASH = _hasher.hash("dummy-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def burn_password_time() -> None:
    """Spend the same time as a real check so unknown emails can't be detected by timing."""
    verify_password("x", _DUMMY_HASH)


def create_access_token(user_id: uuid.UUID) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": str(user_id), "type": "access", "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_minutes),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> uuid.UUID | None:
    """Return the user id, or None for any invalid/expired/wrong-type token."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], options={"require": ["exp", "sub"]})
        if payload.get("type") != "access":
            return None
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError):
        return None


def hash_token(raw: str) -> str:
    # SHA-256 is fine here: refresh tokens are 384 random bits, so there is nothing to brute-force.
    return hashlib.sha256(raw.encode()).hexdigest()


def new_opaque_token() -> tuple[str, str]:
    """(raw, sha256 hash) for single-purpose secrets: refresh tokens, password-reset links."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_token(raw)


new_refresh_token = new_opaque_token
