"""Per-org Yandex Geosearch request meter + per-tier cap."""
from types import SimpleNamespace

import httpx

from app.models import Organization, PlanType
from app.services import quota
from app.services import lead_collection as lc


def test_apply_plan_limits_sets_yandex_caps():
    expected = {
        PlanType.free: 0, PlanType.starter: 0,
        PlanType.pro: 1400, PlanType.team: 3800,
    }
    for plan, cap in expected.items():
        o = Organization(plan=plan)
        quota.apply_plan_limits(o)
        assert o.yandex_requests_limit_per_month == cap


def test_yandex_requests_remaining_boundary():
    o = Organization(plan=PlanType.pro)
    quota.apply_plan_limits(o)
    o.yandex_requests_used_current_month = 0
    assert quota.yandex_requests_remaining(o) == 1400
    o.yandex_requests_used_current_month = 1399
    assert quota.yandex_requests_remaining(o) == 1
    o.yandex_requests_used_current_month = 1400
    assert quota.yandex_requests_remaining(o) == 0
    o.yandex_requests_used_current_month = 9999  # overshoot clamps, never negative
    assert quota.yandex_requests_remaining(o) == 0
    # Starter/Free have no Yandex budget at all.
    s = Organization(plan=PlanType.starter)
    quota.apply_plan_limits(s)
    assert quota.yandex_requests_remaining(s) == 0


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
