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


# Limits per plan. leads_per_month is the REAL enforced cap (see
# ensure_lead_quota). Collection is now DOSED: each "Собрать" adds ≤10 NEW
# companies (no repeats), so leads_per_month ÷ ~10 ≈ collections/month.
# ai_cost_kopecks = monthly LLM spend ceiling in kopecks (₽ × 100).
#   free:    0       (no LLM access — rule-based only)
#   starter: 30000   (₽300/mo)
#   pro:     300000  (₽3000/mo)
#   team:    1500000 (₽15000/mo)
# Lead quotas cut 2026-06-25 to deliverable/profitable sizes (pro 25k→10k,
# team 100k→30k) — the old numbers were unreachable for most niches and
# loss-making at full Yandex use. Existing pilots keep their old limits (no
# monthly re-apply; only a plan change reconciles).
# yandex_requests = monthly cap on PAID Yandex Geosearch requests (the dominant
# variable cost — measured ~0.21 request/lead, see docs/unit-economics.md). The
# cap bounds worst-case spend per org regardless of the Yandex tariff: at
# ₽0.69/req (1k/day) pro≈₽2.1k, team≈₽6.9k. Starter/Free = 0 (Yandex is a
# Pro/Team source; they collect from 2GIS/SearXNG). Tune up on the cheaper
# 10k/day tariff or once the "с сохранением" rate is known.
PLAN_LIMITS = {
    PlanType.free: {
        "projects": 1, "users": 1, "leads_per_month": 0,
        "can_invite": False, "ai_cost_kopecks": 0, "yandex_requests": 0,
    },
    PlanType.starter: {
        "projects": 5, "users": 3, "leads_per_month": 5000,
        "can_invite": True, "ai_cost_kopecks": 30000, "yandex_requests": 0,
    },
    PlanType.pro: {
        "projects": 20, "users": 10, "leads_per_month": 10000,
        "can_invite": True, "ai_cost_kopecks": 300000, "yandex_requests": 3000,
    },
    PlanType.team: {
        "projects": 100, "users": 50, "leads_per_month": 30000,
        "can_invite": True, "ai_cost_kopecks": 1500000, "yandex_requests": 10000,
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
