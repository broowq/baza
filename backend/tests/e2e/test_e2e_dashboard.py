"""E2E: the org-wide analytics dashboard + the in-app notification bell.

Drives real HTTP + auth + DB (no dependency overrides). Two endpoints:

  GET /api/crm/dashboard
    Org-wide analytics across every LIVE project (soft-deleted projects
    excluded via the Project join). Asserts the aggregation contract:
      * leads_total counts every lead across projects,
      * by_status carries count + sum(deal_value) per pipeline stage,
      * conversion_rate = won / (won + lost),
      * pipeline_value sums OPEN-stage deal_value only (won + rejected excluded),
      * by_source groups by the lead's source string,
      * by_assignee includes a "Не назначен" bucket for unassigned leads,
      * over_time has exactly 14 zero-filled daily points,
      * a second org's leads never bleed in, and a soft-deleted project's
        leads drop out.

  GET /api/crm/notifications
    The bell: overdue tasks, due reminders, fresh inbound replies. Asserts
    each group counts the right rows (and only those), items carry lead
    linkage, total is the badge sum, and not-due / done / future rows are
    excluded.

Leads are created over real HTTP (POST /api/leads/project/{pid}). The create
endpoint hardcodes source="manual", so per-source variety + the notification
fixtures (LeadTask, Lead.reminder_at, OutreachReply) are seeded straight in the
DB via the `db` fixture — the things a journey can't do over HTTP.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.db.session import SessionLocal
from app.models import Lead, LeadStatus, LeadTask, OutreachReply, Project


# ── helpers ──────────────────────────────────────────────────────────────────

def _mk_lead(acct, pid: str, company: str, **over) -> dict:
    """Create a manual lead in a project over HTTP; return the lead JSON.

    Accepts status / deal_value / assigned_to_user_id (the create endpoint's
    CRM fields). A distinct website keeps the project's dedup from collapsing
    same-named test companies.
    """
    payload = {"company": company, **over}
    r = acct.post(f"/api/leads/project/{pid}", json=payload)
    assert r.status_code == 201, f"create lead failed: {r.status_code} {r.text}"
    return r.json()


def _dashboard(acct) -> dict:
    r = acct.get("/api/crm/dashboard")
    assert r.status_code == 200, r.text
    return r.json()


def _notifications(acct) -> dict:
    r = acct.get("/api/crm/notifications")
    assert r.status_code == 200, r.text
    return r.json()


def _me_id(acct) -> str:
    r = acct.get("/api/auth/me")
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _set_source(lead_id: str, source: str) -> None:
    """Stamp a lead's `source` directly (the create endpoint forces 'manual')."""
    db = SessionLocal()
    try:
        lead = db.get(Lead, lead_id)
        lead.source = source
        db.commit()
    finally:
        db.close()


def _soft_delete_project(pid: str) -> None:
    db = SessionLocal()
    try:
        proj = db.get(Project, pid)
        proj.deleted_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()


def _by_status(body: dict) -> dict[str, dict]:
    return {row["status"]: row for row in body["by_status"]}


# ── dashboard: the full aggregation contract ─────────────────────────────────

