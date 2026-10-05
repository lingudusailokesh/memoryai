import asyncio
import logging
import smtplib
from abc import ABC, abstractmethod
from email.message import EmailMessage

from app.config import settings

log = logging.getLogger(__name__)


class EmailSender(ABC):
    @abstractmethod
    async def send(self, to: str, subject: str, body: str) -> None: ...


class ConsoleEmailSender(EmailSender):
    """Development only: prints the email (including any reset link) to the backend log instead of sending it."""

    async def send(self, to: str, subject: str, body: str) -> None:
        log.warning("DEV EMAIL (not sent) to=%s subject=%r\n%s", to, subject, body)


class SmtpEmailSender(EmailSender):
    """Any SMTP provider with STARTTLS on port 587 (Gmail app password, Brevo, Mailtrap, ...)."""

    def __init__(self, host: str, port: int, username: str, password: str, sender: str) -> None:
        self.host, self.port, self.username, self.password, self.sender = host, port, username, password, sender

    def _send_sync(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.sender, to, subject
        msg.set_content(body)
        with smtplib.SMTP(self.host, self.port, timeout=15) as smtp:
            smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(msg)

    async def send(self, to: str, subject: str, body: str) -> None:
        await asyncio.to_thread(self._send_sync, to, subject, body)  # smtplib is blocking


def get_email_sender() -> EmailSender:
    if settings.email_backend == "smtp":
        if not settings.smtp_host:
            raise RuntimeError("EMAIL_BACKEND=smtp needs SMTP_HOST (and usually SMTP_USERNAME / SMTP_PASSWORD)")
        return SmtpEmailSender(settings.smtp_host, settings.smtp_port, settings.smtp_username,
                               settings.smtp_password, settings.email_from)
    return ConsoleEmailSender()
