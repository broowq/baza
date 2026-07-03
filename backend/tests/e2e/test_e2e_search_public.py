"""E2E: search routes (/api/search/*) and public/unauth surfaces.

Two route families covered:

1. /api/search/preview and /api/search/companies — authed company search.
   IMPORTANT HARNESS NOTE: these routes import `search_leads` DIRECTLY from
   `app.services.lead_collection` (see app/api/routes/search.py line 11), NOT
   through the `app.tasks.jobs` seam that `stub_sources` patches. So the
   `stub_sources` fixture does NOT make these routes deterministic/offline —
   calling them for real would hit the live network. Per the coverage spec we
   therefore assert the contract we CAN verify offline:
     - auth required (401 without a token),
     - payload validation (422 on bad/missing body),
     - quota / ownership guards (project not found → 404, role gate → 403),
   and we prove the response wiring/shape with a test-LOCAL monkeypatch of the
   route's own `search_leads` binding (this does NOT touch conftest).

2. /api/public/landing — unauthenticated marketing stats, and the liveness
   endpoint GET /health (mounted at the app root, NOT under /api).
"""
from __future__ import annotations

import pytest

import app.api.routes.search as search_route


# ── /api/search/* require auth ──────────────────────────────────────────────

def test_search_preview_requires_auth(client):
    """No token → 401 (OAuth2 bearer auto_error), never a silent search."""
    r = client.post("/api/search/preview", json={"query": "стоматология"})
    assert r.status_code == 401, r.text


def test_search_companies_requires_auth(client):
    r = client.post(
        "/api/search/companies",
        json={"query": "стоматология", "project_id": "x", "limit": 5},
    )
    assert r.status_code == 401, r.text


def test_search_preview_rejects_bad_token(client):
    """A garbage bearer token is rejected at auth, not treated as valid."""
    r = client.post(
        "/api/search/preview",
        json={"query": "стоматология"},
        headers={"Authorization": "Bearer not-a-real-jwt"},
    )
    assert r.status_code == 401, r.text


def test_auth_precedes_body_validation(client):
    """Unauthenticated + invalid body still surfaces 401 (auth dependency runs
    before body validation), so secrets/quotas are never touched on a bad call."""
    r = client.post("/api/search/preview", json={})  # missing required 'query'
    assert r.status_code == 401, r.text


# ── /api/search/preview payload validation (authed) ─────────────────────────

def test_search_preview_missing_query_422(paid_account):
    r = paid_account.post("/api/search/preview", json={})
    assert r.status_code == 422, r.text


def test_search_preview_empty_query_422(paid_account):
    """query has min_length=1 → empty string is rejected."""
    r = paid_account.post("/api/search/preview", json={"query": ""})
    assert r.status_code == 422, r.text


def test_search_preview_limit_out_of_range_422(paid_account):
    """limit is bounded 1..100; 0 and 101 both fail validation."""
    too_low = paid_account.post(
        "/api/search/preview", json={"query": "клиника", "limit": 0}
    )
    assert too_low.status_code == 422, too_low.text
    too_high = paid_account.post(
        "/api/search/preview", json={"query": "клиника", "limit": 101}
    )
    assert too_high.status_code == 422, too_high.text


def test_search_preview_query_too_long_422(paid_account):
    """query has max_length=200."""
    r = paid_account.post("/api/search/preview", json={"query": "к" * 201})
    assert r.status_code == 422, r.text


# ── /api/search/preview happy path (route-local stub, conftest untouched) ────

def test_search_preview_returns_result_items(paid_account, monkeypatch):
    """Prove the route wiring + response shape WITHOUT network: patch the
    route's own `search_leads` binding (NOT conftest) to canned rows and assert
    they are mapped into SearchResultItem shape (company→name, website→url)."""
    canned = [
        {
            "company": "Тестовая Клиника",
            "domain": "klinika.example",
            "website": "https://klinika.example",
            "source": "2gis",
            "city": "Москва",
            "address": "Москва, ул. Тестовая, 1",
            "relevance_score": 90,
        }
    ]
    monkeypatch.setattr(search_route, "search_leads", lambda *a, **k: list(canned))

    r = paid_account.post(
        "/api/search/preview",
        json={"query": "стоматология", "geography": "Москва", "limit": 5},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list) and len(body) == 1
    item = body[0]
    # Field mapping per _to_result_items().
    assert item["name"] == "Тестовая Клиника"
    assert item["url"] == "https://klinika.example"
    assert item["domain"] == "klinika.example"
    assert item["source"] == "2gis"
    assert item["city"] == "Москва"
    # preview is a dry run: it must NOT persist leads.
    assert {"name", "domain", "url", "source", "city", "address"} <= set(item)


