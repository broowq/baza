from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_org, require_org_roles
from app.core.config import get_settings
from app.db.session import get_db
from app.models import Organization, PlanType, Subscription
from app.services.audit import log_action

router = APIRouter(prefix="/billing", tags=["billing"])
settings = get_settings()


class CheckoutRequest(BaseModel):
    plan: PlanType


@router.post("/checkout")
def create_checkout(
    payload: CheckoutRequest,
    organization: Organization = Depends(get_current_org),
    membership=Depends(require_org_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    if payload.plan == organization.plan:
        raise HTTPException(status_code=400, detail="Этот тариф уже активен")
    if settings.app_env != "development":
        raise HTTPException(status_code=503, detail="Платежный провайдер ещё не настроен для продакшена")
    subscription = Subscription(
        organization_id=organization.id,
        plan_id=payload.plan.value,
        status="pending",
        current_period_start=datetime.now(timezone.utc),
        current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        provider_subscription_id=f"stub_{organization.id}_{payload.plan.value}",
    )
    db.add(subscription)
    db.flush()
    log_action(
        db,
        user_id=str(membership.user_id),
        organization_id=str(organization.id),
        action="billing.checkout.created",
        meta={"plan": payload.plan.value, "subscription_id": str(subscription.id)},
    )
    db.commit()
    return {
        "provider": "stripe_stub",
        "status": "pending",
        "checkout_url": f"https://example-payments.local/checkout?org={organization.id}&plan={payload.plan.value}",
        "message": "Тестовый checkout создан. Для продакшена подключите Stripe API.",
    }


@router.post("/webhook/stripe")
def stripe_webhook_stub(payload: dict, request: Request = None, db: Session = Depends(get_db)):
    if settings.stripe_webhook_secret:
        sig = (request.headers.get("stripe-signature", "") if request else "")
        if not sig:
            raise HTTPException(status_code=401, detail="Отсутствует stripe-signature")
    subscription_id = payload.get("subscription_id")
    status = payload.get("status")
    if not subscription_id or not status:
        raise HTTPException(status_code=400, detail="subscription_id и status обязательны")
    try:
        from uuid import UUID
        UUID(subscription_id)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Некорректный subscription_id")
    subscription = db.get(Subscription, subscription_id)
    if not subscription:
        raise HTTPException(status_code=404, detail="Подписка не найдена")
    subscription.status = str(status)
    db.commit()
    return {"status": "ok", "message": "Webhook обработан"}


@router.get("/subscription")
def get_current_subscription(
    organization: Organization = Depends(get_current_org),
    _membership=Depends(require_org_roles("owner", "admin", "member")),
    db: Session = Depends(get_db),
):
    subscription = db.execute(
        select(Subscription)
        .where(Subscription.organization_id == organization.id)
        .order_by(Subscription.created_at.desc())
    ).scalar_one_or_none()
    if not subscription:
        return {"status": "none"}
    return {
        "id": str(subscription.id),
        "plan_id": subscription.plan_id,
        "status": subscription.status,
        "current_period_start": subscription.current_period_start,
        "current_period_end": subscription.current_period_end,
    }
