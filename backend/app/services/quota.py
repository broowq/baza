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


# Limits per plan. Re-gridded 2026-07-09 from market research (see
# docs/unit-economics.md §4): the ×4.3 price gap Starter→Pro sat exactly on the
# RF self-serve corridor 5–10 тыс ₽ (Coldy Про 6 000, Компас-месяц 9 700) — the
# new `growth` («Team») tier closes it. Lead quotas raised on Pro/Business:
# extra leads come from free sources (2GIS/SearXNG), so ₽/lead now FALLS as you
# upgrade (0.98 → 0.99 → 0.85 → 0.82) — the industry upgrade driver.
#
# The ×10-markup floor is kept with BUFFER now (was razor-thin 9.9–9.95%):
# worst-case cost = yandex_requests×0.69 + ai_cost + 3% acquiring.
#   Starter  4 900 ₽ ·  5 000 leads · no Yandex     → ~247 ₽   (×19.8)
#   Team     9 900 ₽ · 10 000 leads ·   550 Yandex  → ~827 ₽   (×12.0)
#   Pro     16 900 ₽ · 20 000 leads · 1 200 Yandex  → ~1 535 ₽ (×11.0)
#   Business44 900 ₽ · 55 000 leads · 2 800 Yandex  → ~3 779 ₽ (×11.9)
# Yandex «с сохранением» is NOT needed: storing API results ≤30 days is allowed
# on the regular tariff (support, 2026-06-29), so the published ₽0.69/req rate
# is our real rate. ai_cost_kopecks = monthly LLM ceiling (₽×100); typical
# spend (~₽50/80/200) sits well under — the cap just guarantees the markup
# floor. yandex_requests = monthly PAID-Geosearch cap (measured ~0.21 req/lead);
# when exhausted, collection falls back to 2GIS/SearXNG.
#
# GRANDFATHER: пилоты, купившие Pro до 2026-07-09 с капом 1 400, держат его
# навсегда через организационный yandex_requests_cap_override (миграция
# c7f1a3e5d9b2 проставила его автоматически). Override — персональное ОБЕЩАНИЕ,
# а не остаток прежнего плана: переживает lapse/даунгрейд/повторную покупку и
# никогда не переносит кап чужого тира (действует только там, где шаблонный
# кап > 0).
PLAN_LIMITS = {
    # Free = ПРОБНЫЙ доступ (решение 13.07.2026): 10 лидов РАЗОВО — счётчик
    # used у free-оргов не сбрасывается месячным reset (см. periodic.
    # reset_monthly_quotas), поэтому «10/мес» здесь на деле «10 навсегда».
    # AI 10 ₽ — чтобы энхансер и LLM-фильтр работали на первом сборе (wow-
    # эффект триала); тоже разовые из-за нескидываемого reset. Яндекса нет —
    # источники Starter-уровня (2ГИС/веб/склад). Это НЕ отклонённый «Free-50»:
    # лиды не возобновляются.
    PlanType.free: {
        "projects": 1, "users": 1, "leads_per_month": 10,
        "can_invite": False, "ai_cost_kopecks": 1000, "yandex_requests": 0,
    },
    PlanType.starter: {
        "projects": 5, "users": 3, "leads_per_month": 5000,
        "can_invite": True, "ai_cost_kopecks": 10000, "yandex_requests": 0,
    },
    PlanType.growth: {  # отображается как «Team»
        "projects": 10, "users": 5, "leads_per_month": 10000,
        "can_invite": True, "ai_cost_kopecks": 15000, "yandex_requests": 550,
    },
    PlanType.pro: {
        "projects": 20, "users": 10, "leads_per_month": 20000,
        "can_invite": True, "ai_cost_kopecks": 20000, "yandex_requests": 1200,
    },
    PlanType.team: {
        "projects": 100, "users": 50, "leads_per_month": 55000,
        "can_invite": True, "ai_cost_kopecks": 50000, "yandex_requests": 2800,
    },
}


def apply_plan_limits(organization: Organization) -> None:
    """Записать лимиты тарифа в колонки организации.

    Grandfather: yandex_requests_cap_override — персональное обещание ранним
    пилотам ИМЕННО НА PRO («кап 1 400 навсегда», миграция c7f1a3e5d9b2).
    Применяется ТОЛЬКО когда организация на Pro: на Free/Starter капа нет
    вовсе, на Business шаблон (2 800) и так выше, а на Team (growth, 9 900 ₽)
    перенос 1 400 давал бы наценку ×7,0 — пробой инварианта ×10 (найдено
    адверсариал-верификацией: обещание давалось на тариф 16 900 ₽, к цене
    9 900 ₽ оно не привязано).
    """
    limits = PLAN_LIMITS[organization.plan]
    organization.projects_limit = limits["projects"]
    organization.users_limit = limits["users"]
    organization.leads_limit_per_month = limits["leads_per_month"]
    organization.can_invite_members = limits["can_invite"]
    organization.ai_cost_limit_kopecks_per_month = limits["ai_cost_kopecks"]
    yandex_cap = limits["yandex_requests"]
    override = organization.yandex_requests_cap_override or 0
    if organization.plan == PlanType.pro and override > 0:
        yandex_cap = max(yandex_cap, override)
    organization.yandex_requests_limit_per_month = yandex_cap


def yandex_requests_remaining(organization: Organization) -> int:
    """Paid Yandex Geosearch requests the org has left this month (0 if no cap)."""
    limit = organization.yandex_requests_limit_per_month or 0
    if limit <= 0:
        return 0
    used = organization.yandex_requests_used_current_month or 0
    return max(0, limit - used)


def ensure_lead_quota(organization: Organization, requested: int) -> None:
    # Нулевой лимит (не должен встречаться после триала 13.07, но лимиты
    # правятся и админом): сбор недоступен без тарифа.
    if (organization.leads_limit_per_month or 0) <= 0:
        raise HTTPException(status_code=402, detail="Сбор лидов доступен на платном тарифе. Выберите тариф, чтобы начать.")
    if organization.leads_used_current_month >= organization.leads_limit_per_month:
        if organization.plan == PlanType.free:
            # Триал (10 разовых лидов) исчерпан — у free счётчик не
            # сбрасывается, поэтому «дождитесь 1-го числа» было бы ложью.
            raise HTTPException(
                status_code=402,
                detail="Пробные лиды использованы. Выберите тариф, чтобы продолжить сбор.",
            )
        raise HTTPException(status_code=402, detail="Месячная квота лидов исчерпана — обновите тариф или дождитесь 1-го числа.")
    if organization.leads_used_current_month + requested > organization.leads_limit_per_month:
        # Для триала не 429-им «слишком много запрошено» — молча соберём
        # остаток (кламп по квоте в jobs), иначе просьба «50 лидов» на триале
        # с 10 умирала бы ошибкой вместо частичной выдачи.
        if organization.plan == PlanType.free:
            return
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
_PLAN_TIER = {
    PlanType.free: 0,
    PlanType.starter: 1,
    PlanType.growth: 2,
    PlanType.pro: 3,
    PlanType.team: 4,
}


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
    # Grandfather-кап пилотов живёт в yandex_requests_cap_override и
    # применяется внутри apply_plan_limits — здесь ничего сохранять не надо.
    apply_plan_limits(organization)
    return new_plan
