"""Reference E2E: the core money path, end to end through real HTTP + auth + DB.

register → upgrade → create project → collect (eager Celery + stubbed sources)
→ leads land scored → list/filter → lead detail → call journal → CSV export.

This is the proven pattern every other E2E module follows.
"""
from __future__ import annotations


def test_full_collection_to_export_journey(paid_account, stub_sources, new_project):
    acct = paid_account

    # 1. Create a project.
    project = new_project(acct, niche="стоматология", geography="Москва")
    pid = project["id"]
    assert project["niche"] == "стоматология"

    # 2. Collect a dose — runs the real task synchronously (eager Celery).
    collect = acct.post(f"/api/leads/project/{pid}/collect", json={"lead_limit": 10})
    assert collect.status_code in (200, 201), collect.text
    job = collect.json()
    assert job["kind"] == "collect"
    # Eager → the job has already run to completion by the time we get here.
    assert job["status"] in ("done", "running", "queued")

    # 3. Job history shows a finished collect that added leads.
    jobs = acct.get(f"/api/leads/jobs/project/{pid}")
    assert jobs.status_code == 200, jobs.text
    assert any(j["kind"] == "collect" for j in jobs.json())
    done = [j for j in jobs.json() if j["kind"] == "collect"][0]
    assert done["status"] == "done", f"collect did not finish: {done}"
    assert done["added_count"] >= 1, f"no leads added: {done}"

    # 4. Leads landed, are org-scoped, scored, and carry the stubbed phone.
    table = acct.get(f"/api/leads/project/{pid}/table?page=1&per_page=50")
    assert table.status_code == 200, table.text
    body = table.json()
    assert body["total"] >= 1
    lead = body["items"][0]
    assert lead["score"] > 0, "lead must be scored"
    assert lead["phone"], "stubbed phone should be saved"
    lead_id = lead["id"]

    # 5. Filter by has_phone — every stub lead has a phone, so count is stable.
    filtered = acct.get(f"/api/leads/project/{pid}/table?has_phone=true&per_page=50")
    assert filtered.status_code == 200
    assert filtered.json()["total"] == body["total"]

    # 6. Lead detail (full record + warehouse cross-ref).
    detail = acct.get(f"/api/leads/{lead_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["id"] == lead_id

    # 7. Call journal: record a call (attributed to the caller) + read it back.
    call = acct.post(f"/api/leads/{lead_id}/calls",
                     json={"comment": "Дозвонился, ЛПР перезвонит"})
    assert call.status_code == 201, call.text
    assert call.json()["user_name"] == acct.full_name
    calls = acct.get(f"/api/leads/{lead_id}/calls")
    assert calls.status_code == 200
    assert len(calls.json()) == 1
    # The call moved a "new" lead to "contacted".
    assert acct.get(f"/api/leads/{lead_id}").json()["status"] == "contacted"

    # 8. CSV export returns the collected leads.
    export = acct.get(f"/api/leads/project/{pid}/export")
    assert export.status_code == 200, export.text
    assert "text/csv" in export.headers.get("content-type", "")
    csv_text = export.text
    assert lead["company"].split()[0] in csv_text  # niche word present in dump


def test_collect_delivers_full_dose_and_autoenrich_fills_email(paid_account, stub_sources, new_project):
    """A 10-dose from 12 distinct candidates delivers ~10 leads (not 1 — guards
    the base-domain dedup-collapse regression), and auto-enrich (eager, fired
    after collect) fills emails without an explicit enrich call."""
    acct = paid_account
    project = new_project(acct)
    pid = project["id"]

    acct.post(f"/api/leads/project/{pid}/collect", json={"lead_limit": 10})
    table = acct.get(f"/api/leads/project/{pid}/table?per_page=50").json()
    assert table["total"] >= 8, f"dose should deliver ~10 distinct leads, got {table['total']}"

    # Auto-enrichment runs right after collect (eager) → emails get filled.
    with_email = acct.get(f"/api/leads/project/{pid}/table?has_email=true&per_page=50").json()
    assert with_email["total"] >= 1, "auto-enrich should fill at least one email (info@domain)"

    # An explicit enrich pass is accepted; 400 is also valid here since
    # auto-enrich already processed every lead ("Нет лидов для обогащения").
    enrich = acct.post(f"/api/leads/project/{pid}/enrich", json={"lead_limit": 50})
    assert enrich.status_code in (200, 201, 400), enrich.text


def test_collection_blocked_on_free_quota(make_account, stub_sources, new_project, db):
    """A free org (0-lead quota) must be refused at collect, not silently no-op."""
    acct = make_account()  # free plan: триал 13.07 — 10 разовых лидов
    project = new_project(acct)
    pid = project["id"]
    # Триал: первый сбор РАЗРЕШЁН. Исчерпываем его и проверяем блок.
    r = acct.post(f"/api/leads/project/{pid}/collect", json={"lead_limit": 10})
    assert r.status_code in (200, 201), f"trial collect must run, got {r.status_code}: {r.text}"
    from app.models import Organization as _Org
    _org = db.get(_Org, acct.org_id)
    _org.leads_used_current_month = _org.leads_limit_per_month
    db.commit()
    r = acct.post(f"/api/leads/project/{pid}/collect", json={"lead_limit": 10})
    assert r.status_code in (402, 429), f"exhausted trial should be quota-blocked, got {r.status_code}"
