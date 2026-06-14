"""TRUE E2E: Lead CRUD + workflow + call journal + table filters/sort/pagination.

Drives the real app through HTTP + auth + Postgres (eager Celery, stubbed
sources). Every test collects a real dose first, then exercises the lead
lifecycle: PATCH (status/notes/tags/reminder/mark_contacted), the call journal,
DELETE, and the table endpoint's filtering / pagination / sorting.

Pattern follows tests/e2e/test_e2e_core_journey.py. Asserts real status codes
AND response/DB state — never just 200.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models import Lead, LeadCallNote, LeadStatus


# ── shared helper ────────────────────────────────────────────────────────────

def _collect(acct, new_project, *, n=12, lead_limit=10, **proj_over):
    """Create a project, collect a dose, return (pid, [lead dicts sorted desc score])."""
    project = new_project(acct, **proj_over)
    pid = project["id"]
    collect = acct.post(f"/api/leads/project/{pid}/collect", json={"lead_limit": lead_limit})
    assert collect.status_code in (200, 201), collect.text
    table = acct.get(f"/api/leads/project/{pid}/table?per_page=200")
    assert table.status_code == 200, table.text
    body = table.json()
    assert body["total"] >= 1, f"collect delivered no leads: {body}"
    return pid, body["items"]


def _first_lead(acct, new_project, **kw):
    pid, items = _collect(acct, new_project, **kw)
    return pid, items[0]["id"]


# ── PATCH: status change ─────────────────────────────────────────────────────

def test_patch_status_change_persists(paid_account, stub_sources, new_project, db):
    acct = paid_account
    pid, lead_id = _first_lead(acct, new_project)

    r = acct.patch(f"/api/leads/{lead_id}", json={"status": "qualified"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "qualified"

    # Persisted in DB.
    row = db.get(Lead, lead_id)
    db.refresh(row)
    assert row.status == LeadStatus.qualified

    # All four valid statuses accepted.
    for st in ("new", "contacted", "qualified", "rejected"):
        rr = acct.patch(f"/api/leads/{lead_id}", json={"status": st})
        assert rr.status_code == 200, rr.text
        assert rr.json()["status"] == st


def test_patch_invalid_status_rejected(paid_account, stub_sources, new_project):
    acct = paid_account
    pid, lead_id = _first_lead(acct, new_project)
    r = acct.patch(f"/api/leads/{lead_id}", json={"status": "totally_bogus"})
    assert r.status_code == 422, r.text
    # The lead's status must be unchanged (still "new").
    assert acct.get(f"/api/leads/{lead_id}").json()["status"] == "new"


# ── PATCH: notes ─────────────────────────────────────────────────────────────

def test_patch_notes_set(paid_account, stub_sources, new_project, db):
    acct = paid_account
    pid, lead_id = _first_lead(acct, new_project)
    note = "Перезвонить после 18:00, ЛПР — главврач"
    r = acct.patch(f"/api/leads/{lead_id}", json={"notes": note})
    assert r.status_code == 200, r.text
    assert r.json()["notes"] == note
    row = db.get(Lead, lead_id)
    db.refresh(row)
    assert row.notes == note


# ── PATCH: tags sanitization (trim / dedupe / <=30 chars) ────────────────────

def test_patch_tags_sanitized(paid_account, stub_sources, new_project):
    acct = paid_account
    pid, lead_id = _first_lead(acct, new_project)

    long_tag = "x" * 50  # must be truncated to 30 chars
    payload = {
        "tags": [
            "  важный  ",      # trimmed → "важный"
            "важный",          # exact dupe of trimmed → dropped
            "ВАЖНЫЙ",          # case-insensitive dupe → dropped
            "горячий",
            "   ",             # whitespace-only → dropped (empty after trim)
            "",                # empty → dropped
            long_tag,          # truncated to 30 chars
        ]
    }
    r = acct.patch(f"/api/leads/{lead_id}", json=payload)
    assert r.status_code == 200, r.text
    tags = r.json()["tags"]

    assert tags == ["важный", "горячий", "x" * 30], tags
    # No tag exceeds 30 chars.
    assert all(len(t) <= 30 for t in tags)
    # First-seen casing wins for the dedupe.
    assert "ВАЖНЫЙ" not in tags


def test_patch_tags_over_limit_422(paid_account, stub_sources, new_project):
    """The LeadUpdate schema caps the tag list at 20 entries (pydantic max_length)."""
    acct = paid_account
    pid, lead_id = _first_lead(acct, new_project)
    r = acct.patch(f"/api/leads/{lead_id}", json={"tags": [f"t{i}" for i in range(21)]})
    assert r.status_code == 422, r.text


# ── PATCH: reminder_at set then CLEAR via null (must persist null) ────────────

def test_patch_reminder_set_then_clear_persists_null(paid_account, stub_sources, new_project, db):
    acct = paid_account
    pid, lead_id = _first_lead(acct, new_project)

    # Set a reminder.
    when = "2026-12-31T09:00:00+00:00"
    r = acct.patch(f"/api/leads/{lead_id}", json={"reminder_at": when})
    assert r.status_code == 200, r.text
    assert r.json()["reminder_at"] is not None
    row = db.get(Lead, lead_id)
    db.refresh(row)
    assert row.reminder_at is not None

    # Clear it via explicit null (the × button). Must persist as null, NOT be
    # silently ignored (the model_fields_set guard in the route).
    r2 = acct.patch(f"/api/leads/{lead_id}", json={"reminder_at": None})
    assert r2.status_code == 200, r2.text
    assert r2.json()["reminder_at"] is None, "explicit null must CLEAR the reminder"

    # Verify the clear actually persisted in the DB.
    db.expire_all()
    row2 = db.get(Lead, lead_id)
    db.refresh(row2)
    assert row2.reminder_at is None, "cleared reminder must be NULL in the DB"

    # And a fresh GET confirms it.
    assert acct.get(f"/api/leads/{lead_id}").json()["reminder_at"] is None


def test_patch_omitted_reminder_left_untouched(paid_account, stub_sources, new_project):
    """An UNSET reminder_at (field omitted) leaves an existing reminder intact —
    distinct from an explicit null which clears it."""
    acct = paid_account
    pid, lead_id = _first_lead(acct, new_project)

    acct.patch(f"/api/leads/{lead_id}", json={"reminder_at": "2026-11-01T12:00:00+00:00"})
    # Now PATCH something else WITHOUT touching reminder_at.
    r = acct.patch(f"/api/leads/{lead_id}", json={"notes": "не трогать напоминание"})
    assert r.status_code == 200, r.text
    assert r.json()["reminder_at"] is not None, "omitted reminder_at must be left untouched"


# ── PATCH: mark_contacted sets last_contacted_at + status contacted ──────────

def test_mark_contacted_sets_timestamp_and_status(paid_account, stub_sources, new_project, db):
    acct = paid_account
    pid, lead_id = _first_lead(acct, new_project)

    # Lead starts "new" with no contact timestamp.
    before = acct.get(f"/api/leads/{lead_id}").json()
    assert before["status"] == "new"
    assert before["last_contacted_at"] is None

    r = acct.patch(f"/api/leads/{lead_id}", json={"mark_contacted": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "contacted"
    assert body["last_contacted_at"] is not None

    row = db.get(Lead, lead_id)
    db.refresh(row)
    assert row.status == LeadStatus.contacted
    assert row.last_contacted_at is not None


def test_mark_contacted_does_not_downgrade_existing_status(paid_account, stub_sources, new_project):
    """mark_contacted only bumps "new" → "contacted"; a "qualified" lead keeps
    its status but still gets the timestamp."""
    acct = paid_account
    pid, lead_id = _first_lead(acct, new_project)
    acct.patch(f"/api/leads/{lead_id}", json={"status": "qualified"})

    r = acct.patch(f"/api/leads/{lead_id}", json={"mark_contacted": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "qualified", "mark_contacted must not downgrade a qualified lead"
    assert body["last_contacted_at"] is not None


# ── Call journal: POST/GET + attribution + comment > 2000 = 422 ─────────────

def test_call_journal_post_get_attribution(paid_account, stub_sources, new_project, db):
    acct = paid_account
    pid, lead_id = _first_lead(acct, new_project)

    r = acct.post(f"/api/leads/{lead_id}/calls", json={"comment": "Дозвонился, ждут КП"})
    assert r.status_code == 201, r.text
    note = r.json()
    # Attributed to the caller.
    assert note["user_name"] == acct.full_name
    assert note["comment"] == "Дозвонился, ждут КП"
    assert note["id"]

    # Read it back.
    calls = acct.get(f"/api/leads/{lead_id}/calls")
    assert calls.status_code == 200
    assert len(calls.json()) == 1
    assert calls.json()[0]["user_name"] == acct.full_name

    # Side effect: a "new" lead moved to "contacted" + got a timestamp.
    detail = acct.get(f"/api/leads/{lead_id}").json()
    assert detail["status"] == "contacted"
    assert detail["last_contacted_at"] is not None

    # Persisted: a LeadCallNote row tied to this lead + org.
    row = db.execute(
        select(LeadCallNote).where(LeadCallNote.lead_id == lead_id)
    ).scalar_one()
    assert row.organization_id is not None
    assert row.comment == "Дозвонился, ждут КП"


def test_call_journal_newest_first(paid_account, stub_sources, new_project):
    acct = paid_account
    pid, lead_id = _first_lead(acct, new_project)
    for i in range(3):
        r = acct.post(f"/api/leads/{lead_id}/calls", json={"comment": f"звонок {i}"})
        assert r.status_code == 201, r.text
    calls = acct.get(f"/api/leads/{lead_id}/calls").json()
    assert len(calls) == 3
    # Newest first ordering.
    assert calls[0]["comment"] == "звонок 2"
    assert calls[-1]["comment"] == "звонок 0"


def test_call_journal_empty_comment_allowed(paid_account, stub_sources, new_project):
    """Comment is optional — just marking the call (who/when) is valid."""
    acct = paid_account
    pid, lead_id = _first_lead(acct, new_project)
    r = acct.post(f"/api/leads/{lead_id}/calls", json={})
    assert r.status_code == 201, r.text
    assert r.json()["comment"] == ""
    assert r.json()["user_name"] == acct.full_name


def test_call_journal_comment_too_long_422(paid_account, stub_sources, new_project):
    acct = paid_account
    pid, lead_id = _first_lead(acct, new_project)
    r = acct.post(f"/api/leads/{lead_id}/calls", json={"comment": "я" * 2001})
    assert r.status_code == 422, r.text
    # Exactly 2000 is the boundary and must be accepted.
    r_ok = acct.post(f"/api/leads/{lead_id}/calls", json={"comment": "я" * 2000})
    assert r_ok.status_code == 201, r_ok.text
    assert len(r_ok.json()["comment"]) == 2000


def test_call_journal_other_org_404(paid_account, make_account, stub_sources, new_project):
    """A second org cannot read/write the call journal of the first org's lead."""
    acct = paid_account
    pid, lead_id = _first_lead(acct, new_project)
    other = make_account(plan="pro")
    assert other.get(f"/api/leads/{lead_id}/calls").status_code == 404
    assert other.post(f"/api/leads/{lead_id}/calls", json={"comment": "leak"}).status_code == 404