def test_dashboard_aggregates_across_projects(paid_account, new_project):
    """Leads across 2 projects in various stages → every dashboard aggregate is
    correct: totals, per-status count+value, conversion, pipeline value (open
    only), sources, the unassigned bucket, and the 14-point timeline."""
    acct = paid_account
    me = _me_id(acct)
    p1 = new_project(acct, name="Проект А")
    p2 = new_project(acct, name="Проект Б")

    # p1: a new (unassigned), a contacted (assigned to me), a won.
    l_new = _mk_lead(acct, p1["id"], "Альфа Новый", website="https://d-new.ru",
                     status="new", deal_value=100)
    l_contacted = _mk_lead(acct, p1["id"], "Альфа Связались", website="https://d-cont.ru",
                           status="contacted", deal_value=200,
                           assigned_to_user_id=me)
    l_won = _mk_lead(acct, p1["id"], "Альфа Сделка", website="https://d-won.ru",
                     status="won", deal_value=5000, assigned_to_user_id=me)
    # p2: a qualified (unassigned), a rejected.
    l_qual = _mk_lead(acct, p2["id"], "Бета Квал", website="https://d-qual.ru",
                      status="qualified", deal_value=300)
    l_rej = _mk_lead(acct, p2["id"], "Бета Отказ", website="https://d-rej.ru",
                     status="rejected", deal_value=9999)

    # Give the leads two distinct sources (3× "2gis", 2× "yandex_maps").
    for lid in (l_new["id"], l_contacted["id"], l_won["id"]):
        _set_source(lid, "2gis")
    for lid in (l_qual["id"], l_rej["id"]):
        _set_source(lid, "yandex_maps")

    body = _dashboard(acct)

    # ── totals ───────────────────────────────────────────────────────────────
    assert body["leads_total"] == 5, body
    assert body["leads_this_month"] == 5  # all just-created
    assert body["won"] == 1
    assert body["lost"] == 1

    # ── by_status: count + value per stage (all 6 stages present) ────────────
    bs = _by_status(body)
    assert {s["status"] for s in body["by_status"]} == {
        "new", "contacted", "qualified", "proposal", "won", "rejected"
    }
    assert bs["new"]["count"] == 1 and bs["new"]["value"] == 100
    assert bs["contacted"]["count"] == 1 and bs["contacted"]["value"] == 200
    assert bs["qualified"]["count"] == 1 and bs["qualified"]["value"] == 300
    assert bs["proposal"]["count"] == 0 and bs["proposal"]["value"] == 0
    assert bs["won"]["count"] == 1 and bs["won"]["value"] == 5000
    assert bs["rejected"]["count"] == 1 and bs["rejected"]["value"] == 9999

    # ── conversion_rate = won / (won + lost) ─────────────────────────────────
    assert body["conversion_rate"] == 0.5

    # ── pipeline_value = open-stage deal_value only (won+rejected excluded) ───
    assert body["pipeline_value"] == 100 + 200 + 300
    assert body["won_value"] == 5000

    # ── by_source groups ─────────────────────────────────────────────────────
    src = {row["source"]: row["count"] for row in body["by_source"]}
    assert src.get("2gis") == 3
    assert src.get("yandex_maps") == 2

    # ── by_assignee: assigned-to-me bucket + a "Не назначен" bucket ──────────
    by_name = {row["name"]: row for row in body["by_assignee"]}
    assert "Не назначен" in by_name, body["by_assignee"]
    unassigned = by_name["Не назначен"]
    assert unassigned["user_id"] is None
    assert unassigned["leads"] == 3  # l_new + l_qual + l_rej (assignee defaults null)

    mine = next(r for r in body["by_assignee"] if r["user_id"] == me)
    assert mine["leads"] == 2   # l_contacted + l_won
    assert mine["won"] == 1     # only l_won

    # ── over_time: exactly 14 zero-filled daily points, last day = today ─────
    assert len(body["over_time"]) == 14
    today = datetime.now(timezone.utc).date().isoformat()
    assert body["over_time"][-1]["date"] == today
    assert body["over_time"][-1]["count"] == 5
    assert all("date" in p and "count" in p for p in body["over_time"])
    assert body["over_time"][0]["count"] == 0  # 13 days ago: empty


def test_dashboard_conversion_rate_zero_without_closed_leads(paid_account, new_project):
    """No won and no lost → conversion_rate is 0.0 (no division by zero)."""
    acct = paid_account
    pid = new_project(acct)["id"]
    _mk_lead(acct, pid, "Только Новый", website="https://only-new.ru", status="new")

    body = _dashboard(acct)
    assert body["won"] == 0 and body["lost"] == 0
    assert body["conversion_rate"] == 0.0


def test_dashboard_isolates_other_org(make_account, new_project):
    """A second org's leads never appear in the first org's dashboard totals."""
    me = make_account(plan="pro")
    other = make_account(plan="pro")

    mine_pid = new_project(me)["id"]
    _mk_lead(me, mine_pid, "Моя Компания", website="https://mine-dash.ru",
             status="won", deal_value=1000)

    other_pid = new_project(other)["id"]
    _mk_lead(other, other_pid, "Чужая Компания", website="https://theirs-dash.ru",
             status="won", deal_value=999999)

    body = _dashboard(me)
    assert body["leads_total"] == 1, "another org's lead leaked into the dashboard"
    assert body["won_value"] == 1000  # NOT 999999 — other org excluded


def test_dashboard_excludes_soft_deleted_project(paid_account, new_project):
    """Leads in a soft-deleted project drop out of every dashboard aggregate."""
    acct = paid_account
    live = new_project(acct, name="Живой")
    doomed = new_project(acct, name="Удаляемый")

    _mk_lead(acct, live["id"], "Живой Лид", website="https://live-dash.ru",
             status="new", deal_value=50)
    _mk_lead(acct, doomed["id"], "Удалённый Лид", website="https://gone-dash.ru",
             status="won", deal_value=7777)

    before = _dashboard(acct)
    assert before["leads_total"] == 2

    _soft_delete_project(doomed["id"])

    after = _dashboard(acct)
    assert after["leads_total"] == 1, "soft-deleted project's lead must be excluded"
    assert after["won"] == 0
    assert after["won_value"] == 0
    bs = _by_status(after)
    assert bs["new"]["value"] == 50


# ── notifications: the bell ──────────────────────────────────────────────────

