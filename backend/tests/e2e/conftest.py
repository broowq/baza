"""Shared harness for TRUE end-to-end tests.

Drives the real FastAPI app in-process via TestClient with REAL auth
(register → JWT → `Authorization: Bearer` + `X-Org-Id`) against the REAL local
Postgres — NO dependency-override shortcuts, so the whole middleware → auth →
service → DB stack runs for real. Celery runs eager so collect/enrich `.delay()`
jobs execute synchronously in-process. External data sources, the LLM filter and
enrichment are stubbed at the `app.tasks.jobs` seam to canned, cleanable data so
the journeys are deterministic and cost nothing (no network, no API quota).

Each created org/user is tracked and cascade-cleaned at fixture teardown; stub
companies use the E2E_DOMAIN suffix so warehouse rows are removable too.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db.session import SessionLocal
from app.main import app
from app.models import (
    ActionLog,
    CollectionJob,
    Company,
    Invite,
    Lead,
    LeadCallNote,
    Membership,
    Organization,
    PlanType,
    Project,
    Subscription,
    User,
)
from app.services.quota import apply_plan_limits
from app.tasks.celery_app import celery

E2E_COMPANY_PREFIX = "e2estub"  # stub-company domains start with this → cleanable
# Each stub lead needs a DISTINCT registrable domain, else get_base_domain()
# collapses them in dedup and only one lead is delivered.


# ── global test-mode toggles ────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def _celery_eager():
    """Run Celery tasks synchronously in-process so `.delay()` actually runs."""
    prev_eager = celery.conf.task_always_eager
    prev_prop = celery.conf.task_eager_propagates
    celery.conf.task_always_eager = True
    celery.conf.task_eager_propagates = True
    yield
    celery.conf.task_always_eager = prev_eager
    celery.conf.task_eager_propagates = prev_prop


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    """Disable the rate-limit middleware (TestClient hammers register/login)."""
    import app.main as main

    monkeypatch.setattr(main, "_get_rate_limit", lambda *a, **k: None, raising=False)


@pytest.fixture(autouse=True)
def _quiet_notifications(monkeypatch):
    """No real email/telegram in tests — and stop send_email_task from retrying
    (eager Celery propagates the Retry, which spams logs and can leak across)."""
    for target in ("app.services.notifications", "app.tasks.email_tasks", "app.tasks.jobs"):
        try:
            mod = __import__(target, fromlist=["send_email"])
        except Exception:
            continue
        monkeypatch.setattr(mod, "send_email", lambda *a, **k: True, raising=False)
        monkeypatch.setattr(mod, "send_telegram", lambda *a, **k: True, raising=False)


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def db():
    """Direct DB session for tweaks a journey can't do over HTTP (custom quota,
    promoting a user to admin, asserting persisted state). Commit your changes."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ── authenticated account context ───────────────────────────────────────────

@dataclass
class Account:
    client: TestClient
    token: str
    refresh_token: str
    org_id: str
    email: str
    password: str
    full_name: str

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}", "X-Org-Id": self.org_id}

    def request(self, method: str, path: str, **kw):
        headers = {**self.headers, **kw.pop("headers", {})}
        return self.client.request(method, path, headers=headers, **kw)

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, **kw):
        return self.request("POST", path, **kw)

    def patch(self, path, **kw):
        return self.request("PATCH", path, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)


def upgrade_plan(org_id: str, plan: str = "pro") -> None:
    """Promote an org to a paid plan + its quotas (direct DB — a paid org)."""
    db = SessionLocal()
    try:
        org = db.get(Organization, org_id)
        org.plan = PlanType(plan)
        apply_plan_limits(org)
        db.commit()
    finally:
        db.close()


def _safe(db, stmt) -> None:
    try:
        db.execute(stmt)
        db.commit()
    except Exception:
        db.rollback()


def _cleanup(org_ids: list[str], emails: list[str]) -> None:
    db = SessionLocal()
    try:
        for org_id in org_ids:
            for model in (LeadCallNote, Lead, CollectionJob, Project,
                          Subscription, ActionLog, Invite, Membership):
                _safe(db, delete(model).where(model.organization_id == org_id))
            _safe(db, delete(Organization).where(Organization.id == org_id))
        for email in emails:
            _safe(db, delete(User).where(User.email == email))
            # книга триалов: у каждого register() остаётся строка с хэшом —
            # без чистки dev-БД копит сироты с каждым прогоном сьюта
            from app.models import TrialGrant
            from app.services import registration_guard as _rg
            _safe(db, delete(TrialGrant).where(
                TrialGrant.email_identity_hash
                == _rg.trial_identity_hash(_rg.normalize_email_identity(email))
            ))
        _safe(db, delete(Company).where(Company.domain.like(f"{E2E_COMPANY_PREFIX}%")))
    finally:
        db.close()


