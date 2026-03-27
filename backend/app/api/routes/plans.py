from fastapi import APIRouter

from app.core.config import get_settings
from app.models import PlanType
from app.services.quota import PLAN_LIMITS

router = APIRouter(prefix="/plans", tags=["plans"])
settings = get_settings()


@router.get("")
def list_plans():
    return [
        {
            "id": plan.value,
            "name": plan.value.title(),
            "projects_limit": PLAN_LIMITS[plan]["projects"],
            "users_limit": PLAN_LIMITS[plan]["users"],
            "leads_limit_per_month": PLAN_LIMITS[plan]["leads_per_month"],
            "can_invite_members": PLAN_LIMITS[plan]["can_invite"],
            "price_monthly_usd": {"starter": 29, "pro": 99, "team": 299}[plan.value],
            "payment_provider": "stripe_stub" if settings.app_env == "development" else "unconfigured",
        }
        for plan in [PlanType.starter, PlanType.pro, PlanType.team]
    ]