def _seed_overdue_task(org_id: str, lead_id: str, *, title: str,
                       due_at: datetime, done: bool) -> str:
    db = SessionLocal()
    try:
        task = LeadTask(
            organization_id=org_id,
            lead_id=lead_id,
            title=title,
            due_at=due_at,
            done=done,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return str(task.id)
    finally:
        db.close()


def _set_reminder(lead_id: str, reminder_at: datetime | None) -> None:
    db = SessionLocal()
    try:
        lead = db.get(Lead, lead_id)
        lead.reminder_at = reminder_at
        db.commit()
    finally:
        db.close()


def _seed_reply(org_id: str, lead_id: str, *, received_at: datetime) -> str:
    db = SessionLocal()
    try:
        reply = OutreachReply(
            organization_id=org_id,
            lead_id=lead_id,
            from_email="prospect@example.com",
            subject="Re: Предложение",
            snippet="Интересно, расскажите подробнее",
            received_at=received_at,
        )
        db.add(reply)
        db.commit()
        db.refresh(reply)
        return str(reply.id)
    finally:
        db.close()


def test_notifications_counts_each_group_and_total(paid_account, new_project):
    """One overdue task + one due reminder + one fresh reply → each group counts
    1, total == 3, and the items carry their lead linkage."""
    acct = paid_account
    org_id = acct.org_id
    pid = new_project(acct)["id"]

    now = datetime.now(timezone.utc)
    lead = _mk_lead(acct, pid, "Лид Уведомлений", website="https://notif-lead.ru")
    lead_id = lead["id"]

    task_id = _seed_overdue_task(
        org_id, lead_id, title="Перезвонить",
        due_at=now - timedelta(hours=2), done=False,
    )
    _set_reminder(lead_id, now - timedelta(hours=1))
    reply_id = _seed_reply(org_id, lead_id, received_at=now - timedelta(minutes=30))

    body = _notifications(acct)

    assert body["overdue_tasks"]["count"] == 1
    assert body["due_reminders"]["count"] == 1
    assert body["new_replies"]["count"] == 1
    assert body["total"] == 3

    # ── lead linkage on each item ────────────────────────────────────────────
    od = body["overdue_tasks"]["items"]
    assert len(od) == 1
    assert od[0]["id"] == task_id
    assert od[0]["lead_id"] == lead_id
    assert od[0]["lead_company"] == "Лид Уведомлений"

    rem = body["due_reminders"]["items"]
    assert len(rem) == 1
    assert rem[0]["lead_id"] == lead_id
    assert rem[0]["company"] == "Лид Уведомлений"

    rep = body["new_replies"]["items"]
    assert len(rep) == 1
    assert rep[0]["id"] == reply_id
    assert rep[0]["lead_id"] == lead_id
    assert rep[0]["from_email"] == "prospect@example.com"


def test_notifications_excludes_not_due_done_and_future(paid_account, new_project):
    """A done task, a future-due task, and a future reminder do NOT notify →
    every group counts 0 and total == 0."""
    acct = paid_account
    org_id = acct.org_id
    pid = new_project(acct)["id"]

    now = datetime.now(timezone.utc)
    lead = _mk_lead(acct, pid, "Тихий Лид", website="https://quiet-lead.ru")
    lead_id = lead["id"]

    # An overdue-by-date task that is DONE → must not count.
    _seed_overdue_task(org_id, lead_id, title="Уже сделано",
                       due_at=now - timedelta(days=1), done=True)
    # A not-yet-due task (future) → must not count.
    _seed_overdue_task(org_id, lead_id, title="Ещё не срок",
                       due_at=now + timedelta(days=1), done=False)
    # A future reminder → must not count.
    _set_reminder(lead_id, now + timedelta(days=2))

    body = _notifications(acct)
    assert body["overdue_tasks"]["count"] == 0, body["overdue_tasks"]
    assert body["due_reminders"]["count"] == 0
    assert body["new_replies"]["count"] == 0
    assert body["total"] == 0


def test_notifications_isolate_other_org(make_account, new_project):
    """Another org's overdue task / due reminder / reply never reach my bell."""
    me = make_account(plan="pro")
    other = make_account(plan="pro")

    now = datetime.now(timezone.utc)
    other_pid = new_project(other)["id"]
    other_lead = _mk_lead(other, other_pid, "Чужой Лид", website="https://other-notif.ru")

    _seed_overdue_task(other.org_id, other_lead["id"], title="Чужая задача",
                       due_at=now - timedelta(hours=1), done=False)
    _set_reminder(other_lead["id"], now - timedelta(hours=1))
    _seed_reply(other.org_id, other_lead["id"], received_at=now - timedelta(minutes=5))

    body = _notifications(me)
    assert body["total"] == 0, "another org's notifications leaked into the bell"
