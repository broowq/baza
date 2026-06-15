"""TRUE end-to-end tests for the CRM layer (built on top of the existing
data model + shared crm service). Drives the real FastAPI app via the e2e
harness (real auth → DB), with collection stubbed at the jobs.py seam.

Covers the CRM API spec:
  - GET  /api/crm/pipeline                      → 6 ordered stages new..rejected
  - PATCH /api/leads/{id} status                → persists + stage_changed activity
  - PATCH /api/leads/{id} assigned_to_user_id   → assign / unassign / 422 non-member
  - deal_value + expected_close_at persist; funnel reflects counts/value/won_value
  - GET  /api/crm/project/{pid}/funnel
  - GET  /api/crm/leads/{id}/activities         → merged timeline, newest first
  - Tasks: POST/GET/PATCH/DELETE under /api/crm; scope=open / scope=overdue
  - Cross-org task access → 404
  - Bulk: POST /api/leads/project/{pid}/bulk  (stage / assign / add_tag) + isolation

These routes are landed in parallel by sibling agents; the tests are written
strictly to the spec and go green once the routes exist.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone


# ── shared helpers ───────────────────────────────────────────────────────────

def _collect_leads(acct, new_project, *, niche, geography="Москва", n=12, limit=10):
    """Create a project under a UNIQUE niche and collect a dose of leads.

    Returns (project_id, [lead, ...]) — leads are the table rows, score-sorted.
    The warehouse is shared across the test session, so each test that cares
    about pool isolation must pass its own niche (see the dosing test note).
    """
    project = new_project(acct, niche=niche, geography=geography)
    pid = project["id"]
    r = acct.post(f"/api/leads/project/{pid}/collect", json={"lead_limit": limit})
    assert r.status_code in (200, 201), r.text
    table = acct.get(f"/api/leads/project/{pid}/table?per_page=50")
    assert table.status_code == 200, table.text
    items = table.json()["items"]
    assert items, f"collect delivered no leads: {table.json()}"
    return pid, items


def _my_user_id(acct) -> str:
    r = acct.get("/api/auth/me")
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _niche() -> str:
    """A niche unique to this collect so warehouse pool isolation holds."""
    return f"crmниша{uuid.uuid4().hex[:8]}"


# ── pipeline definition ──────────────────────────────────────────────────────

def test_pipeline_returns_six_ordered_stages(paid_account):
    r = paid_account.get("/api/crm/pipeline")
    assert r.status_code == 200, r.text
    body = r.json()
    stages = body["stages"] if isinstance(body, dict) else body
    keys = [s["key"] for s in stages]
    assert keys == ["new", "contacted", "qualified", "proposal", "won", "rejected"], keys
    by_key = {s["key"]: s for s in stages}
    # Terminal/won flags as defined in app.services.crm.PIPELINE_STAGES.
    assert by_key["won"]["terminal"] is True and by_key["won"]["won"] is True
    assert by_key["rejected"]["terminal"] is True and by_key["rejected"]["won"] is False
    assert by_key["new"]["terminal"] is False
    # Russian labels are exposed for the board headers.
    assert by_key["new"]["label"] == "Новый"
    assert by_key["won"]["label"] == "Сделка"


# ── stage change persists + logs a stage_changed activity ────────────────────

def test_status_change_persists_and_logs_stage_change(paid_account, stub_sources, new_project):
    acct = paid_account
    pid, leads = _collect_leads(acct, new_project, niche=_niche())
    lead_id = leads[0]["id"]

    # new → proposal
    r = acct.patch(f"/api/leads/{lead_id}", json={"status": "proposal"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "proposal"
    assert acct.get(f"/api/leads/{lead_id}").json()["status"] == "proposal"

    # proposal → won
    r = acct.patch(f"/api/leads/{lead_id}", json={"status": "won"})
    assert r.status_code == 200, r.text
    assert acct.get(f"/api/leads/{lead_id}").json()["status"] == "won"

    # Two stage_changed activities recorded, newest first.
    acts = acct.get(f"/api/crm/leads/{lead_id}/activities")
    assert acts.status_code == 200, acts.text
    feed = acts.json()
    stage_events = [a for a in feed if a["kind"] == "stage_changed"]
    assert len(stage_events) >= 2, feed
    # Newest stage change is the move to "won".
    newest = stage_events[0]
    blob = (newest.get("text", "") + str(newest.get("meta", "")))
    assert "won" in blob or "Сделка" in blob, newest


# ── assignment: assign / unassign / non-member 422 ───────────────────────────

def test_assign_unassign_and_non_member_rejected(paid_account, stub_sources, new_project):
    acct = paid_account
    pid, leads = _collect_leads(acct, new_project, niche=_niche())
    lead_id = leads[0]["id"]
    me = _my_user_id(acct)

    # Assign to the owner (a real member of the org).
    r = acct.patch(f"/api/leads/{lead_id}", json={"assigned_to_user_id": me})
    assert r.status_code == 200, r.text
    assert r.json()["assigned_to_user_id"] == me
    # Lead detail reflects the owner.
    assert acct.get(f"/api/leads/{lead_id}").json()["assigned_to_user_id"] == me

    # Filterable by assigned_to=me on the table endpoint.
    mine = acct.get(f"/api/leads/project/{pid}/table?assigned_to=me&per_page=50")
    assert mine.status_code == 200, mine.text
    assert lead_id in [x["id"] for x in mine.json()["items"]]

    # Explicit null unassigns (model_fields_set distinguishes clear from omit).
    r = acct.patch(f"/api/leads/{lead_id}", json={"assigned_to_user_id": None})
    assert r.status_code == 200, r.text
    assert r.json()["assigned_to_user_id"] is None
    assert acct.get(f"/api/leads/{lead_id}").json()["assigned_to_user_id"] is None
    # And it drops out of the "mine" view.
    mine2 = acct.get(f"/api/leads/project/{pid}/table?assigned_to=me&per_page=50")
    assert lead_id not in [x["id"] for x in mine2.json()["items"]]

    # Assigning a non-member uuid is refused (must be a Membership of the org).
    stranger = str(uuid.uuid4())
    r = acct.patch(f"/api/leads/{lead_id}", json={"assigned_to_user_id": stranger})
    assert r.status_code == 422, f"non-member assign must 422, got {r.status_code}: {r.text}"
    # Lead stayed unassigned.
    assert acct.get(f"/api/leads/{lead_id}").json()["assigned_to_user_id"] is None


# ── deal_value + expected_close_at persist; funnel reflects them ─────────────

def test_deal_value_close_date_persist_and_funnel(paid_account, stub_sources, new_project):
    acct = paid_account
    pid, leads = _collect_leads(acct, new_project, niche=_niche())
    assert len(leads) >= 3, f"need a few leads for the funnel, got {len(leads)}"
    a, b, c = leads[0]["id"], leads[1]["id"], leads[2]["id"]

    close = (datetime.now(timezone.utc) + timedelta(days=14)).replace(microsecond=0)
    close_iso = close.isoformat()

    # Lead A: a 500k deal, moved to proposal with an expected close date.
    r = acct.patch(f"/api/leads/{a}", json={
        "deal_value": 500000,
        "expected_close_at": close_iso,
        "status": "proposal",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deal_value"] == 500000
    assert body["expected_close_at"] is not None
    # Round-trips on the detail endpoint too.
    detail = acct.get(f"/api/leads/{a}").json()
    assert detail["deal_value"] == 500000
    assert detail["expected_close_at"][:10] == close_iso[:10]

    # Lead B: a 300k deal still in proposal.
    assert acct.patch(f"/api/leads/{b}", json={"deal_value": 300000, "status": "proposal"}).status_code == 200

    # Funnel BEFORE any win: proposal stage holds both, won_value is 0.
    f1 = acct.get(f"/api/crm/project/{pid}/funnel")
    assert f1.status_code == 200, f1.text
    funnel = f1.json()
    stages = {s["key"]: s for s in funnel["stages"]}
    assert stages["proposal"]["count"] >= 2
    assert stages["proposal"]["value"] >= 800000
    assert funnel["won_value"] == 0
    assert funnel["won_count"] == 0

    # Move lead A to "won" → its deal_value rolls into won_value.
    assert acct.patch(f"/api/leads/{a}", json={"status": "won"}).status_code == 200
    f2 = acct.get(f"/api/crm/project/{pid}/funnel").json()
    stages2 = {s["key"]: s for s in f2["stages"]}
    assert stages2["won"]["count"] >= 1
    assert stages2["won"]["value"] >= 500000
    assert f2["won_value"] >= 500000
    assert f2["won_count"] >= 1
    # Lead A left the proposal bucket.
    assert stages2["proposal"]["count"] >= 1


# ── tasks: create / list / done / scopes / delete ────────────────────────────

def test_task_lifecycle_and_scopes(paid_account, stub_sources, new_project):
    acct = paid_account
    pid, leads = _collect_leads(acct, new_project, niche=_niche())
    lead_id = leads[0]["id"]
    me = _my_user_id(acct)

    # Create a task — default assignee is the current user.
    r = acct.post(f"/api/crm/leads/{lead_id}/tasks", json={"title": "Перезвонить ЛПР"})
    assert r.status_code in (200, 201), r.text
    task = r.json()
    task_id = task["id"]
    assert task["title"] == "Перезвонить ЛПР"
    assert task["done"] is False
    assert task["assigned_to_user_id"] == me, "default assignee must be the creator"

    # Lists on the lead.
    listed = acct.get(f"/api/crm/leads/{lead_id}/tasks")
    assert listed.status_code == 200, listed.text
    assert task_id in [t["id"] for t in listed.json()]

    # Open scope shows the task before it's done.
    open_before = acct.get("/api/crm/tasks?scope=open")
    assert open_before.status_code == 200, open_before.text
    assert task_id in [t["id"] for t in open_before.json()]

    # Mark done → done flag + done_at + a task_done activity on the lead.
    r = acct.patch(f"/api/crm/tasks/{task_id}", json={"done": True})
    assert r.status_code == 200, r.text
    done_task = r.json()
    assert done_task["done"] is True
    assert done_task["done_at"] is not None

    acts = acct.get(f"/api/crm/leads/{lead_id}/activities").json()
    assert any(a["kind"] == "task_done" for a in acts), acts

    # Open scope no longer lists it once done.
    open_after = acct.get("/api/crm/tasks?scope=open").json()
    assert task_id not in [t["id"] for t in open_after]

    # Delete removes it.
    d = acct.delete(f"/api/crm/tasks/{task_id}")
    assert d.status_code in (200, 204), d.text
    after = acct.get(f"/api/crm/leads/{lead_id}/tasks").json()
    assert task_id not in [t["id"] for t in after]


def test_task_overdue_scope(paid_account, stub_sources, new_project, db):
    """A task with a past due_at shows up under scope=overdue."""
    from app.models import LeadTask

    acct = paid_account
    pid, leads = _collect_leads(acct, new_project, niche=_niche())
    lead_id = leads[0]["id"]

    past = (datetime.now(timezone.utc) - timedelta(days=2)).replace(microsecond=0)
    r = acct.post(
        f"/api/crm/leads/{lead_id}/tasks",
        json={"title": "Просроченная задача", "due_at": past.isoformat()},
    )
    assert r.status_code in (200, 201), r.text
    task_id = r.json()["id"]

    overdue = acct.get("/api/crm/tasks?scope=overdue")
    assert overdue.status_code == 200, overdue.text
    assert task_id in [t["id"] for t in overdue.json()], overdue.json()

    # Once done it is no longer overdue.
    assert acct.patch(f"/api/crm/tasks/{task_id}", json={"done": True}).status_code == 200
    overdue2 = acct.get("/api/crm/tasks?scope=overdue").json()
    assert task_id not in [t["id"] for t in overdue2]


def test_cross_org_task_access_is_404(paid_account, make_account, stub_sources, new_project):
    """A task created in org A is invisible (404) to org B."""
    owner = paid_account
    pid, leads = _collect_leads(owner, new_project, niche=_niche())
    lead_id = leads[0]["id"]
    r = owner.post(f"/api/crm/leads/{lead_id}/tasks", json={"title": "Секретная задача"})
    assert r.status_code in (200, 201), r.text
    task_id = r.json()["id"]

    other = make_account(plan="pro")
    # PATCH and DELETE of a foreign task are opaque 404s.
    assert other.patch(f"/api/crm/tasks/{task_id}", json={"done": True}).status_code == 404
    assert other.delete(f"/api/crm/tasks/{task_id}").status_code == 404
    # Foreign lead's tasks are not listable either.
    assert other.get(f"/api/crm/leads/{lead_id}/tasks").status_code == 404


# ── activity timeline merges call notes + stage changes ──────────────────────

def test_activity_timeline_merges_call_and_stage_change(paid_account, stub_sources, new_project):
    acct = paid_account
    pid, leads = _collect_leads(acct, new_project, niche=_niche())
    lead_id = leads[0]["id"]

    # 1) Log a call note (this also bumps new → contacted).
    call = acct.post(f"/api/leads/{lead_id}/calls",
                     json={"comment": "Дозвонился, обсудили КП"})
    assert call.status_code == 201, call.text

    # 2) Then an explicit stage change to qualified.
    assert acct.patch(f"/api/leads/{lead_id}", json={"status": "qualified"}).status_code == 200

    feed = acct.get(f"/api/crm/leads/{lead_id}/activities")
    assert feed.status_code == 200, feed.text
    items = feed.json()
    kinds = [a["kind"] for a in items]
    # Both event families are present in a single merged feed.
    assert any(k == "stage_changed" for k in kinds), kinds
    assert any(k in ("call", "note") for k in kinds), kinds
    # The call comment text surfaces somewhere in the feed.
    assert any("Дозвонился" in (a.get("text", "") or "") for a in items), items

    # Newest first: created_at is monotonically non-increasing.
    times = [a["created_at"] for a in items]
    assert times == sorted(times, reverse=True), times


# ── bulk actions: stage / assign / add_tag + tenant isolation ────────────────

def test_bulk_stage_assign_and_tag(paid_account, stub_sources, new_project):
    acct = paid_account
    pid, leads = _collect_leads(acct, new_project, niche=_niche())
    assert len(leads) >= 3
    ids = [leads[0]["id"], leads[1]["id"], leads[2]["id"]]
    me = _my_user_id(acct)

    # action="stage": move all three to qualified.
    r = acct.post(f"/api/leads/project/{pid}/bulk",
                  json={"lead_ids": ids, "action": "stage", "status": "qualified"})
    assert r.status_code in (200, 201), r.text
    assert r.json()["updated"] == 3
    for lid in ids:
        assert acct.get(f"/api/leads/{lid}").json()["status"] == "qualified"

    # action="assign": assign all three to the owner.
    r = acct.post(f"/api/leads/project/{pid}/bulk",
                  json={"lead_ids": ids, "action": "assign", "assigned_to_user_id": me})
    assert r.status_code in (200, 201), r.text
    assert r.json()["updated"] == 3
    for lid in ids:
        assert acct.get(f"/api/leads/{lid}").json()["assigned_to_user_id"] == me

    # action="add_tag": tag all three.
    r = acct.post(f"/api/leads/project/{pid}/bulk",
                  json={"lead_ids": ids, "action": "add_tag", "tag": "vip"})
    assert r.status_code in (200, 201), r.text
    assert r.json()["updated"] == 3
    for lid in ids:
        assert "vip" in acct.get(f"/api/leads/{lid}").json()["tags"]


def test_bulk_ignores_foreign_lead_ids(paid_account, make_account, stub_sources, new_project):
    """Tenant isolation: lead ids from another org are silently ignored — only
    the caller's own leads get updated."""
    acct = paid_account
    pid, leads = _collect_leads(acct, new_project, niche=_niche())
    mine = [leads[0]["id"], leads[1]["id"]]

    # A second org with its own lead.
    other = make_account(plan="pro")
    _, other_leads = _collect_leads(other, new_project, niche=_niche())
    foreign_id = other_leads[0]["id"]

    r = acct.post(f"/api/leads/project/{pid}/bulk",
                  json={"lead_ids": mine + [foreign_id], "action": "stage", "status": "won"})
    assert r.status_code in (200, 201), r.text
    # Only the two own leads counted.
    assert r.json()["updated"] == 2, r.json()
    for lid in mine:
        assert acct.get(f"/api/leads/{lid}").json()["status"] == "won"
    # The foreign lead is untouched (still in its original org, still "new").
    assert other.get(f"/api/leads/{foreign_id}").json()["status"] == "new"
