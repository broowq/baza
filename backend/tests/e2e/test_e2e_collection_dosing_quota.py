"""TRUE E2E: collection dosing + no-repeat + monthly lead quota.

Drives the real app in-process (TestClient + real auth + real Postgres +
eager Celery + stubbed sources via the `stub_sources` seam). Every test
asserts real behavior end to end: HTTP status AND the persisted DB / response
state, not just 200.

Covered:
  * a collect delivers a FULL dose of DISTINCT companies (no base-domain
    dedup-collapse) and the job's found/added counts reflect what landed;
  * a SECOND collect on the same project does NOT re-deliver the same
    companies — the leads table has zero duplicate domains;
  * monthly lead quota: a sub-quota dose is clamped to the remaining quota
    and burns it; a dose that exceeds remaining quota is refused at the API
    (429) and a fully-exhausted org is refused (402) — never silently no-op;
  * auto-enrich fires after collect (emails get filled, no manual enrich);
  * the concurrent-collect 409 guard (best-effort under eager Celery).

Domain refs: app/api/routes/leads.py (run_collection / ensure_lead_quota /
MAX_CONCURRENT_JOBS_PER_ORG) and app/tasks/jobs.py (collect_leads_task dosing,
_project_dedup_keys, per-chunk quota booking).
"""
from __future__ import annotations

import uuid

from sqlalchemy import func, select

from app.models import CollectionJob, JobStatus, Lead, Organization
from app.utils.url_tools import get_base_domain


# ── helpers ─────────────────────────────────────────────────────────────────

def _unique_niche() -> str:
    """A niche string unique to ONE test.

    The company warehouse is shared across orgs/projects and matched by
    niche/geography ILIKE — so two tests using the same niche ("стоматология")
    pollute each other's candidate pool (a later test's warehouse-first select
    surfaces companies seeded by an earlier test). A unique niche per test
    isolates the pool to exactly this test's stubbed candidates, making the
    "bounded by stub n" / no-repeat assertions deterministic.
    """
    return f"e2eниша{uuid.uuid4().hex[:8]}"


def _collect(acct, pid, limit=10):
    return acct.post(f"/api/leads/project/{pid}/collect", json={"lead_limit": limit})


def _done_collect_jobs(acct, pid):
    jobs = acct.get(f"/api/leads/jobs/project/{pid}")
    assert jobs.status_code == 200, jobs.text
    return [j for j in jobs.json() if j["kind"] == "collect"]


def _leads_in_project(db, pid):
    return db.execute(select(Lead).where(Lead.project_id == pid)).scalars().all()


def _org_row(db, org_id) -> Organization:
    return db.get(Organization, org_id)


# ── full dose of DISTINCT companies ─────────────────────────────────────────

def test_collect_delivers_full_dose_of_distinct_leads(paid_account, stub_sources, new_project, db):
    """12 distinct stub candidates, dose=10 → ~10 DISTINCT companies land.

    Guards the base-domain dedup-collapse regression (one lead delivered when
    many candidates share a registrable base). We assert: the job finished
    'done' with added_count matching the persisted rows, and every persisted
    lead has a UNIQUE base domain.
    """
    stub_sources["n"] = 12
    acct = paid_account
    pid = new_project(acct, niche=_unique_niche(), geography="Москва")["id"]

    r = _collect(acct, pid, limit=10)
    assert r.status_code in (200, 201), r.text
    job = r.json()
    assert job["kind"] == "collect"

    done = _done_collect_jobs(acct, pid)
    assert len(done) == 1
    j = done[0]
    assert j["status"] == "done", f"collect did not finish: {j}"
    # dose=10 from 12 distinct, saveable candidates → close to 10.
    assert j["added_count"] >= 8, f"dose under-delivered: {j}"
    assert j["found_count"] >= j["added_count"], j  # found is the assembled dose

    # added_count must equal the rows actually persisted (no phantom counting).
    rows = _leads_in_project(db, pid)
    assert len(rows) == j["added_count"], (
        f"job.added_count={j['added_count']} != persisted leads={len(rows)}"
    )
    assert len(rows) >= 8

    # Every delivered company is DISTINCT by base domain (the dedup-collapse
    # regression would leave exactly 1 lead here).
    base_domains = [get_base_domain(l.domain) for l in rows if l.domain]
    assert len(base_domains) == len(rows), "some leads have no domain"
    assert len(set(base_domains)) == len(base_domains), (
        f"dose collapsed to non-distinct domains: {sorted(base_domains)}"
    )

    # Each carries the stubbed phone (real save loop ran).
    assert all(l.phone for l in rows), "stub phone should be persisted on every lead"

    # Quota usage was booked for exactly the leads added.
    org = _org_row(db, acct.org_id)
    assert org.leads_used_current_month == j["added_count"], (
        f"usage {org.leads_used_current_month} != added {j['added_count']}"
    )