# ── DELETE /leads/{id} then GET 404 ─────────────────────────────────────────

def test_delete_lead_then_404(paid_account, stub_sources, new_project, db):
    acct = paid_account
    pid, lead_id = _first_lead(acct, new_project)

    # Detail exists before delete.
    assert acct.get(f"/api/leads/{lead_id}").status_code == 200

    d = acct.delete(f"/api/leads/{lead_id}")
    assert d.status_code == 204, d.text

    # GET now 404.
    assert acct.get(f"/api/leads/{lead_id}").status_code == 404
    # PATCH on a deleted lead is also 404.
    assert acct.patch(f"/api/leads/{lead_id}", json={"status": "new"}).status_code == 404

    # Gone from the DB.
    db.expire_all()
    assert db.get(Lead, lead_id) is None


def test_delete_lead_other_org_404(paid_account, make_account, stub_sources, new_project, db):
    """Tenant isolation: a different org cannot delete this org's lead."""
    acct = paid_account
    pid, lead_id = _first_lead(acct, new_project)
    other = make_account(plan="pro")
    assert other.delete(f"/api/leads/{lead_id}").status_code == 404
    # The lead still exists for the rightful owner.
    assert acct.get(f"/api/leads/{lead_id}").status_code == 200


# ── Table filters: status / has_email / has_phone / min_score / max_score / q ─