def test_search_preview_does_not_persist_leads(paid_account, new_project, monkeypatch):
    """A preview never writes to the project's lead table."""
    project = new_project(paid_account)
    pid = project["id"]
    monkeypatch.setattr(
        search_route,
        "search_leads",
        lambda *a, **k: [
            {
                "company": "Не Сохранять",
                "domain": "nope.example",
                "website": "https://nope.example",
                "source": "2gis",
                "city": "Москва",
                "address": "",
                "relevance_score": 50,
            }
        ],
    )
    pre = paid_account.post(
        "/api/search/preview", json={"query": "клиника", "limit": 3}
    )
    assert pre.status_code == 200, pre.text
    assert len(pre.json()) == 1

    table = paid_account.get(f"/api/leads/project/{pid}/table?per_page=50")
    assert table.status_code == 200, table.text
    assert table.json()["total"] == 0, "preview must not create leads"


# ── /api/search/companies guards (authed) ───────────────────────────────────

def test_search_companies_missing_project_id_422(paid_account):
    """project_id is required by SearchCompaniesRequest."""
    r = paid_account.post(
        "/api/search/companies", json={"query": "клиника", "limit": 5}
    )
    assert r.status_code == 422, r.text


def test_search_companies_unknown_project_404(paid_account, monkeypatch):
    """A project id this org does not own → 404 'Проект не найден', and the
    expensive search is never reached. Patch route-local search_leads to a spy
    that raises if invoked, proving the ownership guard short-circuits first."""
    def _boom(*a, **k):
        raise AssertionError("search_leads must not run for an unknown project")

    monkeypatch.setattr(search_route, "search_leads", _boom)
    r = paid_account.post(
        "/api/search/companies",
        json={
            "query": "клиника",
            "limit": 5,
            "project_id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert r.status_code == 404, r.text
    assert "не найден" in r.json()["detail"].lower()


def test_search_companies_foreign_project_404(paid_account, make_account, new_project, monkeypatch):
    """Tenant isolation: org A cannot search-and-save into org B's project."""
    other = make_account(plan="pro")
    foreign = new_project(other)
    foreign_pid = foreign["id"]

    monkeypatch.setattr(
        search_route, "search_leads",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not run")),
    )
    r = paid_account.post(
        "/api/search/companies",
        json={"query": "клиника", "limit": 5, "project_id": foreign_pid},
    )
    assert r.status_code == 404, r.text


def test_search_companies_member_role_forbidden(paid_account, make_account, new_project, db, monkeypatch):
    """search/companies is gated to owner/admin via require_org_roles. A plain
    member of the org gets 403. We attach a second user to the owner's org as a
    'member' and call with that user's token."""
    from sqlalchemy import select
    from app.models import Membership, User

    owner = paid_account
    project = new_project(owner)
    pid = project["id"]

    # A second, independent account whose user we'll graft into owner's org.
    member = make_account()
    member_user = db.execute(
        select(User).where(User.email == member.email)
    ).scalar_one()
    db.add(
        Membership(
            user_id=member_user.id,
            organization_id=owner.org_id,
            role="member",
        )
    )
    db.commit()

    monkeypatch.setattr(
        search_route, "search_leads",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not run")),
    )
    # Call owner's org with the member's token + owner's org id.
    r = member.post(
        "/api/search/companies",
        json={"query": "клиника", "limit": 5, "project_id": pid},
        headers={"X-Org-Id": owner.org_id},
    )
    assert r.status_code == 403, r.text


def test_search_companies_saves_into_owned_project(paid_account, new_project, db, monkeypatch):
    """Happy path with route-local stub: owner search-and-save persists mapped
    leads into their own project (proving the save loop + dedup wiring)."""
    from sqlalchemy import select, func
    from app.models import Lead

    project = new_project(paid_account)
    pid = project["id"]

    canned = [
        {
            "company": "Сохранить Один",
            "domain": "save1.example",
            "website": "https://save1.example",
            "source": "2gis",
            "city": "Москва",
            "address": "Москва, ул. А, 1",
            "relevance_score": 77,
        },
        {
            "company": "Сохранить Два",
            "domain": "save2.example",
            "website": "https://save2.example",
            "source": "yandex",
            "city": "Москва",
            "address": "Москва, ул. Б, 2",
            "relevance_score": 55,
        },
        # duplicate website of #1 → must be deduped, not double-saved.
        {
            "company": "Дубликат",
            "domain": "save1.example",
            "website": "https://save1.example",
            "source": "2gis",
            "city": "Москва",
            "address": "",
            "relevance_score": 10,
        },
        # no website → skipped by the save loop.
        {
            "company": "Без Сайта",
            "domain": "",
            "website": "",
            "source": "2gis",
            "city": "Москва",
            "address": "",
            "relevance_score": 5,
        },
    ]
    monkeypatch.setattr(search_route, "search_leads", lambda *a, **k: list(canned))

    r = paid_account.post(
        "/api/search/companies",
        json={"query": "клиника", "limit": 10, "project_id": pid},
    )
    assert r.status_code == 200, r.text
    saved = r.json()
    # Two unique websites saved (dup + no-website rows excluded).
    assert len(saved) == 2, saved
    names = {row["name"] for row in saved}
    assert names == {"Сохранить Один", "Сохранить Два"}

    # Persisted in DB, org/project scoped, with scores from relevance_score.
    count = db.scalar(
        select(func.count(Lead.id)).where(
            Lead.project_id == pid,
            Lead.organization_id == paid_account.org_id,
        )
    )
    assert count == 2, f"expected 2 saved leads, got {count}"
    scores = {
        s for (s,) in db.execute(
            select(Lead.score).where(Lead.project_id == pid)
        ).all()
    }
    assert 77 in scores and 55 in scores

    # cleanup the leads we wrote (project/org cascade-clean handles the rest,
    # but be tidy so a rerun in the same DB stays clean).
    from sqlalchemy import delete
    db.execute(delete(Lead).where(Lead.project_id == pid))
    db.commit()


def test_search_companies_consumes_lead_quota(paid_account, new_project, db, monkeypatch):
    """Regression: search-and-save must COUNT against the monthly lead quota.

    Before the fix the endpoint only CHECKED the quota (ensure_lead_quota) but
    never incremented leads_used_current_month — an owner/admin could collect
    leads for free via direct API calls, bypassing the metered collect flow."""
    from sqlalchemy import delete, select
    from app.models import Lead, Organization

    project = new_project(paid_account)
    pid = project["id"]

    used_before = db.scalar(
        select(Organization.leads_used_current_month).where(
            Organization.id == paid_account.org_id
        )
    )

    canned = [
        {
            "company": f"Квота {i}",
            "domain": f"quota{i}.example",
            "website": f"https://quota{i}.example",
            "source": "2gis",
            "city": "Москва",
            "address": "",
            "relevance_score": 50,
        }
        for i in (1, 2, 3)
    ]
    monkeypatch.setattr(search_route, "search_leads", lambda *a, **k: list(canned))

    r = paid_account.post(
        "/api/search/companies",
        json={"query": "клиника", "limit": 10, "project_id": pid},
    )
    assert r.status_code == 200, r.text
    assert len(r.json()) == 3

    db.expire_all()
    used_after = db.scalar(
        select(Organization.leads_used_current_month).where(
            Organization.id == paid_account.org_id
        )
    )
    assert used_after == used_before + 3, (
        f"quota must grow by the number of saved leads: {used_before} → {used_after}"
    )

    db.execute(delete(Lead).where(Lead.project_id == pid))
    db.commit()


# ── /api/public/landing — unauthenticated marketing stats ───────────────────

def test_public_landing_no_auth_200_and_shape(client):
    """Public endpoint: no auth, 200, and the full documented landing shape."""
    r = client.get("/api/public/landing")
    assert r.status_code == 200, r.text
    body = r.json()
    # Top-level contract (present whether or not a demo org is seeded).
    for key in (
        "available", "totals", "rates", "avg_score",
        "sources", "by_city", "funnel", "samples", "generated_at",
    ):
        assert key in body, f"missing landing key: {key}"

    assert isinstance(body["available"], bool)
    assert set(body["totals"]) == {
        "leads", "enriched", "with_email", "with_phone", "qualified"
    }
    assert set(body["rates"]) == {"enrichment", "email", "phone", "qualified"}
    assert set(body["funnel"]) == {"found", "added", "enriched", "qualified"}
    assert isinstance(body["sources"], list)
    assert isinstance(body["by_city"], list)
    assert isinstance(body["samples"], list)


def test_public_landing_never_leaks_contacts(client):
    """Privacy invariant: sample rows expose only boolean has_email/has_phone,
    NEVER raw email/phone strings, on this public endpoint."""
    r = client.get("/api/public/landing")
    assert r.status_code == 200, r.text
    for sample in r.json()["samples"]:
        assert "email" not in sample, f"raw email leaked: {sample}"
        assert "phone" not in sample, f"raw phone leaked: {sample}"
        assert isinstance(sample.get("has_email"), bool)
        assert isinstance(sample.get("has_phone"), bool)
        # company/score are public-safe aggregates.
        assert "company" in sample and "score" in sample


def test_public_landing_ignores_auth_header(client, paid_account):
    """Auth is irrelevant here — same payload with or without a token."""
    anon = client.get("/api/public/landing")
    authed = paid_account.get("/api/public/landing")
    assert anon.status_code == authed.status_code == 200
    # Both return the documented top-level shape.
    assert set(anon.json()) == set(authed.json())


# ── liveness ────────────────────────────────────────────────────────────────

def test_health_ok(client):
    """Health is mounted at the app root (NOT under /api) and returns ok."""
    r = client.get("/health")
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "ok"}


def test_api_health_not_mounted(client):
    """Document that there is no /api/health alias — liveness lives at /health."""
    r = client.get("/api/health")
    assert r.status_code == 404, r.text