# ── second collect does NOT re-deliver the same companies ────────────────────

def test_second_collect_does_not_redeliver_same_companies(paid_account, stub_sources, new_project, db):
    """Re-running collect on the same project must bring NEW businesses only.

    With 12 distinct stub candidates and dose=10, the first run takes ~10 and
    the second can only deliver the remaining ~2 (the dedup-by-project key set
    excludes what's already collected). Critically: the leads table must have
    ZERO duplicate domains across both runs.
    """
    stub_sources["n"] = 12
    acct = paid_account
    # Unique niche → the warehouse-first select can only surface THIS test's
    # 12 stub companies, so the pool is bounded and the no-repeat math is exact.
    pid = new_project(acct, niche=_unique_niche())["id"]

    r1 = _collect(acct, pid, limit=10)
    assert r1.status_code in (200, 201), r1.text
    first_rows = _leads_in_project(db, pid)
    first_count = len(first_rows)
    assert first_count >= 8, f"first dose too small: {first_count}"
    first_domains = {l.domain for l in first_rows}

    # Second collect — same project, same stub catalogue (12 distinct total).
    r2 = _collect(acct, pid, limit=10)
    assert r2.status_code in (200, 201), r2.text

    all_rows = _leads_in_project(db, pid)
    # The pool of distinct stub companies is 12 → total can never exceed that.
    assert len(all_rows) <= stub_sources["n"], (
        f"delivered {len(all_rows)} leads from a {stub_sources['n']}-company pool — "
        "second run re-delivered already-collected companies"
    )
    # The second run added only NEW domains (the deficit), never repeats.
    assert len(all_rows) > first_count, "second collect should top up with new companies"

    # THE no-duplicate assertion: zero duplicate domains in the leads table.
    domains = [l.domain for l in all_rows]
    assert len(domains) == len(set(domains)), (
        f"duplicate domains delivered across two collects: "
        f"{[d for d in domains if domains.count(d) > 1]}"
    )
    # And base-domain dedup holds too (covers www./subdomain collapse rules).
    base_domains = [get_base_domain(l.domain) for l in all_rows]
    assert len(base_domains) == len(set(base_domains)), "duplicate base domains across runs"

    # The new run's companies are a strict superset including brand-new ones.
    new_domains = {l.domain for l in all_rows} - first_domains
    second_added = _done_collect_jobs(acct, pid)
    second_added.sort(key=lambda j: j["created_at"])
    assert second_added[-1]["added_count"] == len(new_domains), (
        f"second job added_count={second_added[-1]['added_count']} != "
        f"newly-seen domains={len(new_domains)}"
    )


def test_exhausting_the_pool_reports_all_collected(paid_account, stub_sources, new_project, db):
    """Once every distinct stub company is collected, a further collect adds 0
    and the job reports it honestly (not a crash, not a silent success)."""
    stub_sources["n"] = 6
    acct = paid_account
    pid = new_project(acct, niche=_unique_niche())["id"]

    # First dose drains the whole 6-company pool (dose=10 > 6).
    assert _collect(acct, pid, limit=10).status_code in (200, 201)
    drained = _leads_in_project(db, pid)
    assert len(drained) == 6, f"expected the full pool of 6, got {len(drained)}"

    # Second collect: nothing new remains → added 0, status done, honest error.
    assert _collect(acct, pid, limit=10).status_code in (200, 201)
    assert len(_leads_in_project(db, pid)) == 6, "no new companies should appear"

    jobs = sorted(_done_collect_jobs(acct, pid), key=lambda j: j["created_at"])
    last = jobs[-1]
    assert last["status"] == "done", last
    assert last["added_count"] == 0, last
    # The task sets a "всё доступное уже собрано" message when live returned
    # rows but nothing new could be added.
    assert last["error"], "an exhausted run should carry an explanatory message"
    assert "собран" in last["error"].lower() or "источник" in last["error"].lower(), last["error"]


