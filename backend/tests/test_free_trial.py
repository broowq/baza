"""Пробный доступ (13.07.2026): 10 разовых лидов на Free.

Ключевое отличие от отклонённого «Free-50»: лиды НЕ возобновляются —
месячный сброс квот не трогает free-орги, поэтому «10/мес» в PLAN_LIMITS
на деле «10 навсегда». Триал даёт Starter-уровень источников (2ГИС/веб/склад,
без Яндекса) и 10 ₽ AI на качество первого сбора.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.models import Organization, PlanType
from app.services import quota

_PFX = "trial-"


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
        s.rollback()
        s.execute(delete(Organization).where(Organization.name.like(f"{_PFX}%")))
        s.commit()
    finally:
        s.close()


def _free_org(used: int = 0) -> Organization:
    org = Organization(name=f"{_PFX}{uuid.uuid4().hex[:8]}", plan=PlanType.free)
    quota.apply_plan_limits(org)
    org.leads_used_current_month = used
    return org


# ── лимиты триала ────────────────────────────────────────────────────────────

def test_free_plan_gets_trial_limits():
    org = _free_org()
    assert org.leads_limit_per_month == 10
    assert org.ai_cost_limit_kopecks_per_month == 1000  # 10 ₽
    assert org.yandex_requests_limit_per_month == 0     # Starter-уровень, без Яндекса


# ── ensure_lead_quota: триал-ветки ───────────────────────────────────────────

def test_trial_allows_collection_under_10():
    quota.ensure_lead_quota(_free_org(used=0), requested=10)
    quota.ensure_lead_quota(_free_org(used=9), requested=1)


def test_trial_clamps_instead_of_429_on_oversized_request():
    """Запрос 50 на триале с остатком 10 НЕ 429-ит — сбор клампится в jobs."""
    quota.ensure_lead_quota(_free_org(used=0), requested=50)  # не должно поднять


def test_trial_exhausted_gives_honest_402():
    with pytest.raises(HTTPException) as exc:
        quota.ensure_lead_quota(_free_org(used=10), requested=5)
    assert exc.value.status_code == 402
    assert "Пробные лиды использованы" in exc.value.detail
    # «дождитесь 1-го числа» было бы ложью — free не сбрасывается
    assert "1-го числа" not in exc.value.detail


def test_former_payer_downgraded_gets_no_second_trial():
    """Бывший платник (used=3000 за месяц) после даунгрейда на free не
    получает триал заново — used уже выше лимита 10."""
    org = _free_org(used=3000)
    with pytest.raises(HTTPException) as exc:
        quota.ensure_lead_quota(org, requested=1)
    assert exc.value.status_code == 402
    assert "Пробные лиды использованы" in exc.value.detail


def test_paid_plan_oversized_request_clamps_not_429():
    """Аудит 16.07: платный клиент с остатком 10, просящий 100, получает
    частичную дозу (кламп ниже по конвейеру), а не сырой 429-тупик."""
    org = Organization(name=f"{_PFX}paid", plan=PlanType.starter)
    quota.apply_plan_limits(org)
    org.leads_used_current_month = 4990
    quota.ensure_lead_quota(org, requested=100)  # не должно поднять

    # полностью исчерпанная квота по-прежнему честный 402
    org.leads_used_current_month = 5000
    with pytest.raises(HTTPException) as exc:
        quota.ensure_lead_quota(org, requested=1)
    assert exc.value.status_code == 402


# ── разовость: месячный сброс не трогает free ───────────────────────────────

def test_monthly_reset_skips_free_orgs(db):
    from app.tasks import periodic

    free_org = _free_org(used=10)
    free_org.ai_cost_used_kopecks_current_month = 900
    paid_org = Organization(name=f"{_PFX}pro-{uuid.uuid4().hex[:6]}", plan=PlanType.pro)
    quota.apply_plan_limits(paid_org)
    paid_org.leads_used_current_month = 5000
    paid_org.ai_cost_used_kopecks_current_month = 15000
    db.add_all([free_org, paid_org])
    db.commit()
    fid, pid = free_org.id, paid_org.id

    periodic.reset_monthly_quotas()
    db.expire_all()

    f = db.get(Organization, fid)
    p = db.get(Organization, pid)
    # free: триал РАЗОВЫЙ — использованное не возвращается
    assert f.leads_used_current_month == 10
    assert f.ai_cost_used_kopecks_current_month == 900
    # платный: обычный месячный сброс работает
    assert p.leads_used_current_month == 0
    assert p.ai_cost_used_kopecks_current_month == 0


def test_zero_limit_still_blocked_with_paid_plan_message():
    """Ветка limit=0 (админ обнулил лимит руками) осталась и после триала:
    честный 402 «на платном тарифе» — покрытие, потерянное при переписывании
    старого free-теста (ревью 13.07)."""
    org = Organization(name=f"{_PFX}zero", plan=PlanType.free)
    quota.apply_plan_limits(org)
    org.leads_limit_per_month = 0  # админ-обнуление
    with pytest.raises(HTTPException) as exc:
        quota.ensure_lead_quota(org, requested=1)
    assert exc.value.status_code == 402
    assert "платном тарифе" in exc.value.detail
