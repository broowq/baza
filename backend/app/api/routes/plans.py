from fastapi import APIRouter

from app.core.config import get_settings
from app.models import PlanType
from app.services.quota import PLAN_LIMITS

router = APIRouter(prefix="/plans", tags=["plans"])
settings = get_settings()

# Prices in rubles per month
PLAN_PRICES_RUB = {
    "free": 0,
    "starter": 2490,
    "pro": 8900,
    "team": 24900,
}

PLAN_NAMES = {
    "free": "Free",
    "starter": "Starter",
    "pro": "Pro",
    "team": "Business",
}


@router.get("")
def list_plans():
    return [
        {
            "id": plan.value,
            "name": PLAN_NAMES.get(plan.value, plan.value.title()),
            "projects_limit": PLAN_LIMITS[plan]["projects"],
            "users_limit": PLAN_LIMITS[plan]["users"],
            "leads_limit_per_month": PLAN_LIMITS[plan]["leads_per_month"],
            "searches_per_month": PLAN_LIMITS[plan]["searches"],
            "can_invite_members": PLAN_LIMITS[plan]["can_invite"],
            "price_monthly_rub": PLAN_PRICES_RUB.get(plan.value, 0),
            "payment_provider": "stripe_stub" if settings.app_env == "development" else "unconfigured",
        }
        for plan in [PlanType.free, PlanType.starter, PlanType.pro, PlanType.team]
    ]
