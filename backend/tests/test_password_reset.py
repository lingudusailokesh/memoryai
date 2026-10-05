import re
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select, update

from app.mailer.senders import ConsoleEmailSender, SmtpEmailSender
from app.models import PasswordResetToken
from tests.test_auth import PW, register

NEW = "brand-new-pass-9"


def token_in(mailer, index=-1) -> str:
    return re.search(r"token=([\w-]+)", mailer.sent[index][2]).group(1)


async def forgot(client, email="a@x.com"):
    return await client.post("/api/auth/forgot-password", json={"email": email})


async def reset(client, token, password=NEW):
    return await client.post("/api/auth/reset-password", json={"token": token, "password": password})


async def login(client, pw, email="a@x.com"):
    return await client.post("/api/auth/login", json={"email": email, "password": pw})


async def test_forgot_password_sends_one_email_with_a_link(client, mailer):
    await register(client)
    r = await forgot(client)
    assert r.status_code == 202
    to, subject, body = mailer.sent[0]
    assert to == "a@x.com" and "reset" in subject.lower()
    assert "http://localhost:5173/reset-password?token=" in body and "30 minutes" in body


async def test_unknown_email_gets_the_same_answer_and_no_email(client, mailer):
    await register(client)
    known, unknown = await forgot(client, "a@x.com"), await forgot(client, "ghost@x.com")
    assert (known.status_code, known.json()) == (unknown.status_code, unknown.json())
    assert len(mailer.sent) == 1 and (await forgot(client, "not-an-email")).status_code == 422


async def test_cooldown_blocks_a_second_email_within_a_minute(client, mailer, session):
    await register(client)
    await forgot(client)
    assert (await forgot(client)).status_code == 202 and len(mailer.sent) == 1
    await session.execute(update(PasswordResetToken).values(created_at=datetime.now(timezone.utc) - timedelta(minutes=2)))
    await session.commit()
    await forgot(client)
    assert len(mailer.sent) == 2


async def test_reset_changes_the_password_and_the_link_works_once(client, mailer):
    await register(client)
    await forgot(client)
    token = token_in(mailer)
    assert (await reset(client, token)).status_code == 204
    assert (await login(client, PW)).status_code == 401
    assert (await login(client, NEW)).status_code == 200
    assert (await reset(client, token, "another-pass-77")).status_code == 400  # single use
    assert (await login(client, NEW)).status_code == 200


async def test_newest_link_replaces_older_ones(client, mailer, session):
    await register(client)
    await forgot(client)
    await session.execute(update(PasswordResetToken).values(created_at=datetime.now(timezone.utc) - timedelta(minutes=2)))
    await session.commit()
    await forgot(client)
    first, second = token_in(mailer, 0), token_in(mailer, 1)
    assert (await reset(client, first)).status_code == 400
    assert (await reset(client, second)).status_code == 204


async def test_expired_and_garbage_tokens_are_rejected(client, mailer, session):
    await register(client)
    await forgot(client)
    token = token_in(mailer)
    await session.execute(update(PasswordResetToken).values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)))
    await session.commit()
    assert (await reset(client, token)).status_code == 400
    assert (await reset(client, "x" * 40)).status_code == 400
    assert (await reset(client, "short")).status_code == 422
    assert (await login(client, PW)).status_code == 200  # password untouched


async def test_weak_password_is_rejected_and_keeps_the_token_usable(client, mailer):
    await register(client)
    await forgot(client)
    token = token_in(mailer)
    assert (await reset(client, token, "short")).status_code == 422
    assert (await reset(client, token)).status_code == 204


async def test_reset_signs_out_existing_sessions(client, mailer):
    await register(client)
    old_cookie = client.cookies.get("refresh_token")
    await forgot(client)
    await reset(client, token_in(mailer))
    client.cookies.clear()
    r = await client.post("/api/auth/refresh", headers={"Cookie": f"refresh_token={old_cookie}"})
    assert r.status_code == 401


async def test_only_a_hash_of_the_token_is_stored(client, mailer, session):
    await register(client)
    await forgot(client)
    row = (await session.execute(select(PasswordResetToken))).scalar_one()
    assert token_in(mailer) not in row.token_hash and len(row.token_hash) == 64


async def test_smtp_sender_uses_starttls_login_and_sends():
    with patch("app.mailer.senders.smtplib.SMTP") as smtp_cls:
        smtp = smtp_cls.return_value.__enter__.return_value
        await SmtpEmailSender("smtp.example.com", 587, "user", "pw", "MemoryAI <me@example.com>").send("a@x.com", "Hi", "Body")
    smtp_cls.assert_called_once_with("smtp.example.com", 587, timeout=15)
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("user", "pw")
    sent = smtp.send_message.call_args.args[0]
    assert sent["To"] == "a@x.com" and sent["Subject"] == "Hi" and sent["From"] == "MemoryAI <me@example.com>"


async def test_console_sender_logs_instead_of_sending(caplog):
    with caplog.at_level("WARNING"):
        await ConsoleEmailSender().send("a@x.com", "Hi", "link here")
    assert "DEV EMAIL" in caplog.text and "link here" in caplog.text


def test_smtp_backend_without_host_fails_fast(monkeypatch):
    from app.config import settings
    from app.mailer.senders import get_email_sender
    monkeypatch.setattr(settings, "email_backend", "smtp")
    monkeypatch.setattr(settings, "smtp_host", "")
    with pytest.raises(RuntimeError):
        get_email_sender()