@pytest.fixture
def make_account(client):
    """Factory: register a fresh org+user, return an authed Account.

    Pass plan="pro"/"starter"/"team" to promote the org (free has a 0-lead
    quota, which blocks collection).
    """
    org_ids: list[str] = []
    emails: list[str] = []

    def _make(plan: str | None = None) -> Account:
        suffix = uuid.uuid4().hex[:10]
        email = f"e2e-{suffix}@example.com"
        password = "password123"
        full_name = "E2E Тест"
        r = client.post("/api/auth/register", json={
            "email": email,
            "full_name": full_name,
            "password": password,
            "organization_name": f"E2E Org {suffix}",
        })
        assert r.status_code in (200, 201), f"register failed: {r.status_code} {r.text}"
        body = r.json()
        emails.append(email)
        orgs = client.get(
            "/api/organizations/my-list",
            headers={"Authorization": f"Bearer {body['access_token']}"},
        )
        assert orgs.status_code == 200, orgs.text
        org_id = orgs.json()[0]["id"]
        org_ids.append(org_id)
        if plan:
            upgrade_plan(org_id, plan)
        return Account(
            client=client,
            token=body["access_token"],
            refresh_token=body["refresh_token"],
            org_id=org_id,
            email=email,
            password=password,
            full_name=full_name,
        )

    yield _make
    _cleanup(org_ids, emails)


@pytest.fixture
def paid_account(make_account) -> Account:
    """A ready-to-use Pro org (25k lead quota) — the common case for journeys."""
    return make_account(plan="pro")


# ── deterministic, free collection/enrichment ──────────────────────────────

@pytest.fixture
def stub_sources(monkeypatch):
    """Make collect/enrich deterministic + network-free at the jobs.py seam.

    The REAL dosing, warehouse write-through, scoring, save loop and job
    lifecycle all execute — only the external sources, the LLM filter and the
    enrichers are replaced with canned data. Returns a mutable `state` dict so
    a test can tune how many candidates each live seed yields.
    """
    state = {"suffix": uuid.uuid4().hex[:8], "n": 12}

    def fake_search_leads(query="", limit=30, *, niche="", geography="",
                          segments=None, prompt="", use_yandex=True,
                          organization_id=None, **_kw):
        # **_kw глотает будущие kwargs search_leads (напр. excluded_segments) —
        # стаб не должен ломаться на каждом расширении сигнатуры (уже наступали:
        # рейт-лимит middleware, теперь excluded_segments).
        out = []
        for i in range(min(limit, state["n"])):
            dom = f"{E2E_COMPANY_PREFIX}{state['suffix']}x{i}.ru"
            out.append({
                "company": f"{(niche or 'Компания').strip()} {i} {state['suffix']}",
                "city": geography or "Москва",
                "domain": dom,
                "website": f"https://{dom}",
                "phone": f"+7 495 000-00-{i:02d}",
                "email": "",
                "address": f"{geography or 'Москва'}, ул. Тестовая, {i}",
                "snippet": f"{niche} {' '.join(segments or [])}".strip(),
                "source": "2gis",
                "relevance_score": 80,
                "categories": [niche or "услуги"],
            })
        return out

    def fake_filter(cands, *a, **k):
        return list(cands)  # keep-all; competitor filtering is unit-tested

    def fake_enrich_web(base_url):
        host = base_url.split("//")[-1].split("/")[0]
        return {"emails": [f"info@{host}"], "phones": []}

    def fake_enrich_2gis(company, city="", firm_id=""):
        return {"emails": [], "phones": ["+7 495 111-22-33"]}

    import app.tasks.jobs as jobs_mod
    monkeypatch.setattr(jobs_mod, "search_leads", fake_search_leads)
    monkeypatch.setattr(jobs_mod, "filter_candidates_llm", fake_filter)
    monkeypatch.setattr(jobs_mod, "enrich_website_contacts", fake_enrich_web)
    monkeypatch.setattr(jobs_mod, "enrich_2gis_lead", fake_enrich_2gis)
    return state


# ── small helpers shared across journeys ────────────────────────────────────

@pytest.fixture
def new_project():
    """Factory fixture: `new_project(acct, niche=..., geography=..., segments=[...])`.

    Creates a project with explicit niche/geo/segments and NO prompt → skips the
    LLM enhance path, keeping journeys deterministic. Returns the JSON body.
    """
    def _create(acct: Account, **over) -> dict:
        suffix = uuid.uuid4().hex[:6]
        payload = {
            "name": over.get("name", f"E2E Проект {suffix}"),
            "niche": over.get("niche", "стоматология"),
            "geography": over.get("geography", "Москва"),
            "segments": over.get("segments", ["частная клиника"]),
            "auto_collection_enabled": over.get("auto_collection_enabled", False),
        }
        r = acct.post("/api/projects", json=payload)
        assert r.status_code in (200, 201), f"create project failed: {r.status_code} {r.text}"
        return r.json()

    return _create