# ── monthly lead quota ──────────────────────────────────────────────────────

def test_quota_clamps_dose_to_remaining_and_blocks_further(paid_account, stub_sources, new_project, db):
    """leads_limit_per_month low (3): a dose WITHIN the quota delivers up to the
    remaining quota and burns it; a follow-up collect is then quota-blocked.

    NOTE on the API pre-check: ensure_lead_quota refuses (429) when
    used+dose > limit. So to exercise the *clamp* (deliver only the remaining),
    the requested dose must be <= remaining. We request dose=3 == remaining.
    """
    stub_sources["n"] = 12
    acct = paid_account
    pid = new_project(acct)["id"]

    # Force a tiny monthly quota directly in the DB.
    org = _org_row(db, acct.org_id)
    org.leads_limit_per_month = 3
    org.leads_used_current_month = 0
    db.commit()

    # Dose == remaining quota (3) → passes the API pre-check, delivers exactly 3.
    r = _collect(acct, pid, limit=3)
    assert r.status_code in (200, 201), r.text
    rows = _leads_in_project(db, pid)
    assert len(rows) == 3, f"dose should be clamped/served to the 3-lead quota, got {len(rows)}"

    db.expire_all()
    org = _org_row(db, acct.org_id)
    assert org.leads_used_current_month == 3, f"usage should now equal the cap: {org.leads_used_current_month}"

    # Quota is now fully consumed → a further collect of ANY size is refused.
    blocked = _collect(acct, pid, limit=1)
    assert blocked.status_code == 402, (
        f"exhausted-quota collect should be 402, got {blocked.status_code}: {blocked.text}"
    )
    assert "квот" in blocked.json()["detail"].lower()
    # And no extra leads slipped in.
    assert len(_leads_in_project(db, pid)) == 3


def test_collect_exceeding_remaining_quota_is_refused_429(paid_account, stub_sources, new_project, db):
    """A dose LARGER than the remaining quota is refused up-front (429) by the
    API quota pre-check — the job never runs and no leads are created."""
    stub_sources["n"] = 12
    acct = paid_account
    pid = new_project(acct)["id"]

    org = _org_row(db, acct.org_id)
    org.leads_limit_per_month = 3
    org.leads_used_current_month = 0
    db.commit()

    # dose=10 > remaining=3 → 429, refused before any job is queued.
    r = _collect(acct, pid, limit=10)
    assert r.status_code == 429, f"over-quota collect should be 429, got {r.status_code}: {r.text}"
    assert "квот" in r.json()["detail"].lower()

    # Nothing was collected and no collect job was even created.
    assert _leads_in_project(db, pid) == []
    assert _done_collect_jobs(acct, pid) == [], "no job should be queued on a 429 quota refusal"

    db.expire_all()
    assert _org_row(db, acct.org_id).leads_used_current_month == 0, "usage must stay at 0"


def test_partial_remaining_quota_serves_only_the_remainder(paid_account, stub_sources, new_project, db):
    """With some quota already used, a dose == the *remaining* slots delivers
    exactly that many — the per-chunk SELECT FOR UPDATE booking respects the
    cap precisely, never over-delivering."""
    stub_sources["n"] = 12
    acct = paid_account
    pid = new_project(acct)["id"]

    org = _org_row(db, acct.org_id)
    org.leads_limit_per_month = 5
    org.leads_used_current_month = 3  # 2 remaining
    db.commit()

    # Request exactly the 2 remaining → passes the pre-check, delivers 2.
    r = _collect(acct, pid, limit=2)
    assert r.status_code in (200, 201), r.text
    rows = _leads_in_project(db, pid)
    assert len(rows) == 2, f"only the 2 remaining slots should be served, got {len(rows)}"

    db.expire_all()
    org = _org_row(db, acct.org_id)
    assert org.leads_used_current_month == 5, f"usage should hit the cap exactly: {org.leads_used_current_month}"
    # Cap reached → next collect refused.
    assert _collect(acct, pid, limit=1).status_code == 402