def test_table_filter_status(paid_account, stub_sources, new_project):
    acct = paid_account
    pid, items = _collect(acct, new_project)
    total = len(items)
    assert total >= 2

    # All start "new".
    new_only = acct.get(f"/api/leads/project/{pid}/table?status=new&per_page=200").json()
    assert new_only["total"] == total

    # Move one to qualified.
    acct.patch(f"/api/leads/{items[0]['id']}", json={"status": "qualified"})
    qualified = acct.get(f"/api/leads/project/{pid}/table?status=qualified&per_page=200").json()
    assert qualified["total"] == 1
    assert qualified["items"][0]["id"] == items[0]["id"]
    # And "new" dropped by one.
    new_after = acct.get(f"/api/leads/project/{pid}/table?status=new&per_page=200").json()
    assert new_after["total"] == total - 1

    # Bogus status enum value → 422 (LeadStatus query param).
    assert acct.get(f"/api/leads/project/{pid}/table?status=nope").status_code == 422


def test_table_filter_has_phone_and_has_email(paid_account, stub_sources, new_project):
    acct = paid_account
    pid, items = _collect(acct, new_project)
    total = len(items)

    # Every stub lead has a phone.
    has_phone = acct.get(f"/api/leads/project/{pid}/table?has_phone=true&per_page=200").json()
    assert has_phone["total"] == total
    no_phone = acct.get(f"/api/leads/project/{pid}/table?has_phone=false&per_page=200").json()
    assert no_phone["total"] == 0

    # Auto-enrich fills info@domain → at least some leads have email; the two
    # partitions must sum to the total (mutually exclusive, exhaustive).
    with_email = acct.get(f"/api/leads/project/{pid}/table?has_email=true&per_page=200").json()
    without_email = acct.get(f"/api/leads/project/{pid}/table?has_email=false&per_page=200").json()
    assert with_email["total"] >= 1, "auto-enrich should fill at least one email"
    assert with_email["total"] + without_email["total"] == total
    # Every returned has_email=true row actually carries an email.
    assert all(it["email"] for it in with_email["items"])


