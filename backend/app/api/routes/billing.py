"""Платежи через ЮKassa.

Поток:
  1. POST /billing/checkout — создаём pending Subscription + платёж в ЮKassa,
     возвращаем confirmation_url (фронт делает window.location.assign).
  2. Клиент платит на стороне ЮKassa и возвращается на /billing/return.
  3. POST /billing/webhook/yookassa — ЮKassa дёргает наш URL, мы:
       (a) проверяем source IP по списку ЮKassa,
       (b) перезапрашиваем платёж по id (authoritative — подделка отсекается),
       (c) активируем подписку + поднимаем тариф + квоты.

Webhook идемпотентен: повторный payment.succeeded не задвоит активацию.
"""
from __future__ import annotations

import logging
import uuid as _uuid
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address, ip_network

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_org, get_current_user, require_org_roles
from app.api.routes.plans import PLAN_NAMES, PLAN_PRICES_RUB
from app.core.config import get_settings
from app.db.session import get_db
from app.models import Organization, PlanType, Subscription, User
from app.services.audit import log_action
from app.services.quota import apply_plan_limits
from app.services.yookassa import YooKassaClient, YooKassaError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/billing", tags=["billing"])
settings = get_settings()


# Опубликованные ЮKassa IP-диапазоны для вебхуков.
# Источник: https://yookassa.ru/developers/using-api/webhooks#ip
# Если ЮKassa добавит новые — поднимется 403, проверь актуальность.
_YOOKASSA_WEBHOOK_NETS = [
    ip_network("185.71.76.0/27"),
    ip_network("185.71.77.0/27"),
    ip_network("77.75.153.0/25"),
    ip_network("77.75.154.128/25"),
    ip_network("77.75.156.11/32"),
    ip_network("77.75.156.35/32"),
    ip_network("2a02:5180::/32"),
]


class CheckoutRequest(BaseModel):
    plan: PlanType
    # Согласие на сохранение способа оплаты + ежемесячные автосписания
    # (чекбокс в UI, включён по умолчанию; отключается в настройках).
    auto_renew: bool = True


class AutoRenewRequest(BaseModel):
    enabled: bool


def _get_client() -> YooKassaClient:
    if not settings.yookassa_shop_id or not settings.yookassa_secret_key:
        raise HTTPException(
            status_code=503,
            detail="Платежный провайдер ещё не настроен для продакшена",
        )
    return YooKassaClient(settings.yookassa_shop_id, settings.yookassa_secret_key)


def _build_receipt(*, user_email: str, plan_id: str, amount_rub: int) -> dict | None:
    if not settings.yookassa_receipts_enabled:
        return None
    if not user_email:
        # Чек без email клиента ОФД не примет → лучше не отправлять чек, чем
        # отправлять кривой. Это редкий путь (у нас email обязателен при
        # регистрации), но всё же.
        return None
    return {
        "customer": {"email": user_email},
        "tax_system_code": settings.yookassa_tax_system_code,
        "items": [
            {
                "description": (
                    f"Подписка БАЗА — тариф {PLAN_NAMES.get(plan_id, plan_id)} (1 мес.)"
                )[:128],
                "quantity": "1.00",
                "amount": {"value": f"{amount_rub:.2f}", "currency": "RUB"},
                "vat_code": settings.yookassa_vat_code,
                "payment_subject": "service",
                "payment_mode": "full_payment",
            }
        ],
    }


