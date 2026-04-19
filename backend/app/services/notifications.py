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


def send_alert(severity: str, title: str, body: str = "", *, key: str | None = None,
               throttle_seconds: int = 600) -> None:
    """Send a throttled production alert to Telegram + log it.

    severity: 'critical' | 'error' | 'warning' | 'info'
    key: dedup key — same alert won't fire twice within `throttle_seconds`.
         If omitted, derived from title.
    Throttling uses Redis (DB 4 — separate from cache/celery). If Redis is
    unavailable, the alert still fires (fail-open).
    """
    severity_emoji = {
        "critical": "🔥",
        "error": "❌",
        "warning": "⚠️",
        "info": "ℹ️",
    }.get(severity.lower(), "📌")

    dedup_key = key or title

    # Throttle via Redis SETNX
    try:
        import redis as _redis
        settings = get_settings()
        base = settings.redis_url.rsplit("/", 1)[0] if "/" in settings.redis_url else settings.redis_url
        r = _redis.Redis.from_url(f"{base}/4", decode_responses=True, socket_timeout=2)
        # SET with NX (only set if not exists) + EX (TTL)
        if not r.set(f"alert:{dedup_key}", "1", nx=True, ex=throttle_seconds):
            logger.debug("Alert throttled: key=%r", dedup_key)
            return
    except Exception:
        # Redis down — proceed without throttle (better than silent)
        pass

    text = f"{severity_emoji} [{severity.upper()}] {title}"
    if body:
        text += f"\n\n{body[:3500]}"

    logger.warning("ALERT [%s] %s | %s", severity, title, body[:200])
    send_telegram(text)
