from fastapi import APIRouter

from app.core.config import get_settings
from app.models import PlanType
from app.services.quota import PLAN_LIMITS

router = APIRouter(prefix="/plans", tags=["plans"])
settings = get_settings()

# Prices in rubles per month. Re-gridded 2026-07-09 from market research
# (docs/unit-economics.md §4): Starter 3 900→4 900 (still under the ~5 000 ₽
# impulse threshold, cheaper than Coldy Про 6 000); NEW «Team» (enum `growth`)
# 9 900 closes the ×4.3 Starter→Pro gap right on the RF self-serve corridor
# 5–10 тыс ₽ (Компас-месяц 9 700); Pro/Business prices kept, quotas raised.
PLAN_PRICES_RUB = {
    "starter": 4900,
    "growth": 9900,
    "pro": 16900,
    "team": 44900,
}

# Отображаемые имена. Казус: enum `team` исторически занят тиром Business,
# поэтому средний тир «Team» живёт под enum-значением `growth` (см. PlanType).
PLAN_NAMES = {
    "starter": "Starter",
    "growth": "Team",
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
            "can_invite_members": PLAN_LIMITS[plan]["can_invite"],
            "price_monthly_rub": PLAN_PRICES_RUB.get(plan.value, 0),
            "payment_provider": (
                "yookassa" if settings.yookassa_shop_id and settings.yookassa_secret_key
                else "unconfigured"
            ),
        }
        for plan in [PlanType.starter, PlanType.growth, PlanType.pro, PlanType.team]
    ]