def test_table_filter_score_range(paid_account, stub_sources, new_project):
    acct = paid_account
    pid, items = _collect(acct, new_project)
    scores = sorted(it["score"] for it in items)
    lo, hi = scores[0], scores[-1]

    # min_score below the floor returns everything.
    all_rows = acct.get(f"/api/leads/project/{pid}/table?min_score={lo}&per_page=200").json()
    assert all_rows["total"] == len(items)

    # max_score below the floor returns nothing (when there's a positive floor).
    if lo > 0:
        none_rows = acct.get(f"/api/leads/project/{pid}/table?max_score={lo - 1}&per_page=200").json()
        assert none_rows["total"] == 0

    # A bracket [lo, hi] returns everything; every row is within the bracket.
    bracket = acct.get(
        f"/api/leads/project/{pid}/table?min_score={lo}&max_score={hi}&per_page=200"
    ).json()
    assert bracket["total"] == len(items)
    assert all(lo <= it["score"] <= hi for it in bracket["items"])

    # Out-of-range score param → 422 (Query ge=0 le=100).
    assert acct.get(f"/api/leads/project/{pid}/table?min_score=101").status_code == 422
    assert acct.get(f"/api/leads/project/{pid}/table?max_score=-1").status_code == 422


def test_table_filter_q_substring(paid_account, stub_sources, new_project):
    acct = paid_account
    # Stub company names embed the unique run suffix → searchable substring.
    suffix = stub_sources["suffix"]
    pid, items = _collect(acct, new_project)
    total = len(items)

    # The suffix appears in every stub company name → matches all.
    by_suffix = acct.get(f"/api/leads/project/{pid}/table?q={suffix}&per_page=200").json()
    assert by_suffix["total"] == total

    # A substring that matches a single company (its index marker " 0 ").
    target = items[0]["company"]
    # Use the full unique company name → exactly one match.
    one = acct.get(f"/api/leads/project/{pid}/table?q={target}&per_page=200").json()
    assert one["total"] == 1
    assert one["items"][0]["company"] == target

    # A nonsense substring matches nothing.
    none = acct.get(f"/api/leads/project/{pid}/table?q=zzznomatchzzz&per_page=200").json()
    assert none["total"] == 0

    # q matches phone too (substring of the stubbed phone prefix).
    by_phone = acct.get(f"/api/leads/project/{pid}/table?q=%2B7%20495&per_page=200").json()
    assert by_phone["total"] == total


