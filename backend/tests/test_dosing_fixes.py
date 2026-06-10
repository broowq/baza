"""Tests for the dosed-collection audit fixes (jobs.py + company_warehouse.py).

Covers:
  * FIX 1 — warehouse candidates carry relevance_score; it flows into the saved
    lead's "relevance=NN; " notes prefix.
  * FIX 2 — the assembled dose passes the LLM competitor filter, and the dose
    is topped up from the warehouse when the filter shrinks it.
  * FIX 3 — _take() skips unsaveable rows (no false «всё собрано» brick) and
    rusprofile registry rows are saveable.
  * FIX 4 — no exhaustion stamp when live returned ZERO rows (source outage);
    stamp IS set when live returned rows but nothing new was added.
  * FIX 5 — raw-live fallback fires whenever the dose is under-filled; web rows
    get the project city backfilled at write-through (skip for nationwide).
  * FIX 6 — enrich processes never-enriched newest leads first; auto-enrich is
    queued with the exact new lead ids.
  * FIX 7 — rule-based enhancer fallback is used once, never cached.
  * FIX 8 — dose clamped to remaining quota; usage charged per chunk (exact).
  * FIX 9 — a reaper-failed job is never resurrected to done.

Same patterns as tests/test_company_warehouse.py: real local Postgres, _PFX
prefixes for cleanup, filter_candidates_llm monkeypatched to identity (autouse)
so no LLM calls happen.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select, update

from app.db.session import SessionLocal
from app.models import (
    CollectionJob,
    Company,
    JobStatus,
    Lead,
    LeadStatus,
    Organization,
    PlanType,
    Project,
)
from app.services import company_warehouse as cw
from app.tasks import jobs as jobs_mod

_PFX = "dosefix-"


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.execute(delete(Company).where(Company.dedup_key.like(f"%{_PFX}%")))
        session.execute(delete(Company).where(Company.normalized_name.like(f"%{_PFX}%")))
        session.commit()
        session.close()


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    """No telegram, no real enrich enqueue, no email, identity LLM filter."""
    monkeypatch.setattr(jobs_mod, "send_telegram", lambda *a, **k: None)
    monkeypatch.setattr(jobs_mod.enrich_leads_task, "delay", lambda *a, **k: None)
    monkeypatch.setattr(jobs_mod, "_notify_owner_project_ready", lambda *a, **k: None)
    monkeypatch.setattr(jobs_mod, "filter_candidates_llm", lambda cands, *a, **k: cands)


# ── helpers ────────────────────────────────────────────────────────────────

def _cand(**kw):
    base = {
        "company": kw.pop("company", "Тест Компания"),
        "city": kw.pop("city", ""),
        "domain": kw.pop("domain", ""),
        "website": kw.pop("website", ""),
        "email": kw.pop("email", ""),
        "phone": kw.pop("phone", ""),
        "address": kw.pop("address", ""),
        "source": kw.pop("source", "2gis"),
        "score": kw.pop("score", 0),
    }
    base.update(kw)
    return base


def _mk_org_project(db, prefix, niche, geo):
    org = Organization(
        name=f"{prefix}-org-{uuid.uuid4().hex[:6]}",
        plan=PlanType.pro,
        leads_used_current_month=0,
        leads_limit_per_month=100000,
        projects_limit=100,
        users_limit=100,
    )
    db.add(org)
    db.flush()
    proj = Project(
        organization_id=org.id, name=f"{prefix}-proj",
        niche=niche, geography=geo, segments=[], prompt="",
    )
    db.add(proj)
    db.flush()
    db.commit()
    return org, proj


def _run_collect(db, org, proj, dose):
    job = CollectionJob(
        organization_id=org.id, project_id=proj.id,
        status=JobStatus.queued, kind="collect", requested_limit=dose,
    )
    db.add(job)
    db.commit()
    jid = str(job.id)
    jobs_mod.collect_leads_task(jid)
    db.expire_all()
    return db.get(CollectionJob, uuid.UUID(jid))


def _cleanup(db, org, proj):
    db.rollback()
    db.execute(delete(Lead).where(Lead.project_id == proj.id))
    db.execute(delete(CollectionJob).where(CollectionJob.project_id == proj.id))
    db.execute(delete(Project).where(Project.id == proj.id))
    db.execute(delete(Organization).where(Organization.id == org.id))
    db.commit()


# ── FIX 1: relevance_score flows warehouse → save loop ──────────────────────

def test_company_to_candidate_carries_relevance_score(db):
    domain = f"{_PFX}relu.ru"
    niche = f"{_PFX}relu-niche"
    cw.upsert_companies(
        db, [_cand(company="Rel Unit", domain=domain, city="Томск", score=63)], niche=niche
    )
    hits = cw.search_warehouse(db, niche=niche, geography="Томск", limit=10)
    hit = next(h for h in hits if h["domain"] == domain)
    assert hit["relevance_score"] == 63, "warehouse candidate must expose best_score as relevance_score"
    assert hit["score"] == 63


def test_relevance_flows_from_warehouse_to_saved_lead_notes(db, monkeypatch):
    prefix = f"{_PFX}relflow"
    niche = f"{prefix}-niche"
    org, proj = _mk_org_project(db, prefix, niche, "Томск")
    cw.upsert_companies(
        db,
        [_cand(company=f"{prefix} Co", domain=f"{prefix}.ru", city="Томск",
               phone="+7 999 111 22 33", source="2gis", score=57)],
        niche=niche,
    )
    calls = {"n": 0}

    def fake_search_leads(*a, **k):
        calls["n"] += 1
        return []

    monkeypatch.setattr(jobs_mod, "search_leads", fake_search_leads)
    try:
        job = _run_collect(db, org, proj, 1)
        assert job.added_count == 1
        assert calls["n"] == 0, "dose served fully from the warehouse — no live search"
        lead = db.execute(select(Lead).where(Lead.project_id == proj.id)).scalar_one()
        assert lead.notes.startswith("relevance=57; "), \
            "warehouse-served lead must carry the relevance prefix (was always 0 before the fix)"
    finally:
        _cleanup(db, org, proj)


# ── FIX 3: _take skips unsaveable rows; rusprofile rows are saveable ─────────

def test_candidate_saveable_rules():
    sv = jobs_mod._candidate_saveable
    assert not sv({"company": "", "source": "2gis", "phone": "+7"}), "no name → unsaveable"
    assert not sv({"company": "X", "source": "searxng"}), "domain-less web row → unsaveable"
    assert not sv({"company": "X", "source": "2gis"}), \
        "name-only maps row without contacts or registry id → unsaveable"
    assert not sv({"company": "X", "source": "searxng", "domain": "localhost"}), \
        "non-real domain → unsaveable"
    assert sv({"company": "X", "source": "rusprofile", "rusprofile_id": "123"}), \
        "rusprofile id waives the contact requirement"
    assert sv({"company": "X", "source": "warehouse", "rusprofile_id": "123"}), \
        "warehouse-served rusprofile row stays saveable"
    assert sv({"company": "X", "source": "2gis", "phone": "+7"})
    assert sv({"company": "X", "source": "warehouse", "address": "ул. Тест 1"})
    assert sv({"company": "X", "source": "searxng", "website": "https://okna-sibir-realsite.ru"})


def test_unsaveable_warehouse_rows_dont_brick_the_dose(db, monkeypatch):
    """10 high-ranked unsaveable rows used to fill the dose, gate off live search
    and produce a permanent false «всё собрано». Now they are skipped and the
    dose is delivered from live finds."""
    prefix = f"{_PFX}brick"
    niche = f"{prefix}-niche"
    org, proj = _mk_org_project(db, prefix, niche, "Томск")
    # Unsaveable: name-only, no domain/phone/address, no rusprofile id — but
    # ranked ABOVE everything by best_score.
    cw.upsert_companies(
        db,
        [_cand(company=f"{prefix} junk {i}", city="Томск", source="2gis", score=90 + i)
         for i in range(10)],
        niche=niche,
    )
    calls = {"n": 0}

    def fake_search_leads(*a, **k):
        calls["n"] += 1
        return [_cand(company=f"{prefix} good {i}", domain=f"{prefix}{i}.ru", city="Томск",
                      phone=f"+7 000 00{i}", source="2gis", score=10) for i in range(5)]

    monkeypatch.setattr(jobs_mod, "search_leads", fake_search_leads)
    try:
        job = _run_collect(db, org, proj, 5)
        assert calls["n"] == 1, "deficit must be recognized → live search runs"
        assert job.added_count == 5, "dose delivered despite the junk ranking on top"
        assert db.get(Project, proj.id).leads_exhausted_at is None
    finally:
        _cleanup(db, org, proj)


def test_rusprofile_rows_are_saveable_and_enrichable_later(db, monkeypatch):
    prefix = f"{_PFX}rusp"
    niche = f"{prefix}-niche"
    org, proj = _mk_org_project(db, prefix, niche, "Томск")
    cw.upsert_companies(
        db,
        [_cand(company=f"{prefix} ООО {i}", city="Томск", source="rusprofile",
               rusprofile_id=f"99000{i}", score=50) for i in range(3)],
        niche=niche,
    )
    monkeypatch.setattr(jobs_mod, "search_leads", lambda *a, **k: [])
    try:
        job = _run_collect(db, org, proj, 3)
        assert job.added_count == 3, "rusprofile registry rows must be saveable"
        leads = db.execute(select(Lead).where(Lead.project_id == proj.id)).scalars().all()
        assert {l.external_id for l in leads} == {"990000", "990001", "990002"}
        assert all(l.website.startswith("maps://") for l in leads), \
            "contact-less rows get the maps:// placeholder → 2GIS-by-name enrichment path"
    finally:
        _cleanup(db, org, proj)


# ── FIX 4: exhaustion stamp vs source outage ─────────────────────────────────

def test_no_exhaust_stamp_when_live_returned_zero(db, monkeypatch):
    prefix = f"{_PFX}outage"
    org, proj = _mk_org_project(db, prefix, f"{prefix}-niche", "Томск")
    monkeypatch.setattr(jobs_mod, "search_leads", lambda *a, **k: [])
    try:
        job = _run_collect(db, org, proj, 5)
        assert db.get(Project, proj.id).leads_exhausted_at is None, \
            "zero live rows is indistinguishable from an outage — must NOT stamp the cooldown"
        assert job.status == JobStatus.done
        assert job.error and "Источники временно недоступны" in job.error
    finally:
        _cleanup(db, org, proj)


def test_exhaust_stamp_set_when_live_returned_only_known(db, monkeypatch):
    prefix = f"{_PFX}known"
    org, proj = _mk_org_project(db, prefix, f"{prefix}-niche", "Томск")
    db.add(Lead(
        organization_id=org.id, project_id=proj.id,
        company=f"{prefix} Known", city="Томск",
        website=f"https://{prefix}known.ru", domain=f"{prefix}known.ru",
        phone="+7 1", source="2gis", status=LeadStatus.new, score=50,
    ))
    db.commit()
    monkeypatch.setattr(
        jobs_mod, "search_leads",
        lambda *a, **k: [_cand(company=f"{prefix} Known", domain=f"{prefix}known.ru",
                               city="Томск", phone="+7 1", source="2gis")],
    )
    try:
        job = _run_collect(db, org, proj, 5)
        assert job.added_count == 0
        assert db.get(Project, proj.id).leads_exhausted_at is not None, \
            "live RETURNED rows and nothing was new → genuinely exhausted, stamp the cooldown"
    finally:
        _cleanup(db, org, proj)


# ── FIX 5: raw-live fallback + city backfill ─────────────────────────────────

def test_raw_live_fallback_fires_when_dose_underfilled(db, monkeypatch):
    """Warehouse upserts fine (stored > 0) but its re-select surfaces nothing —
    the old `stored == 0` gate delivered ZERO paid live finds in that case."""
    prefix = f"{_PFX}fallb"
    org, proj = _mk_org_project(db, prefix, f"{prefix}-niche", "Томск")
    monkeypatch.setattr(cw, "search_warehouse", lambda *a, **k: [])  # warehouse is blind
    monkeypatch.setattr(
        jobs_mod, "search_leads",
        lambda *a, **k: [_cand(company=f"{prefix} {i}", domain=f"{prefix}{i}.ru", city="Томск",
                               phone="+7 2", source="2gis") for i in range(5)],
    )
    try:
        job = _run_collect(db, org, proj, 5)
        assert job.added_count == 5, "under-filled dose must fall back to the raw live rows"
    finally:
        _cleanup(db, org, proj)


def test_web_rows_get_city_backfilled_for_specific_geo(db, monkeypatch):
    prefix = f"{_PFX}webgeo"
    org, proj = _mk_org_project(db, prefix, f"{prefix}-niche", "Томск")
    monkeypatch.setattr(
        jobs_mod, "search_leads",
        lambda *a, **k: [_cand(company=f"{prefix} Web {i}", domain=f"{prefix}w{i}.ru",
                               website=f"https://{prefix}w{i}.ru", city="", source="searxng")
                         for i in range(3)],
    )
    try:
        job = _run_collect(db, org, proj, 3)
        assert job.added_count == 3, "web rows must reach the customer via the geo re-select"
        rows = db.execute(
            select(Company).where(Company.dedup_key.like(f"{prefix}w%.ru"))
        ).scalars().all()
        assert len(rows) == 3
        assert all(r.city == "Томск" for r in rows), \
            "empty city on web rows must be backfilled with the project geo"
    finally:
        _cleanup(db, org, proj)


def test_web_rows_not_backfilled_for_nationwide_geo(db, monkeypatch):
    prefix = f"{_PFX}webnat"
    org, proj = _mk_org_project(db, prefix, f"{prefix}-niche", "Россия")
    monkeypatch.setattr(
        jobs_mod, "search_leads",
        lambda *a, **k: [_cand(company=f"{prefix} Web {i}", domain=f"{prefix}n{i}.ru",
                               website=f"https://{prefix}n{i}.ru", city="", source="searxng")
                         for i in range(2)],
    )
    try:
        job = _run_collect(db, org, proj, 2)
        assert job.added_count == 2
        rows = db.execute(
            select(Company).where(Company.dedup_key.like(f"{prefix}n%.ru"))
        ).scalars().all()
        assert all((r.city or "") == "" for r in rows), \
            "nationwide geo must NOT be stamped as a city"
    finally:
        _cleanup(db, org, proj)


# ── FIX 2: dose passes the LLM filter, top-up refills it ─────────────────────

def test_dose_filtered_and_topped_up_from_warehouse(db, monkeypatch):
    prefix = f"{_PFX}flt"
    niche = f"{prefix}-niche"
    org, proj = _mk_org_project(db, prefix, niche, "Томск")
    # 3 competitors ranked on top + 5 good rows below.
    cw.upsert_companies(
        db,
        [_cand(company=f"{prefix} seller {i}", domain=f"{prefix}s{i}.ru", city="Томск",
               phone="+7 3", source="2gis", score=90 - i) for i in range(3)]
        + [_cand(company=f"{prefix} buyer {i}", domain=f"{prefix}b{i}.ru", city="Томск",
                 phone="+7 4", source="2gis", score=50 - i) for i in range(5)],
        niche=niche,
    )
    fcalls = {"n": 0}

    def fake_filter(cands, *a, **k):
        fcalls["n"] += 1
        return [c for c in cands if "seller" not in (c.get("company") or "")]

    monkeypatch.setattr(jobs_mod, "filter_candidates_llm", fake_filter)
    monkeypatch.setattr(jobs_mod, "search_leads", lambda *a, **k: [])
    try:
        job = _run_collect(db, org, proj, 5)
        assert fcalls["n"] >= 2, "initial dose AND the top-up must both be filtered"
        assert job.added_count == 5, "dose topped back up to batch_size after the filter"
        companies = [l.company for l in db.execute(
            select(Lead).where(Lead.project_id == proj.id)).scalars()]
        assert len(companies) == 5
        assert all("seller" not in c for c in companies), \
            "no competitor may reach the project from the warehouse dose"
    finally:
        _cleanup(db, org, proj)


# ── FIX 7: enhancer fallback is used once, never cached ──────────────────────

def test_fallback_enhancer_terms_used_once_not_cached(db, monkeypatch):
    import app.services.prompt_enhancer as pe

    prefix = f"{_PFX}fb"
    org, proj = _mk_org_project(db, prefix, f"{prefix}-raw", "Томск")
    proj.prompt = "нужны автосервисы Томска"
    db.commit()
    n = {"enh": 0}

    def fake_enhance(prompt, *, organization_id=None):
        n["enh"] += 1
        return {"search_queries_niche": f"{prefix}-fbq", "source": "fallback"}

    monkeypatch.setattr(pe, "enhance_prompt", fake_enhance)
    seen = {}

    def fake_search(*a, **k):
        seen["niche"] = k.get("niche")
        return [_cand(company=f"{prefix} {i}", domain=f"{prefix}{i}.ru", city="Томск",
                      phone="+7 5", source="2gis") for i in range(5)]

    monkeypatch.setattr(jobs_mod, "search_leads", fake_search)
    try:
        _run_collect(db, org, proj, 3)
        assert seen["niche"] == f"{prefix}-fbq", "fallback terms ARE used for this run"
        assert (db.get(Project, proj.id).search_query or "").strip() == "", \
            "fallback terms must NOT be cached on the project"
        _run_collect(db, org, proj, 3)
        assert n["enh"] == 2, "next run re-enhances (cache still empty) instead of being locked"
    finally:
        _cleanup(db, org, proj)


# ── FIX 8: quota clamp + per-chunk charging ──────────────────────────────────

def test_dose_clamped_to_remaining_quota(db, monkeypatch):
    prefix = f"{_PFX}clamp"
    org, proj = _mk_org_project(db, prefix, f"{prefix}-niche", "Томск")
    org.leads_limit_per_month = 10
    org.leads_used_current_month = 7  # 3 remaining
    db.commit()
    monkeypatch.setattr(
        jobs_mod, "search_leads",
        lambda *a, **k: [_cand(company=f"{prefix} {i}", domain=f"{prefix}{i}.ru", city="Томск",
                               phone="+7 6", source="2gis") for i in range(10)],
    )
    try:
        job = _run_collect(db, org, proj, 10)
        assert job.added_count == 3, "selection must be clamped to the remaining quota"
        assert db.get(Organization, org.id).leads_used_current_month == 10
    finally:
        _cleanup(db, org, proj)


def test_usage_charged_exactly_once_across_chunks(db, monkeypatch):
    """25 leads = two full chunk commits + a tail: usage must equal added (no
    double charge from the per-chunk + final-tail accounting), and auto-enrich
    must receive the exact new lead ids."""
    prefix = f"{_PFX}chunk"
    org, proj = _mk_org_project(db, prefix, f"{prefix}-niche", "Томск")
    monkeypatch.setattr(
        jobs_mod, "search_leads",
        lambda *a, **k: [_cand(company=f"{prefix} {i}", domain=f"{prefix}{i}.ru", city="Томск",
                               phone="+7 7", source="2gis") for i in range(30)],
    )
    delay_args = {}
    monkeypatch.setattr(jobs_mod.enrich_leads_task, "delay",
                        lambda *a, **k: delay_args.setdefault("a", a))
    try:
        job = _run_collect(db, org, proj, 25)
        assert job.added_count == 25
        assert db.get(Organization, org.id).leads_used_current_month == 25, \
            "per-chunk + tail charging must add up to exactly `added`"
        lead_ids = {str(l.id) for l in db.execute(
            select(Lead).where(Lead.project_id == proj.id)).scalars()}
        assert "a" in delay_args, "auto-enrich must be queued"
        assert set(delay_args["a"][1]) == lead_ids, \
            "auto-enrich must receive the exact ids collected this run"
    finally:
        _cleanup(db, org, proj)


# ── FIX 9: reaper-failed jobs stay failed ────────────────────────────────────

def test_reaper_failed_job_not_resurrected_to_done(db, monkeypatch):
    prefix = f"{_PFX}reap"
    org, proj = _mk_org_project(db, prefix, f"{prefix}-niche", "Томск")
    jid_holder = {}

    def fake_search_leads(*a, **k):
        # Simulate periodic.health_check reaping the job mid-run (no heartbeat).
        s = SessionLocal()
        try:
            s.execute(
                update(CollectionJob)
                .where(CollectionJob.id == uuid.UUID(jid_holder["id"]))
                .values(status=JobStatus.failed, error="reaped-by-test")
            )
            s.commit()
        finally:
            s.close()
        return [_cand(company=f"{prefix} {i}", domain=f"{prefix}{i}.ru", city="Томск",
                      phone="+7 8", source="2gis") for i in range(12)]

    monkeypatch.setattr(jobs_mod, "search_leads", fake_search_leads)
    job = CollectionJob(organization_id=org.id, project_id=proj.id,
                        status=JobStatus.queued, kind="collect", requested_limit=12)
    db.add(job)
    db.commit()
    jid_holder["id"] = str(job.id)
    try:
        jobs_mod.collect_leads_task(jid_holder["id"])
        db.expire_all()
        job = db.get(CollectionJob, uuid.UUID(jid_holder["id"]))
        assert job.status == JobStatus.failed, "must not overwrite a reaper-failed job to done"
        assert job.error == "reaped-by-test", "the reaper's error message must survive"
        assert job.added_count == 12, "the work that DID happen is still recorded"
        assert db.get(Organization, org.id).leads_used_current_month == 12
        enrich_jobs = db.execute(
            select(CollectionJob).where(
                CollectionJob.project_id == proj.id, CollectionJob.kind == "enrich")
        ).scalars().all()
        assert enrich_jobs == [], "no auto-enrich for a job the reaper already failed"
    finally:
        _cleanup(db, org, proj)


def test_running_transition_bumps_heartbeat(db, monkeypatch):
    prefix = f"{_PFX}heart"
    org, proj = _mk_org_project(db, prefix, f"{prefix}-niche", "Томск")
    observed = {}

    def fake_search_leads(*a, **k):
        s = SessionLocal()
        try:
            row = s.get(CollectionJob, uuid.UUID(observed["id"]))
            observed["status"] = row.status
            observed["updated_at"] = row.updated_at
        finally:
            s.close()
        return []

    monkeypatch.setattr(jobs_mod, "search_leads", fake_search_leads)
    stale = datetime.now(timezone.utc) - timedelta(hours=2)
    job = CollectionJob(organization_id=org.id, project_id=proj.id,
                        status=JobStatus.queued, kind="collect", requested_limit=5,
                        created_at=stale, updated_at=stale)
    db.add(job)
    db.commit()
    observed["id"] = str(job.id)
    try:
        jobs_mod.collect_leads_task(observed["id"])
        assert observed["status"] == JobStatus.running
        age = datetime.now(timezone.utc) - observed["updated_at"].replace(tzinfo=timezone.utc)
        assert age < timedelta(minutes=5), \
            "updated_at must be bumped on queued→running or the reaper kills live jobs"
    finally:
        _cleanup(db, org, proj)


# ── FIX 6: enrich ordering ───────────────────────────────────────────────────

def test_enrich_processes_never_enriched_newest_first(db, monkeypatch):
    prefix = f"{_PFX}enrord"
    org, proj = _mk_org_project(db, prefix, f"{prefix}-niche", "Томск")
    now = datetime.now(timezone.utc)
    old = Lead(  # already enriched, still contactless — eligible forever
        organization_id=org.id, project_id=proj.id, company=f"{prefix} old",
        city="Томск", website=f"https://{prefix}old.ru", domain=f"{prefix}old.ru",
        email="", phone="", source="searxng", status=LeadStatus.new,
        enriched=True, created_at=now - timedelta(days=10),
    )
    fresh = [
        Lead(
            organization_id=org.id, project_id=proj.id, company=f"{prefix} fresh {i}",
            city="Томск", website=f"https://{prefix}f{i}.ru", domain=f"{prefix}f{i}.ru",
            email="", phone="", source="searxng", status=LeadStatus.new,
            enriched=False, created_at=now - timedelta(minutes=i),
        )
        for i in range(2)
    ]
    db.add_all([old] + fresh)
    db.commit()
    processed: list[str] = []

    def fake_enrich_site(website):
        processed.append(website)
        return {"emails": [], "phones": ["+7 999 000"], "addresses": []}

    monkeypatch.setattr(jobs_mod, "enrich_website_contacts", fake_enrich_site)
    monkeypatch.setattr(jobs_mod, "enrich_2gis_lead",
                        lambda *a, **k: {"emails": [], "phones": [], "addresses": []})
    job = CollectionJob(organization_id=org.id, project_id=proj.id,
                        status=JobStatus.queued, kind="enrich", requested_limit=2)
    db.add(job)
    db.commit()
    try:
        jobs_mod.enrich_leads_task(str(job.id))
        db.expire_all()
        assert set(processed) == {f"https://{prefix}f0.ru", f"https://{prefix}f1.ru"}, \
            "never-enriched newest leads go first; the stale contactless one must not monopolize the run"
        assert db.get(CollectionJob, job.id).status == JobStatus.done
    finally:
        _cleanup(db, org, proj)
