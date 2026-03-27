from fastapi import HTTPException

from app.models import Organization, PlanType

PLAN_LIMITS = {
    PlanType.starter: {"projects": 3, "users": 3, "leads_per_month": 1000, "can_invite": True},
    PlanType.pro: {"projects": 20, "users": 15, "leads_per_month": 10000, "can_invite": True},
    PlanType.team: {"projects": 100, "users": 100, "leads_per_month": 100000, "can_invite": True},
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
