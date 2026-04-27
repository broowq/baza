"""Per-organization quota enforcement.

Two parallel quotas are tracked: leads collected this month, and AI/LLM
spend this month (kopecks ₽×100). Both reset on the 1st via celery beat.

The AI cap exists because every search now hits an LLM (prompt enhancer +
candidate filter), so a single noisy team can otherwise drain the shared
GigaChat / Anthropic credit pool. The cap is denominated in kopecks so we
can do all accounting in plain ints without float drift.
"""
from fastapi import HTTPException

from app.models import Organization, PlanType


# Limits per plan — "searches" = number of "Собрать лиды" clicks per month
# leads_per_month = searches × ~500 average leads per search
# ai_cost_kopecks = monthly LLM spend ceiling in kopecks (₽ × 100).
#   free:    0       (no LLM access — rule-based only)
#   starter: 30000   (₽300/mo)
#   pro:     300000  (₽3000/mo)
#   team:    1500000 (₽15000/mo)
PLAN_LIMITS = {
    PlanType.free: {
        "projects": 1, "users": 1, "leads_per_month": 0,
        "can_invite": False, "searches": 0, "ai_cost_kopecks": 0,
    },
    PlanType.starter: {
        "projects": 5, "users": 3, "leads_per_month": 5000,
        "can_invite": True, "searches": 30, "ai_cost_kopecks": 30000,
    },
    PlanType.pro: {
        "projects": 20, "users": 10, "leads_per_month": 25000,
        "can_invite": True, "searches": 100, "ai_cost_kopecks": 300000,
    },
    PlanType.team: {
        "projects": 100, "users": 50, "leads_per_month": 100000,
        "can_invite": True, "searches": 300, "ai_cost_kopecks": 1500000,
    },
}


def apply_plan_limits(organization: Organization) -> None:
    limits = PLAN_LIMITS[organization.plan]
    organization.projects_limit = limits["projects"]
    organization.users_limit = limits["users"]
    organization.leads_limit_per_month = limits["leads_per_month"]
    organization.can_invite_members = limits["can_invite"]
    organization.ai_cost_limit_kopecks_per_month = limits["ai_cost_kopecks"]


def ensure_lead_quota(organization: Organization, requested: int) -> None:
    if organization.leads_used_current_month >= organization.leads_limit_per_month:
        raise HTTPException(status_code=402, detail="Месячная квота лидов исчерпана")
    if organization.leads_used_current_month + requested > organization.leads_limit_per_month:
        raise HTTPException(status_code=429, detail="Запрошенное количество лидов превышает месячную квоту")


def ensure_ai_cost_budget(organization: Organization, *, slack_kopecks: int = 0) -> None:
    """Refuse the call if the org's running spend would exceed its cap.

    `slack_kopecks` lets the caller pre-reserve an estimate (so a single
    very expensive call doesn't squeeze through under-the-wire). Pass 0 to
    only block once the cap is fully hit.
    """
    limit = organization.ai_cost_limit_kopecks_per_month or 0
    used = organization.ai_cost_used_kopecks_current_month or 0
    if limit <= 0:
        # 0 = AI disabled for this plan (free tier). Never raise — callers
        # treat None-from-LLM as "unavailable" and fall back to rule-based.
        # The wrapper short-circuits before calling the upstream API.
        return
    if used + slack_kopecks >= limit:
        # 402 Payment Required — same family as the leads-quota signal so
        # frontend handlers can treat both uniformly.
        raise HTTPException(
            status_code=402,
            detail=(
                "Месячный лимит на AI-обогащение исчерпан. "
                f"Использовано {used // 100} ₽ из {limit // 100} ₽. "
                "Обновите тариф или дождитесь сброса 1-го числа."
            ),
        )


def ai_cost_remaining_kopecks(organization: Organization) -> int:
    """How many kopecks of AI budget the org has left this month.

    Returns 0 when the cap is hit; returns the raw limit when usage is
    not yet recorded. Negative values are clamped to 0 (over-spend can
    happen if a single call exceeds the slack reservation).
    """
    limit = organization.ai_cost_limit_kopecks_per_month or 0
    used = organization.ai_cost_used_kopecks_current_month or 0
    return max(0, limit - used)
