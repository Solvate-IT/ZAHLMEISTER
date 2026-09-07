import asyncio
import smtplib
from email.message import EmailMessage

from app.core.config import settings


def _send(subject: str, recipient: str, body: str) -> None:
    if settings.mail_delivery_mode == "console":
        print(f"[account-mail] to={recipient} subject={subject}\n{body}")
        return
    if settings.mail_delivery_mode != "smtp":
        raise RuntimeError(f"Unsupported MAIL_DELIVERY_MODE: {settings.mail_delivery_mode}")
    if not settings.smtp_host or not settings.mail_from_address:
        raise RuntimeError("Platform SMTP is not configured")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = (
        f"{settings.mail_from_name} <{settings.mail_from_address}>"
        if settings.mail_from_name
        else settings.mail_from_address
    )
    message["To"] = recipient
    message.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as client:
        if settings.smtp_starttls:
            client.starttls()
        if settings.smtp_username:
            client.login(settings.smtp_username, settings.smtp_password)
        client.send_message(message)


async def send_platform_mail(*, subject: str, recipient: str, body: str) -> None:
    await asyncio.to_thread(_send, subject, recipient, body)