@router.post("/checkout")
def create_checkout(
    payload: CheckoutRequest,
    request: Request,
    organization: Organization = Depends(get_current_org),
    membership=Depends(require_org_roles("owner", "admin")),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.plan == organization.plan:
        raise HTTPException(status_code=400, detail="Этот тариф уже активен")
    if payload.plan == PlanType.free:
        raise HTTPException(status_code=400, detail="Free-тариф нельзя оплатить")
    amount = PLAN_PRICES_RUB.get(payload.plan.value)
    if not amount or amount <= 0:
        raise HTTPException(status_code=400, detail="Цена тарифа не настроена")

    client = _get_client()

    subscription = Subscription(
        organization_id=organization.id,
        plan_id=payload.plan.value,
        status="pending",
        current_period_start=datetime.now(timezone.utc),
        current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        auto_renew=payload.auto_renew,
    )
    db.add(subscription)
    db.flush()  # нужен subscription.id для idempotence + return_url

    base_url = settings.frontend_app_url.rstrip("/") or "https://usebaza.ru"
    return_url = f"{base_url}/billing/return?subscription_id={subscription.id}"

    metadata = {
        "organization_id": str(organization.id),
        "plan_id": payload.plan.value,
        "subscription_id": str(subscription.id),
        "user_id": str(user.id),
    }
    receipt = _build_receipt(
        user_email=user.email,
        plan_id=payload.plan.value,
        amount_rub=amount,
    )

    try:
        payment = client.create_payment(
            amount_rub=amount,
            description=(
                f"БАЗА · {PLAN_NAMES.get(payload.plan.value, payload.plan.value)} "
                f"· {organization.name}"
            ),
            return_url=return_url,
            metadata=metadata,
            receipt=receipt,
            idempotence_key=str(subscription.id),
            save_payment_method=payload.auto_renew,
        )
    except YooKassaError as e:
        db.rollback()
        logger.error("YooKassa checkout failed for org=%s plan=%s: %s",
                     organization.id, payload.plan.value, e)
        raise HTTPException(status_code=502, detail=f"Не удалось создать платёж: {e}")

    payment_id = payment.get("id")
    confirmation_url = (payment.get("confirmation") or {}).get("confirmation_url")
    if not payment_id or not confirmation_url:
        db.rollback()
        logger.error("YooKassa returned no id/confirmation_url: %s", payment)
        raise HTTPException(status_code=502, detail="ЮKassa не вернула confirmation_url")

    subscription.provider_subscription_id = payment_id

    log_action(
        db,
        user_id=str(membership.user_id),
        organization_id=str(organization.id),
        action="billing.checkout.created",
        meta={
            "plan": payload.plan.value,
            "subscription_id": str(subscription.id),
            "payment_id": payment_id,
            "amount_rub": amount,
        },
    )
    db.commit()
    return {
        "provider": "yookassa",
        "status": "pending",
        "checkout_url": confirmation_url,
        "payment_id": payment_id,
        "subscription_id": str(subscription.id),
        "message": "Перенаправляем в ЮKassa для оплаты",
    }


def _request_source_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def _is_yookassa_ip(ip: str) -> bool:
    if not ip:
        return False
    try:
        addr = ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in _YOOKASSA_WEBHOOK_NETS)