def test_free_org_collect_is_quota_blocked(make_account, stub_sources, new_project, db):
    """A free org (0-lead quota) is refused at collect (402) and no job runs."""
    acct = make_account()  # free plan, leads_limit_per_month = 0
    pid = new_project(acct)["id"]

    r = _collect(acct, pid, limit=10)
    assert r.status_code == 402, f"free org should be 402-blocked, got {r.status_code}: {r.text}"
    assert "квот" in r.json()["detail"].lower()
    assert _leads_in_project(db, pid) == []
    assert _done_collect_jobs(acct, pid) == []


# ── auto-enrich fires after collect ─────────────────────────────────────────

def test_autoenrich_fires_after_collect_and_fills_emails(paid_account, stub_sources, new_project, db):
    """No explicit enrich call: collect → auto-enrich (eager) → emails filled.

    Stub leads arrive with a phone but NO email; the auto-enrich step (queued
    inside collect_leads_task, run synchronously by eager Celery) scrapes
    info@domain. Assert via HTTP filter AND the persisted rows.
    """
    stub_sources["n"] = 10
    acct = paid_account
    pid = new_project(acct)["id"]

    r = _collect(acct, pid, limit=10)
    assert r.status_code in (200, 201), r.text

    # An auto-enrich job was created and finished, distinct from the collect.
    all_jobs = acct.get(f"/api/leads/jobs/project/{pid}").json()
    enrich_jobs = [j for j in all_jobs if j["kind"] == "enrich"]
    assert enrich_jobs, "collect should auto-queue an enrich job"
    assert all(j["status"] == "done" for j in enrich_jobs), enrich_jobs
    assert any(j["enriched_count"] >= 1 for j in enrich_jobs), "auto-enrich enriched nothing"

    # Emails are now filled (fake_enrich_web → info@<domain>).
    with_email = acct.get(f"/api/leads/project/{pid}/table?has_email=true&per_page=50").json()
    assert with_email["total"] >= 1, "auto-enrich should fill at least one email"

    rows = _leads_in_project(db, pid)
    enriched_rows = [l for l in rows if l.enriched]
    assert enriched_rows, "leads should be flagged enriched after auto-enrich"
    info_emails = [l.email for l in rows if l.email.startswith("info@")]
    assert info_emails, f"auto-enrich should set info@domain emails, got {[l.email for l in rows]}"
    # The filled email matches the lead's own domain (info@<lead.domain>).
    for l in enriched_rows:
        if l.email and l.domain:
            assert l.email == f"info@{l.domain}", f"email/domain mismatch: {l.email} vs {l.domain}"


# ── concurrent-collect 409 guard (best-effort under eager Celery) ───────────

def test_concurrent_collect_409_guard(paid_account, stub_sources, new_project, db):
    """The API refuses a 2nd collect while one is queued/running for the same
    project (409). Under eager Celery the first collect runs to completion
    synchronously inside the POST, so by the time the 2nd POST lands there is
    no active job to collide with — the guard cannot be hit through the HTTP
    path here. We assert the guard's *precondition* deterministically instead:
    inserting a queued collect job directly, then a real collect POST must 409.
    """
    acct = paid_account
    pid = new_project(acct)["id"]

    # Simulate an in-flight collect by inserting a queued job (what .delay()
    # would have created) WITHOUT running the task — mirrors a real worker that
    # hasn't picked the job up yet.
    stuck = CollectionJob(
        organization_id=acct.org_id,
        project_id=pid,
        status=JobStatus.queued,
        kind="collect",
        requested_limit=10,
    )
    db.add(stuck)
    db.commit()

    try:
        r = _collect(acct, pid, limit=10)
        assert r.status_code == 409, (
            f"a 2nd collect with one already queued must 409, got {r.status_code}: {r.text}"
        )
        assert "уже запущен" in r.json()["detail"].lower()
        # The guard must not have created a competing collect job.
        active = db.scalar(
            select(func.count(CollectionJob.id)).where(
                CollectionJob.project_id == pid,
                CollectionJob.kind == "collect",
                CollectionJob.status.in_([JobStatus.queued, JobStatus.running]),
            )
        )
        assert active == 1, f"409 path must not queue a second collect job (active={active})"
    finally:
        # Release the stub so fixture teardown / nothing else hangs on it.
        db.delete(stuck)
        db.commit()
