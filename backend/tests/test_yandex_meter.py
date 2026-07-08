"""Per-org Yandex Geosearch request meter + per-tier cap."""
from types import SimpleNamespace

import httpx

from app.models import Organization, PlanType
from app.services import quota
from app.services import lead_collection as lc


def test_apply_plan_limits_sets_yandex_caps():
    # Сетка 2026-07-09: growth («Team») 550, Pro 1 200, Business 2 800.
    expected = {
        PlanType.free: 0, PlanType.starter: 0, PlanType.growth: 550,
        PlanType.pro: 1200, PlanType.team: 2800,
    }
    for plan, cap in expected.items():
        o = Organization(plan=plan)
        quota.apply_plan_limits(o)
        assert o.yandex_requests_limit_per_month == cap


def test_yandex_requests_remaining_boundary():
    o = Organization(plan=PlanType.pro)
    quota.apply_plan_limits(o)
    cap = quota.PLAN_LIMITS[PlanType.pro]["yandex_requests"]
    o.yandex_requests_used_current_month = 0
    assert quota.yandex_requests_remaining(o) == cap
    o.yandex_requests_used_current_month = cap - 1
    assert quota.yandex_requests_remaining(o) == 1
    o.yandex_requests_used_current_month = cap
    assert quota.yandex_requests_remaining(o) == 0
    o.yandex_requests_used_current_month = cap + 8599  # overshoot clamps, never negative
    assert quota.yandex_requests_remaining(o) == 0
    # Starter/Free have no Yandex budget at all.
    s = Organization(plan=PlanType.starter)
    quota.apply_plan_limits(s)
    assert quota.yandex_requests_remaining(s) == 0


def test_grandfather_override_survives_lapse_and_repurchase():
    """Обещание «пилотам Pro кап 1 400 навсегда» живёт в организационном
    yandex_requests_cap_override и переживает полный lapse-цикл:
    Pro(1 400) → карта не прошла → free(0) → повторная покупка Pro → снова
    1 400, а не шаблонные 1 200. Ровно сценарий major-находки ревью #2."""
    o = Organization(plan=PlanType.pro)
    o.yandex_requests_cap_override = 1400
    quota.apply_plan_limits(o)
    assert o.yandex_requests_limit_per_month == 1400
    # lapse: ночной даунгрейд в free — кап обнулён, override не тронут.
    o.plan = PlanType.free
    quota.apply_plan_limits(o)
    assert o.yandex_requests_limit_per_month == 0
    assert o.yandex_requests_cap_override == 1400
    # повторная покупка Pro наутро — обещание вернулось.
    o.plan = PlanType.pro
    quota.apply_plan_limits(o)
    assert o.yandex_requests_limit_per_month == 1400


def test_renewal_does_not_weld_admin_granted_higher_cap():
    """Кап более высокого тира, выданного админом (Business 2 800 без
    Subscription-строки), НЕ приваривается к продлеваемому нижнему плану:
    в override его нет, а сохранённый лимит-колонка шаблоном перетирается.
    Ровно сценарий major-находки ревью #1 (было ×6,4 — пробой ×10)."""
    o = Organization(plan=PlanType.team)  # админ выдал Business
    quota.apply_plan_limits(o)
    assert o.yandex_requests_limit_per_month == 2800
    # ночное продление реальной Pro-подписки: план возвращается на Pro.
    o.plan = PlanType.pro
    quota.apply_plan_limits(o)
    assert o.yandex_requests_limit_per_month == quota.PLAN_LIMITS[PlanType.pro]["yandex_requests"]


def test_grandfather_override_applies_only_on_pro():
    """Override — обещание ИМЕННО НА PRO (16 900 ₽) и никуда не переносится:
    Free/Starter — капа нет; Team (growth, 9 900 ₽) — шаблонные 550 (перенос
    1 400 дал бы наценку ×7,0 — пробой ×10, major адверсариал-верификации);
    Business — шаблонные 2 800 (и так выше). Только Pro получает 1 400."""
    expected = {
        PlanType.free: 0,
        PlanType.starter: 0,
        PlanType.growth: 550,   # НЕ 1 400 — обещание к 9 900 ₽ не привязано
        PlanType.pro: 1400,
        PlanType.team: 2800,
    }
    for plan, cap in expected.items():
        o = Organization(plan=plan)
        o.yandex_requests_cap_override = 1400
        quota.apply_plan_limits(o)
        assert o.yandex_requests_limit_per_month == cap, plan


