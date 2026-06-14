"""TRUE E2E for the admin console (/api/admin/*).

Two halves, end to end through real HTTP + auth + DB:

  1. Authorization wall — a normal (non-admin) user is 403'd on EVERY admin
     route (GET stats/users/orgs/jobs/logs + the PATCH mutators).
  2. Admin journey — flip user.is_admin in the DB (read fresh each request, no
     re-login) and exercise every endpoint, asserting both the HTTP response AND
     the persisted DB effect for the mutators.

We assert ">= our own created rows" against global counters (the DB is shared
and not reset between runs), never exact global totals.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Organization, PlanType, User


# ── helpers ──────────────────────────────────────────────────────────────────

def _promote(db, acct) -> User:
    """Flip is_admin=True on the account's user and commit. require_admin reads
    is_admin from the DB every request, so the existing Bearer keeps working."""
    user = db.execute(select(User).where(User.email == acct.email)).scalar_one()
    user.is_admin = True
    db.commit()
    return user


# Every admin route as (method, path-template, json-body-or-None). Path
# templates that need an id use "{uid}"/"{oid}" filled per-test.
_READ_ROUTES = [
    ("GET", "/api/admin/stats", None),
    ("GET", "/api/admin/users", None),
    ("GET", "/api/admin/organizations", None),
    ("GET", "/api/admin/jobs", None),
    ("GET", "/api/admin/logs", None),
]


# ── 1. authorization wall ────────────────────────────────────────────────────

def test_normal_user_forbidden_on_all_admin_reads(make_account):
    """A freshly-registered, non-admin user gets 403 on every admin GET."""
    acct = make_account()
    for method, path, _body in _READ_ROUTES:
        r = acct.request(method, path)
        assert r.status_code == 403, f"{method} {path} → {r.status_code}, expected 403"
        assert "админ" in r.json()["detail"].lower()


def test_normal_user_forbidden_on_all_admin_mutators(make_account, db):
    """Non-admin is 403'd on the PATCH mutators too — authorization is checked
    BEFORE any body/id validation, so even well-formed payloads are refused."""
    acct = make_account()
    user = db.execute(select(User).where(User.email == acct.email)).scalar_one()
    uid, oid = str(user.id), acct.org_id

    cases = [
        ("PATCH", f"/api/admin/users/{uid}", {"is_admin": True}),
        ("PATCH", f"/api/admin/organizations/{oid}/limits",
         {"projects_limit": 10, "leads_limit_per_month": 999}),
        ("PATCH", f"/api/admin/organizations/{oid}/plan", {"plan": "pro"}),
        ("DELETE", f"/api/admin/users/{uid}", None),
    ]
    for method, path, body in cases:
        r = acct.request(method, path, json=body) if body else acct.request(method, path)
        assert r.status_code == 403, f"{method} {path} → {r.status_code}, expected 403"

    # And the would-be self-promotion did NOT take effect.
    db.refresh(user)
    assert user.is_admin is False


def test_unauthenticated_admin_is_401(client):
    """No Bearer at all → 401 (auth layer), distinct from the authenticated-but-
    not-admin 403."""
    r = client.get("/api/admin/stats")
    assert r.status_code == 401


def test_bad_bearer_admin_is_401(make_account):
    acct = make_account()
    r = acct.get("/api/admin/stats", headers={"Authorization": "Bearer not-a-real-jwt"})
    assert r.status_code == 401


# ── 2. admin journey ─────────────────────────────────────────────────────────

def test_admin_stats_counts_our_rows(make_account, db):
    """GET /admin/stats: structure is intact and global counters include the
    org+user we just created (>= 1 each, never exact)."""
    acct = make_account()
    _promote(db, acct)

    r = acct.get("/api/admin/stats")
    assert r.status_code == 200, r.text
    body = r.json()

    # Shape.
    for key in ("totals", "recent", "revenue_monthly_rub", "plan_distribution"):
        assert key in body, f"missing {key}: {body}"
    totals = body["totals"]
    for key in ("users", "organizations", "projects", "leads", "jobs"):
        assert key in totals

    # Our just-created user + org are counted.
    assert totals["users"] >= 1
    assert totals["organizations"] >= 1
    assert body["recent"]["users_today"] >= 1, "we registered today"

    # Plan distribution covers every plan and our free org bumps the free bucket.
    pd = body["plan_distribution"]
    assert set(pd.keys()) == {p.value for p in PlanType}
    assert pd["free"] >= 1

    # No subscriptions paid → revenue is a non-negative number (not the plan field).
    assert isinstance(body["revenue_monthly_rub"], (int, float))
    assert body["revenue_monthly_rub"] >= 0


def test_admin_lists_users_and_finds_self(make_account, db):
    """GET /admin/users: paginated envelope; our user is present and now flagged
    admin. (We page through enough rows to find ourselves on a shared DB.)"""
    acct = make_account()
    _promote(db, acct)

    r = acct.get("/api/admin/users", params={"limit": 200})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "total" in body and "items" in body
    assert body["total"] >= 1
    assert len(body["items"]) <= 200

    # Walk pages until we find ourselves (newest-first ordering helps, but be safe).
    found = None
    skip = 0
    while skip < body["total"] and skip < 1000:
        page = acct.get("/api/admin/users", params={"skip": skip, "limit": 200}).json()
        if not page["items"]:
            break
        for u in page["items"]:
            if u["email"] == acct.email:
                found = u
                break
        if found:
            break
        skip += 200
    assert found is not None, "our user must appear in /admin/users"
    assert found["is_admin"] is True
    assert found["full_name"] == acct.full_name


def test_admin_patch_user_promotes_second_user(make_account, db):
    """PATCH /admin/users/{id}: an admin promotes a DIFFERENT user (is_admin) and
    demotes email_verified; both changes are persisted (verified via DB), and a
    200 message comes back."""
    admin_acct = make_account()
    _promote(db, admin_acct)

    target = make_account()  # second, independent org+user
    target_user = db.execute(select(User).where(User.email == target.email)).scalar_one()
    assert target_user.is_admin is False

    # Flip BOTH toggles; admin can demote email_verified too, so set False to
    # prove the patch writes the literal value (not just truthy promotion).
    r = admin_acct.patch(
        f"/api/admin/users/{target_user.id}",
        json={"is_admin": True, "email_verified": False},
    )
    assert r.status_code == 200, r.text
    assert "обновл" in r.json()["message"].lower()

    db.refresh(target_user)
    assert target_user.is_admin is True
    assert target_user.email_verified is False


def test_admin_cannot_patch_self(make_account, db):
    """The route forbids an admin editing their OWN account (400), guarding
    against self-lockout / self-escalation noise."""
    acct = make_account()
    user = _promote(db, acct)

    r = acct.patch(f"/api/admin/users/{user.id}", json={"is_admin": False})
    assert r.status_code == 400, r.text
    db.refresh(user)
    assert user.is_admin is True  # unchanged


def test_admin_patch_user_bad_id_and_missing(make_account, db):
    """Malformed UUID → 400; well-formed-but-absent → 404."""
    acct = make_account()
    _promote(db, acct)

    bad = acct.patch("/api/admin/users/not-a-uuid", json={"is_admin": True})
    assert bad.status_code == 400, bad.text

    missing = acct.patch(
        "/api/admin/users/00000000-0000-0000-0000-000000000000",
        json={"is_admin": True},
    )
    assert missing.status_code == 404, missing.text


def test_admin_lists_organizations_with_our_org(make_account, db):
    """GET /admin/organizations: enriched rows (members/projects/leads counts +
    limits). Our org appears with the expected free-plan shape."""
    acct = make_account()
    _promote(db, acct)

    found = None
    skip = 0
    while skip < 2000:
        page = acct.get("/api/admin/organizations", params={"skip": skip, "limit": 200}).json()
        assert "total" in page and "items" in page
        if not page["items"]:
            break
        for o in page["items"]:
            if o["id"] == acct.org_id:
                found = o
                break
        if found or skip + 200 >= page["total"]:
            break
        skip += 200
    assert found is not None, "our org must appear in /admin/organizations"
    assert found["plan"] == "free"
    assert found["members_count"] >= 1  # the registrant
    for key in ("projects_count", "leads_count", "projects_limit",
                "leads_limit_per_month", "leads_used_current_month"):
        assert key in found


def test_admin_update_org_limits_persists(make_account, db):
    """PATCH /admin/organizations/{id}/limits: changes leads_limit_per_month and
    projects_limit; verify the new values landed in the DB."""
    acct = make_account()
    _promote(db, acct)

    org = db.get(Organization, acct.org_id)
    assert org.leads_limit_per_month == 0  # free default

    r = acct.patch(
        f"/api/admin/organizations/{acct.org_id}/limits",
        json={"projects_limit": 7, "leads_limit_per_month": 4242},
    )
    assert r.status_code == 200, r.text
    assert "лимит" in r.json()["message"].lower()

    db.expire_all()
    org = db.get(Organization, acct.org_id)
    assert org.leads_limit_per_month == 4242
    assert org.projects_limit == 7


def test_admin_update_org_limits_validates_payload(make_account, db):
    """Limits below the schema floor (ge=1) → 422; absent org → 404."""
    acct = make_account()
    _promote(db, acct)

    too_low = acct.patch(
        f"/api/admin/organizations/{acct.org_id}/limits",
        json={"projects_limit": 0, "leads_limit_per_month": 0},
    )
    assert too_low.status_code == 422, too_low.text

    missing = acct.patch(
        "/api/admin/organizations/00000000-0000-0000-0000-000000000000/limits",
        json={"projects_limit": 5, "leads_limit_per_month": 100},
    )
    assert missing.status_code == 404, missing.text


def test_admin_update_org_plan_applies_plan_limits(make_account, db):
    """PATCH /admin/organizations/{id}/plan: switching free→starter sets the
    plan AND re-applies the plan's quota grid (leads_limit becomes 5000)."""
    acct = make_account()
    _promote(db, acct)

    org = db.get(Organization, acct.org_id)
    assert org.plan == PlanType.free
    assert org.leads_limit_per_month == 0

    r = acct.patch(
        f"/api/admin/organizations/{acct.org_id}/plan",
        json={"plan": "starter"},
    )
    assert r.status_code == 200, r.text
    assert "starter" in r.json()["message"].lower()

    db.expire_all()
    org = db.get(Organization, acct.org_id)
    assert org.plan == PlanType.starter
    # apply_plan_limits ran → starter grid (see app/services/quota.PLAN_LIMITS).
    assert org.leads_limit_per_month == 5000
    assert org.projects_limit == 5


