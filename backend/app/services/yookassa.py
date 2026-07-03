"""Тонкий клиент ЮKassa API v3.

Создание платежа, перепроверка статуса и рекуррентные списания по
сохранённому способу оплаты (автопродление подписки):

  * create_payment(save_payment_method=True) — первый платёж с согласием;
    в succeeded-платеже ЮKassa вернёт payment_method.{id, saved: true}.
  * create_recurring_payment(payment_method_id=...) — merchant-initiated
    списание без участия клиента (без confirmation).

Аутентификация — Basic shop_id:secret_key. Каждый POST требует
заголовок Idempotence-Key — без него повторный запрос пройдёт как
новый платёж. У нас ключом идёт subscription.id, так что двойной
клик на кнопку «Перейти на Pro» (или повтор ретрая автосписания)
приведёт к одному платежу.
"""
from __future__ import annotations

import base64
import logging
import uuid
from typing import Any

import httpx

logger = logging.getLogger(__name__)

API_BASE = "https://api.yookassa.ru/v3"


class YooKassaError(Exception):
    """API вернула не-2xx или сеть упала."""


class YooKassaClient:
    def __init__(self, shop_id: str, secret_key: str, *, timeout: float = 30.0):
        if not shop_id or not secret_key:
            raise YooKassaError("YooKassa: shop_id или secret_key пустые")
        token = base64.b64encode(f"{shop_id}:{secret_key}".encode()).decode()
        self._auth_header = f"Basic {token}"
        self._timeout = timeout

    def _headers(self, *, idempotence_key: str | None = None) -> dict[str, str]:
        h = {
            "Authorization": self._auth_header,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if idempotence_key:
            h["Idempotence-Key"] = idempotence_key
        return h

    def _post_payment(self, body: dict[str, Any], idem: str, *, op: str) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=self._timeout) as c:
                r = c.post(f"{API_BASE}/payments", headers=self._headers(idempotence_key=idem), json=body)
        except httpx.HTTPError as e:
            logger.exception("YooKassa %s network error", op)
            raise YooKassaError(f"Сеть: {e}") from e
        if r.status_code >= 400:
            logger.error("YooKassa %s %s: %s", op, r.status_code, r.text[:500])
            raise YooKassaError(f"HTTP {r.status_code}: {r.text[:300]}")
        return r.json()

    def create_payment(
        self,
        *,
        amount_rub: int,
        description: str,
        return_url: str,
        metadata: dict[str, str],
        receipt: dict[str, Any] | None = None,
        idempotence_key: str | None = None,
        save_payment_method: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "amount": {"value": f"{amount_rub:.2f}", "currency": "RUB"},
            "confirmation": {"type": "redirect", "return_url": return_url},
            "capture": True,
            "description": description[:128],
            "metadata": metadata,
        }
        if save_payment_method:
            # Просим ЮKassa сохранить способ оплаты для будущих автосписаний.
            # В succeeded-платеже вернётся payment_method.{id, saved: true}.
            body["save_payment_method"] = True
        if receipt:
            body["receipt"] = receipt
        return self._post_payment(body, idempotence_key or str(uuid.uuid4()), op="create_payment")

    def create_recurring_payment(
        self,
        *,
        amount_rub: int,
        description: str,
        payment_method_id: str,
        metadata: dict[str, str],
        receipt: dict[str, Any] | None = None,
        idempotence_key: str | None = None,
    ) -> dict[str, Any]:
        """Merchant-initiated списание по сохранённому способу оплаты.

        Без блока confirmation — клиент не участвует. Ответ обычно сразу
        succeeded / canceled (карта отклонена); pending тоже возможен —
        тогда финал придёт вебхуком payment.succeeded/canceled.
        """
        if not payment_method_id:
            raise YooKassaError("payment_method_id пуст — автосписание невозможно")
        body: dict[str, Any] = {
            "amount": {"value": f"{amount_rub:.2f}", "currency": "RUB"},
            "capture": True,
            "payment_method_id": payment_method_id,
            "description": description[:128],
            "metadata": metadata,
        }
        if receipt:
            body["receipt"] = receipt
        return self._post_payment(body, idempotence_key or str(uuid.uuid4()), op="create_recurring_payment")

    def get_payment(self, payment_id: str) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=self._timeout) as c:
                r = c.get(f"{API_BASE}/payments/{payment_id}", headers=self._headers())
        except httpx.HTTPError as e:
            logger.exception("YooKassa get_payment network error")
            raise YooKassaError(f"Сеть: {e}") from e
        if r.status_code >= 400:
            logger.error("YooKassa get_payment %s: %s", r.status_code, r.text[:500])
            raise YooKassaError(f"HTTP {r.status_code}: {r.text[:300]}")
        return r.json()