def test_grandfather_pilot_buying_team_keeps_x10_margin():
    """Ровно сценарий major-находки: пилот с override=1400 покупает Team
    9 900 ₽ (checkout разрешён — план отличается). Кап обязан быть шаблонным
    550: худшая себестоимость 550×0,69 + 150 + 297 = 827 ₽ → ×12,0. С капом
    1 400 было бы 1 413 ₽ → ×7,0 — пробой инварианта ×10."""
    o = Organization(plan=PlanType.pro)
    o.yandex_requests_cap_override = 1400
    quota.apply_plan_limits(o)
    assert o.yandex_requests_limit_per_month == 1400
    # даунгрейд-покупка Team (вебхук payment.succeeded)
    o.plan = PlanType.growth
    quota.apply_plan_limits(o)
    cap = o.yandex_requests_limit_per_month
    assert cap == 550, cap
    worst_cost = cap * 0.69 + 150 + 0.03 * 9900
    assert 9900 / worst_cost >= 10, worst_cost
    # ...и обещание не потеряно: вернулся на Pro → снова 1 400.
    o.plan = PlanType.pro
    quota.apply_plan_limits(o)
    assert o.yandex_requests_limit_per_month == 1400


def test_charge_yandex_requests_accumulates():
    import uuid
    from app.db.session import SessionLocal
    db = SessionLocal()
    oid = None
    try:
        o = Organization(name=f"ymeter-{uuid.uuid4().hex[:8]}", plan=PlanType.pro)
        quota.apply_plan_limits(o)
        db.add(o)
        db.commit()
        oid = o.id
        lc._charge_yandex_requests(str(oid), 5)
        lc._charge_yandex_requests(str(oid), 3)
        db.expire_all()
        assert db.get(Organization, oid).yandex_requests_used_current_month == 8
        # no-ops: missing org / zero count must not change the meter
        lc._charge_yandex_requests(None, 9)
        lc._charge_yandex_requests(str(oid), 0)
        db.expire_all()
        assert db.get(Organization, oid).yandex_requests_used_current_month == 8
    finally:
        if oid is not None:
            obj = db.get(Organization, oid)
            if obj:
                db.delete(obj)
                db.commit()
        db.close()


class _FakeResp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._p


def test_search_yandex_maps_meters_every_billable_request(monkeypatch):
    """The meter must equal the actual count of org-search requests made —
    including the geo/bbox lookup, which hits the same billable endpoint."""
    monkeypatch.setattr(lc, "_YANDEX_DEAD_KEY", False)
    lc._YANDEX_BBOX_CACHE.clear()
    monkeypatch.setattr(
        lc, "get_settings",
        lambda: SimpleNamespace(yandex_maps_api_key="testkey", yandex_maps_lang="ru_RU"),
    )
    monkeypatch.setattr(lc.time, "sleep", lambda *_a, **_k: None)

    calls = {"n": 0}

    def fake_get(self, url, params=None, **k):
        if str(url).startswith(lc._YANDEX_SEARCH_URL):
            calls["n"] += 1
        if (params or {}).get("type") == "geo":
            return _FakeResp({"features": [{"properties": {"boundedBy": [[37.0, 55.4], [38.1, 56.0]]}}]})
        feats = [
            {"properties": {"CompanyMetaData": {
                "name": f"Компания {i}", "address": "Тест, 1",
                "Phones": [{"formatted": "+7 999 000-00-00"}], "url": ""}}}
            for i in range(18)
        ]
        return _FakeResp({"features": feats})

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    charged = []
    monkeypatch.setattr(lc, "_charge_yandex_requests", lambda oid, n: charged.append((oid, n)))

    leads = lc._search_yandex_maps("автосервис", "Тестоград", [], 15, organization_id="org-42")

    assert leads, "expected parsed leads from the fake feed"
    assert charged, "metering must be invoked"
    oid, n = charged[-1]
    assert oid == "org-42"
    assert n == calls["n"]      # meter == every billable request (bbox + pages)
    assert n >= 2               # at least the geo lookup + one results page

    # No org_id → no charge attempted.
    charged.clear()
    lc._YANDEX_BBOX_CACHE.clear()
    lc._search_yandex_maps("автосервис", "Другоград", [], 15)
    assert charged and charged[-1][0] is None
