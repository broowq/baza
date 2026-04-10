from fastapi import HTTPException

from app.models import Organization, PlanType

# Limits per plan — "searches" = number of "Собрать лиды" clicks per month
# leads_per_month = searches × ~500 average leads per search
PLAN_LIMITS = {
    PlanType.free: {"projects": 1, "users": 1, "leads_per_month": 500, "can_invite": False, "searches": 3},
    PlanType.starter: {"projects": 5, "users": 3, "leads_per_month": 5000, "can_invite": True, "searches": 30},
    PlanType.pro: {"projects": 20, "users": 10, "leads_per_month": 25000, "can_invite": True, "searches": 100},
    PlanType.team: {"projects": 100, "users": 50, "leads_per_month": 100000, "can_invite": True, "searches": 300},
}


def apply_plan_limits(organization: Organization) -> None:
    limits = PLAN_LIMITS[organization.plan]
    organization.projects_limit = limits["projects"]
    organization.users_limit = limits["users"]
    organization.leads_limit_per_month = limits["leads_per_month"]
    organization.can_invite_members = limits["can_invite"]


def ensure_lead_quota(organization: Organization, requested: int) -> None:
    if organization.leads_used_current_month >= organization.leads_limit_per_month:
        raise HTTPException(status_code=402, detail="Месячная квота лидов исчерпана")
    if organization.leads_used_current_month + requested > organization.leads_limit_per_month:
        raise HTTPException(status_code=429, detail="Запрошенное количество лидов превышает месячную квоту")