# ── Pagination: page / per_page, total stable ───────────────────────────────

def test_pagination_total_stable_pages_disjoint(paid_account, stub_sources, new_project):
    acct = paid_account
    stub_sources["n"] = 12
    pid, items = _collect(acct, new_project, lead_limit=12)
    total = len(items)
    assert total >= 6, f"need several leads to paginate, got {total}"

    per = 5
    p1 = acct.get(f"/api/leads/project/{pid}/table?page=1&per_page={per}&sort=score&order=desc").json()
    p2 = acct.get(f"/api/leads/project/{pid}/table?page=2&per_page={per}&sort=score&order=desc").json()

    # total is identical across pages.
    assert p1["total"] == total
    assert p2["total"] == total
    assert p1["page"] == 1 and p1["per_page"] == per
    assert p2["page"] == 2

    # per_page respected.
    assert len(p1["items"]) == per
    assert len(p2["items"]) == min(per, total - per)

    # Pages are disjoint.
    ids1 = {it["id"] for it in p1["items"]}
    ids2 = {it["id"] for it in p2["items"]}
    assert ids1.isdisjoint(ids2)

    # A page past the end is empty but total still reported.
    far = acct.get(f"/api/leads/project/{pid}/table?page=999&per_page={per}").json()
    assert far["total"] == total
    assert far["items"] == []


def test_pagination_param_validation(paid_account, stub_sources, new_project):
    acct = paid_account
    pid, _ = _collect(acct, new_project)
    # page must be >= 1.
    assert acct.get(f"/api/leads/project/{pid}/table?page=0").status_code == 422
    # per_page bounded 1..200.
    assert acct.get(f"/api/leads/project/{pid}/table?per_page=0").status_code == 422
    assert acct.get(f"/api/leads/project/{pid}/table?per_page=201").status_code == 422


# ── Sort: sort=score order=asc/desc ─────────────────────────────────────────

def test_sort_score_asc_desc(paid_account, stub_sources, new_project):
    acct = paid_account
    pid, items = _collect(acct, new_project)
    assert len(items) >= 2

    desc = acct.get(f"/api/leads/project/{pid}/table?sort=score&order=desc&per_page=200").json()
    asc = acct.get(f"/api/leads/project/{pid}/table?sort=score&order=asc&per_page=200").json()

    desc_scores = [it["score"] for it in desc["items"]]
    asc_scores = [it["score"] for it in asc["items"]]

    assert desc_scores == sorted(desc_scores, reverse=True), desc_scores
    assert asc_scores == sorted(asc_scores), asc_scores
    # Same multiset of scores, just reordered.
    assert sorted(desc_scores) == sorted(asc_scores)
    # Same set of leads in both orderings.
    assert {it["id"] for it in desc["items"]} == {it["id"] for it in asc["items"]}
    # Top of desc is the max score; top of asc is the min.
    assert desc_scores[0] == max(asc_scores)
    assert asc_scores[0] == min(desc_scores)


# ── Cross-cutting 404s ──────────────────────────────────────────────────────

def test_patch_and_detail_other_org_404(paid_account, make_account, stub_sources, new_project):
    acct = paid_account
    pid, lead_id = _first_lead(acct, new_project)
    other = make_account(plan="pro")
    assert other.get(f"/api/leads/{lead_id}").status_code == 404
    assert other.patch(f"/api/leads/{lead_id}", json={"status": "qualified"}).status_code == 404


def test_table_unknown_project_404(paid_account, stub_sources, new_project):
    acct = paid_account
    import uuid as _uuid
    missing = _uuid.uuid4()
    assert acct.get(f"/api/leads/project/{missing}/table").status_code == 404
