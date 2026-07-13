import logging

from app.services.notifications import send_alert, send_email
from app.tasks.celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(name="email.send_email", bind=True, max_retries=3, default_retry_delay=30)
def send_email_task(self, subject: str, body: str, recipient: str) -> bool:
    """Async Celery wrapper around the synchronous send_email helper."""
    try:
        result = send_email(subject, body, recipient)
        if not result:
            logger.warning(
                "send_email returned False for recipient=%s subject=%s, retrying",
                recipient,
                subject,
            )
            raise self.retry(exc=RuntimeError("send_email returned False"))
        return True
    except self.MaxRetriesExceededError:
        logger.error(
            "Max retries exceeded for email to=%s subject=%s",
            recipient,
            subject,
        )
        # С включённой верификацией недоставленное письмо = юзер заперт у
        # входа (403 до подтверждения), а RuSender-квота (100/мес на free)
        # кончается молча — алертим, а не только логируем.
        send_alert(
            "error",
            "Письмо не доставлено после ретраев",
            f"to={recipient} subject={subject}",
            key=f"email-fail:{recipient}",
        )
        return False
    except Exception as exc:
        logger.error(
            "send_email_task failed for recipient=%s subject=%s: %s",
            recipient,
            subject,
            exc,
        )
        raise self.retry(exc=exc)
