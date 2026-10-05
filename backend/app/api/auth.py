import logging

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_session
from app.mailer.senders import EmailSender, get_email_sender
from app.services.auth import AuthService, EmailAlreadyExists, InvalidCredentials

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])
COOKIE = "refresh_token"


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


def _set_refresh_cookie(response: Response, raw: str) -> None:
    # httpOnly: JS can't read it (XSS). path: only sent to /api/auth. SameSite=Lax: no cross-site POSTs.
    response.set_cookie(COOKIE, raw, httponly=True, secure=settings.cookie_secure, samesite="lax",
                        max_age=settings.refresh_token_days * 86400, path="/api/auth")


@router.post("/register", status_code=201, response_model=TokenOut)
async def register(body: RegisterIn, response: Response, session: AsyncSession = Depends(get_session)) -> TokenOut:
    svc = AuthService(session)
    try:
        user = await svc.register(body.email, body.password)
    except EmailAlreadyExists:
        raise HTTPException(409, "Email already registered") from None
    access, refresh = await svc.issue(user.id)
    _set_refresh_cookie(response, refresh)
    return TokenOut(access_token=access)


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, response: Response, session: AsyncSession = Depends(get_session)) -> TokenOut:
    svc = AuthService(session)
    try:
        user = await svc.login(body.email, body.password)
    except InvalidCredentials:
        raise HTTPException(401, "Incorrect email or password") from None  # same message for both cases
    access, refresh = await svc.issue(user.id)
    _set_refresh_cookie(response, refresh)
    return TokenOut(access_token=access)


@router.post("/refresh", response_model=TokenOut)
async def refresh(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    session: AsyncSession = Depends(get_session),
) -> TokenOut:
    pair = await AuthService(session).rotate(refresh_token) if refresh_token else None
    if pair is None:
        raise HTTPException(401, "Session expired. Log in again.")
    _set_refresh_cookie(response, pair[1])
    return TokenOut(access_token=pair[0])


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    session: AsyncSession = Depends(get_session),
) -> None:
    if refresh_token:
        await AuthService(session).logout(refresh_token)
    response.delete_cookie(COOKIE, path="/api/auth")


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=8, max_length=128)


async def _send_reset_email(sender: EmailSender, to: str, raw_token: str) -> None:
    link = f"{settings.frontend_url.rstrip('/')}/reset-password?token={raw_token}"
    body = (f"Someone asked to reset the password for your MemoryAI account.\n\n"
            f"Open this link within {settings.reset_token_minutes} minutes to choose a new one:\n{link}\n\n"
            "If this wasn't you, ignore this email: your password stays the same.")
    try:
        await sender.send(to, "Reset your MemoryAI password", body)
    except Exception:  # never surfaced to the caller (that would reveal which emails exist)
        log.exception("could not send password reset email")


@router.post("/forgot-password", status_code=202)
async def forgot_password(body: ForgotIn, background: BackgroundTasks, session: AsyncSession = Depends(get_session),
                          sender: EmailSender = Depends(get_email_sender)) -> dict[str, str]:
    result = await AuthService(session).request_reset(body.email)
    if result:
        background.add_task(_send_reset_email, sender, result[0].email, result[1])  # after the response: same speed either way
    return {"message": "If that email is registered, a reset link is on its way."}


@router.post("/reset-password", status_code=204)
async def reset_password(body: ResetIn, response: Response, session: AsyncSession = Depends(get_session)) -> None:
    if not await AuthService(session).reset_password(body.token, body.password):
        raise HTTPException(400, "This reset link is invalid or has expired.")
    response.delete_cookie(COOKIE, path="/api/auth")