def test_admin_update_org_plan_rejects_unknown_plan(make_account, db):
    """An unrecognised plan string → 400; the org's plan is left untouched."""
    acct = make_account()
    _promote(db, acct)

    r = acct.patch(
        f"/api/admin/organizations/{acct.org_id}/plan",
        json={"plan": "platinum"},
    )
    assert r.status_code == 400, r.text

    db.expire_all()
    org = db.get(Organization, acct.org_id)
    assert org.plan == PlanType.free  # unchanged


def test_admin_jobs_list_shows_our_collect_job(paid_account, stub_sources, new_project, db):
    """GET /admin/jobs: after a real collect (eager Celery), the finished job is
    visible globally with enriched project/org names and counts. Also exercises
    the ?status= filter."""
    acct = paid_account
    _promote(db, acct)

    project = new_project(acct)
    pid = project["id"]
    collect = acct.post(f"/api/leads/project/{pid}/collect", json={"lead_limit": 10})
    assert collect.status_code in (200, 201), collect.text

    r = acct.get("/api/admin/jobs", params={"limit": 200})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "total" in body and "items" in body
    assert body["total"] >= 1

    # Our project's jobs should be in there. Collect auto-fires an enrich job
    # afterward, so the project yields BOTH a "collect" and an "enrich" row —
    # pick the collect one explicitly rather than assuming newest-first.
    ours = [j for j in body["items"] if j["project_name"] == project["name"]]
    assert ours, f"our collect job not found in /admin/jobs; saw {len(body['items'])} items"
    collect_jobs = [j for j in ours if j["kind"] == "collect"]
    assert collect_jobs, f"no collect job for our project; kinds seen: {[j['kind'] for j in ours]}"
    job = collect_jobs[0]
    for key in ("id", "project_name", "org_name", "status", "kind",
                "requested_limit", "found_count", "added_count", "enriched_count"):
        assert key in job
    assert job["kind"] == "collect"
    assert job["org_name"]  # enriched org name, not "—"
    assert job["added_count"] >= 1, f"collect added no leads: {job}"

    # status filter narrows the set: every returned row matches.
    done = acct.get("/api/admin/jobs", params={"status": "done", "limit": 200}).json()
    assert all(j["status"] == "done" for j in done["items"])
    assert done["total"] >= 1


def test_admin_logs_list_envelope(make_account, db):
    """GET /admin/logs: returns the standard {total, items} envelope; each item
    (if any) carries the audit fields. We don't depend on a specific log existing
    on a shared DB, only on the contract."""
    acct = make_account()
    _promote(db, acct)

    r = acct.get("/api/admin/logs", params={"limit": 50})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "total" in body and "items" in body
    assert isinstance(body["items"], list)
    assert body["total"] >= 0
    for log in body["items"]:
        for key in ("id", "action", "user_email", "org_name", "meta", "created_at"):
            assert key in log


def test_admin_pagination_limit_capped(make_account, db):
    """limit is bounded (le=200): asking for more than 200 is a 422 (Query
    validation), so the endpoint can't be coerced into an unbounded scan."""
    acct = make_account()
    _promote(db, acct)

    r = acct.get("/api/admin/users", params={"limit": 5000})
    assert r.status_code == 422, r.text
