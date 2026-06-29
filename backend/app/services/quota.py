"""Per-organization quota enforcement.

Two parallel quotas are tracked: leads collected this month, and AI/LLM
spend this month (kopecks ₽×100). Both reset on the 1st via celery beat.

The AI cap exists because every search now hits an LLM (prompt enhancer +
candidate filter), so a single noisy team can otherwise drain the shared
YandexGPT / GigaChat / Anthropic credit pool. The cap is denominated in
kopecks so we can do all accounting in plain ints without float drift.
"""
from fastapi import HTTPException

from app.models import Organization, PlanType


# Limits per plan. Sized 2026-06-29 for a GUARANTEED ×10 markup (cost-of-goods
# ≤ 10% of price even at full utilisation), at the now-confirmed published
# Yandex rate ₽0.69/req (1k/day). Worst-case cost = yandex_requests×0.69 +
# ai_cost + 3% acquiring; see docs/unit-economics.md for the full table.
#   Starter 3 900 ₽ · 5 000 leads · no Yandex      → ~217 ₽  (×18)
#   Pro     16 900 ₽ · 7 000 leads · 1 400 Yandex  → ~1 673 ₽ (×10.1)
#   Business44 900 ₽ · 20 000 leads · 3 800 Yandex → ~4 469 ₽ (×10.0)
# Yandex «с сохранением» is NOT needed: Yandex allows storing API results ≤30
# days on the regular tariff (support, 2026-06-29), so the published rate is our
# real rate. ai_cost_kopecks = monthly LLM ceiling (₽×100); cut to ₽100/200/500
# — typical spend (~₽50/80/200) sits well under, the cap just guarantees the ×10
# floor. yandex_requests = monthly PAID-Geosearch-request cap (measured ~0.21
# req/lead); when exhausted, collection falls back to 2GIS/SearXNG. Existing
# pilots keep their old limits until a plan change reconciles.
PLAN_LIMITS = {
    PlanType.free: {
        "projects": 1, "users": 1, "leads_per_month": 0,
        "can_invite": False, "ai_cost_kopecks": 0, "yandex_requests": 0,
    },
    PlanType.starter: {
        "projects": 5, "users": 3, "leads_per_month": 5000,
        "can_invite": True, "ai_cost_kopecks": 10000, "yandex_requests": 0,
    },
    PlanType.pro: {
        "projects": 20, "users": 10, "leads_per_month": 7000,
        "can_invite": True, "ai_cost_kopecks": 20000, "yandex_requests": 1400,
    },
    PlanType.team: {
        "projects": 100, "users": 50, "leads_per_month": 20000,
        "can_invite": True, "ai_cost_kopecks": 50000, "yandex_requests": 3800,
    },
}


def apply_plan_limits(organization: Organization) -> None:
    limits = PLAN_LIMITS[organization.plan]
    organization.projects_limit = limits["projects"]
    organization.users_limit = limits["users"]
    organization.leads_limit_per_month = limits["leads_per_month"]
    organization.can_invite_members = limits["can_invite"]
    organization.ai_cost_limit_kopecks_per_month = limits["ai_cost_kopecks"]
    organization.yandex_requests_limit_per_month = limits["yandex_requests"]


def yandex_requests_remaining(organization: Organization) -> int:
    """Paid Yandex Geosearch requests the org has left this month (0 if no cap)."""
    limit = organization.yandex_requests_limit_per_month or 0
    if limit <= 0:
        return 0
    used = organization.yandex_requests_used_current_month or 0
    return max(0, limit - used)


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


# Tier order — used to pick the best plan when an org has several overlapping
# active subscriptions (e.g. mid-cycle upgrade) and one of them lapses/refunds.
_PLAN_TIER = {PlanType.free: 0, PlanType.starter: 1, PlanType.pro: 2, PlanType.team: 3}


def _plan_from_id(plan_id: str):
    try:
        return PlanType(plan_id)
    except (ValueError, TypeError):
        return None


def reconcile_org_plan(organization_db, organization, *, now=None, exclude_sub_id=None):
    """Set the org's plan to the highest tier it STILL actively pays for, then
    re-apply limits. Returns the resulting PlanType.

    "Actively pays for" = a Subscription row with status='active' whose
    current_period_end is in the future (excluding `exclude_sub_id` — the row
    that just lapsed/was refunded; needed because autoflush is off, so its
    new status may not be visible to this query yet). If nothing covers the org,
    it drops to free. This keeps an org with multiple overlapping subscriptions
    on exactly the plan it's entitled to — never wrongly downgraded while another
    paid subscription is live, never left on a plan it no longer pays for.
    """
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.models import Subscription

    db = organization_db
    if now is None:
        now = datetime.now(timezone.utc)
    q = select(Subscription).where(
        Subscription.organization_id == organization.id,
        Subscription.status == "active",
        Subscription.current_period_end.is_not(None),
        Subscription.current_period_end >= now,
    )
    if exclude_sub_id is not None:
        q = q.where(Subscription.id != exclude_sub_id)
    covering = db.execute(q).scalars().all()

    new_plan = PlanType.free
    plans = [p for p in (_plan_from_id(s.plan_id) for s in covering) if p is not None]
    if plans:
        new_plan = max(plans, key=lambda p: _PLAN_TIER.get(p, 0))

    organization.plan = new_plan
    apply_plan_limits(organization)
    return new_plan
