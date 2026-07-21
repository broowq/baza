"""Outbound CRM webhook tasks.

Pushes newly-enriched leads to the organization's configured webhook URL
(Bitrix24 / AmoCRM / custom). Retries on network errors; drops after 3.
"""
import logging

import httpx

from app.tasks.celery_app import celery
from app.utils.url_tools import _is_safe_url

logger = logging.getLogger(__name__)


@celery.task(
    name="webhook.push_lead",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def push_lead_webhook(self, webhook_url: str, payload: dict) -> bool:
    """POST one lead to the CRM webhook URL. Retries on 5xx / network errors.

    payload fields: id, company, city, email, phone, address, website,
                    score, status, tags, project_id, project_name
    """
    if not webhook_url:
        return False
    # SSRF-гард (аудит, HIGH): webhook_url задаёт админ орги, а мы POST'им туда
    # ПД лидов. Проверяем, что хост резолвится в ПУБЛИЧНЫЙ адрес (не
    # localhost/приватная сеть/облачная метадата 169.254.169.254), И отключаем
    # follow_redirects — иначе публичный URL мог бы 30x-редиректом увести запрос
    # с ПД на внутренний сервис. Set-time валидация есть в organizations.update_webhook,
    # но здесь второй барьер против DNS-rebinding (хост мог сменить IP после установки).
    if not _is_safe_url(webhook_url):
        logger.warning("Webhook blocked (unsafe/internal target): %s", webhook_url[:100])
        return False
    try:
        with httpx.Client(timeout=10.0, follow_redirects=False) as client:
            resp = client.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json", "User-Agent": "BAZA-Webhook/1.0"},
            )
        # 30x на вебхуке — подозрительно (возможная попытка увести на внутренний
        # хост). Не следуем, считаем неретраебельной ошибкой доставки.
        if 300 <= resp.status_code < 400:
            logger.warning("Webhook returned redirect %d (not followed): %s",
                           resp.status_code, webhook_url[:100])
            return False
        if resp.status_code >= 500:
            raise self.retry(exc=RuntimeError(f"webhook 5xx: {resp.status_code}"))
        if resp.status_code >= 400:
            logger.warning(
                "Webhook non-retryable %d for %s: %s",
                resp.status_code, webhook_url, resp.text[:200],
            )
            return False
        return True
    except self.MaxRetriesExceededError:
        logger.error("Webhook max retries exhausted: url=%s", webhook_url)
        return False
    except httpx.RequestError as exc:
        logger.warning("Webhook network error, retrying: %s", exc)
        raise self.retry(exc=exc)
    except Exception as exc:
        logger.error("Webhook task crashed: %s", exc)
        return False