@router.post("/webhook/yookassa")
def yookassa_webhook(payload: dict, request: Request, db: Session = Depends(get_db)):
    # 1. Проверка source IP (первая линия). В деве можно выключить флагом.
    src_ip = _request_source_ip(request)
    if settings.yookassa_verify_ip and not _is_yookassa_ip(src_ip):
        logger.warning("YooKassa webhook from non-allowed IP: %s", src_ip)
        raise HTTPException(status_code=403, detail="Webhook source IP not allowed")

    event_type = payload.get("event") or ""
    obj = payload.get("object") or {}
    # For refund events the object IS a refund; the original payment id (which
    # carries our checkout metadata) is in object.payment_id. Re-fetch THAT
    # payment so org/subscription resolution + IP auth work exactly as for a
    # normal payment event.
    is_refund = event_type == "refund.succeeded"
    payment_id = obj.get("payment_id") if is_refund else obj.get("id")
    if not payment_id:
        raise HTTPException(status_code=400, detail="Webhook missing object.id")

    # 2. Authoritative re-fetch — подделать содержимое webhook нельзя,
    #    потому что мы перезапрашиваем платёж по id с нашими credentials.
    client = _get_client()
    try:
        payment = client.get_payment(payment_id)
    except YooKassaError as e:
        logger.error("YooKassa re-fetch failed for %s: %s", payment_id, e)
        raise HTTPException(status_code=502, detail=f"ЮKassa re-fetch: {e}")

    if payment.get("id") != payment_id:
        raise HTTPException(status_code=400, detail="Payment id mismatch")

    metadata = payment.get("metadata") or {}
    subscription_id = metadata.get("subscription_id")
    organization_id = metadata.get("organization_id")
    plan_id = metadata.get("plan_id")
    if not (subscription_id and organization_id and plan_id):
        raise HTTPException(status_code=400, detail="Webhook metadata incomplete")
    try:
        _uuid.UUID(subscription_id)
        _uuid.UUID(organization_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Webhook ids malformed")

    subscription = db.get(Subscription, subscription_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="Подписка не найдена")
    if str(subscription.organization_id) != organization_id:
        raise HTTPException(status_code=400, detail="org/subscription mismatch")

    org = db.get(Organization, organization_id)
    if not org:
        raise HTTPException(status_code=404, detail="Организация не найдена")

    # Кто «актор» для ActionLog (UUID, not null). У checkout-платежей в
    # metadata всегда лежит валидный user_id; для автопродлений (или битой
    # metadata) фолбэк — владелец организации. Иначе log_action упал бы на
    # invalid-uuid и вебхук вечно отдавал бы 500 (ЮKassa ретраит бесконечно).
    actor_id = metadata.get("user_id") or ""
    try:
        _uuid.UUID(actor_id)
    except (ValueError, TypeError):
        actor_id = ""
    if not actor_id:
        from app.models import Membership

        owner_m = db.execute(
            select(Membership).where(
                Membership.organization_id == org.id, Membership.role == "owner"
            )
        ).scalars().first()
        actor_id = str(owner_m.user_id) if owner_m else ""

    def _log(action: str, meta: dict) -> None:
        if actor_id:  # без валидного актора запись невозможна (UUID not null)
            log_action(db, user_id=actor_id, organization_id=organization_id,
                       action=action, meta=meta)

    payment_status = payment.get("status")  # pending / waiting_for_capture / succeeded / canceled

    # Возврат средств → немедленно откатываем доступ на free (не ждём конца
    # оплаченного периода). Без этого вернувший деньги клиент сохранял бы Pro.
    if is_refund:
        from app.services.quota import reconcile_org_plan

        subscription.status = "refunded"
        # Reconcile to the plan the org STILL actively pays for (free if none).
        # Another active subscription (e.g. after a mid-cycle upgrade) may still
        # cover the org, so we must NOT blindly downgrade to free. Exclude the
        # just-refunded row (its status change isn't flushed yet under autoflush=off).
        new_plan = reconcile_org_plan(db, org, exclude_sub_id=subscription.id)
        _log(
            "billing.refund.succeeded",
            {"payment_id": payment_id, "subscription_id": subscription_id, "plan_after": new_plan.value},
        )
        db.commit()
        logger.info("Refund processed: org=%s plan now %s (payment=%s)",
                    organization_id, new_plan.value, payment_id)
        return {"status": "ok", "refunded": True}

    # Идемпотентность: если уже активировали этим же платежом — выходим.
    if (
        event_type == "payment.succeeded"
        and payment_status == "succeeded"
        and subscription.status == "active"
        and subscription.provider_subscription_id == payment_id
    ):
        return {"status": "ok", "duplicate": True}

    if event_type == "payment.succeeded" and payment_status == "succeeded":
        try:
            plan_enum = PlanType(plan_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown plan: {plan_id}")

        now = datetime.now(timezone.utc)
        subscription.status = "active"
        subscription.provider_subscription_id = payment_id
        subscription.current_period_start = now
        subscription.current_period_end = now + timedelta(days=30)

        # Автопродление: если клиент дал согласие (save_payment_method при
        # checkout) — ЮKassa вернула сохранённый способ оплаты. Запоминаем его
        # id: именно им ночная задача renew_subscriptions делает списания.
        pm = payment.get("payment_method") or {}
        if pm.get("saved") and pm.get("id"):
            subscription.payment_method_id = pm["id"]

        org.plan = plan_enum
        apply_plan_limits(org)

        _log(
            "billing.payment.succeeded",
            {
                "payment_id": payment_id,
                "plan": plan_id,
                "amount": payment.get("amount", {}).get("value"),
                "currency": payment.get("amount", {}).get("currency"),
                "subscription_id": subscription_id,
            },
        )
        db.commit()
        logger.info("Subscription activated: org=%s plan=%s payment=%s",
                    organization_id, plan_id, payment_id)
        return {"status": "ok"}

    if event_type == "payment.canceled" and payment_status == "canceled":
        subscription.status = "canceled"
        _log(
            "billing.payment.canceled",
            {
                "payment_id": payment_id,
                "reason": (payment.get("cancellation_details") or {}).get("reason"),
                "subscription_id": subscription_id,
            },
        )
        db.commit()
        return {"status": "ok"}

    # pending / waiting_for_capture — пока не обрабатываем, ЮKassa повторит.
    logger.info("YooKassa webhook ignored: event=%s status=%s payment=%s",
                event_type, payment_status, payment_id)
    return {"status": "ignored", "event": event_type, "payment_status": payment_status}


@router.get("/subscription")
def get_current_subscription(
    organization: Organization = Depends(get_current_org),
    _membership=Depends(require_org_roles("owner", "admin", "member")),
    db: Session = Depends(get_db),
):
    # An org legitimately accumulates multiple Subscription rows over time
    # (each checkout creates one: pending → active/canceled). Take the most
    # recent. scalar_one_or_none() was wrong — it raises MultipleResultsFound
    # the moment a second subscription exists.
    subscription = db.execute(
        select(Subscription)
        .where(Subscription.organization_id == organization.id)
        .order_by(Subscription.created_at.desc())
        .limit(1)
    ).scalars().first()
    if not subscription:
        return {"status": "none"}
    return {
        "id": str(subscription.id),
        "plan_id": subscription.plan_id,
        "status": subscription.status,
        "current_period_start": subscription.current_period_start,
        "current_period_end": subscription.current_period_end,
        "provider": "yookassa",
        "payment_id": subscription.provider_subscription_id or None,
        "auto_renew": bool(subscription.auto_renew),
        # Карта реально сохранена → автосписание технически возможно.
        "payment_method_saved": bool(subscription.payment_method_id),
    }


@router.post("/auto-renew")
def set_auto_renew(
    payload: AutoRenewRequest,
    organization: Organization = Depends(get_current_org),
    membership=Depends(require_org_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    """Включить/выключить автопродление на последней активной подписке.

    Выключение — обязательная возможность для рекуррентов в РФ: клиент в
    любой момент отказывается от будущих списаний (текущий оплаченный период
    не трогаем). Включение обратно возможно только пока сохранён способ
    оплаты (иначе — просто нечем списывать: нужен новый checkout с галочкой).
    """
    subscription = db.execute(
        select(Subscription)
        .where(
            Subscription.organization_id == organization.id,
            Subscription.status == "active",
        )
        .order_by(Subscription.created_at.desc())
        .limit(1)
    ).scalars().first()
    if not subscription:
        raise HTTPException(status_code=404, detail="Активная подписка не найдена")
    if payload.enabled and not subscription.payment_method_id:
        raise HTTPException(
            status_code=400,
            detail="Способ оплаты не сохранён — оплатите тариф с галочкой «Автопродление»",
        )
    subscription.auto_renew = payload.enabled
    if payload.enabled:
        # Свежая попытка с чистого листа (сбрасываем счётчик неудач).
        subscription.renew_attempts = 0
    log_action(
        db,
        user_id=str(membership.user_id),
        organization_id=str(organization.id),
        action="billing.auto_renew." + ("enabled" if payload.enabled else "disabled"),
        meta={"subscription_id": str(subscription.id)},
    )
    db.commit()
    return {"status": "ok", "auto_renew": subscription.auto_renew}
