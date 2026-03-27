import logging
import smtplib
import time
from email.message import EmailMessage

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

EMAIL_MAX_RETRIES = 3
EMAIL_RETRY_DELAY = 2  # seconds


def email_delivery_configured() -> bool:
    settings = get_settings()
    return bool(settings.smtp_host and settings.smtp_user and settings.smtp_password)


def send_email(subject: str, body: str, recipient: str) -> bool:
    settings = get_settings()
    if not email_delivery_configured():
        return False
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_user
    message["To"] = recipient
    message.set_content(body)

    last_exc: Exception | None = None
    for attempt in range(1, EMAIL_MAX_RETRIES + 1):
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
                smtp.starttls()
                smtp.login(settings.smtp_user, settings.smtp_password)
                smtp.send_message(message)
            return True
        except Exception as exc:
            last_exc = exc
            logger.error(
                "Email send failed (attempt %d/%d) to=%s subject=%s: %s",
                attempt,
                EMAIL_MAX_RETRIES,
                recipient,
                subject,
                exc,
            )
            if attempt < EMAIL_MAX_RETRIES:
                time.sleep(EMAIL_RETRY_DELAY)

    logger.critical(
        "All %d email send attempts exhausted to=%s subject=%s: %s",
        EMAIL_MAX_RETRIES,
        recipient,
        subject,
        last_exc,
    )
    return False


def send_telegram(message: str) -> None:
    settings = get_settings()
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        httpx.post(url, json={"chat_id": settings.telegram_chat_id, "text": message}, timeout=8.0)
    except Exception as exc:
        logger.error("Telegram send failed: %s", exc)
