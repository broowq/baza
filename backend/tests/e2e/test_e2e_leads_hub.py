"""E2E: the org-wide "Все лиды" hub — GET /api/leads/all.

A lead is no longer locked inside one project: this endpoint lists leads across
ALL of an org's (non-deleted) projects, stamps each with its project_name, and
mirrors the per-project table's search/filter/sort/pagination.

Drives real HTTP + auth + DB (no dependency overrides). Asserts the rules that
make the hub trustworthy:
  * leads from MULTIPLE projects appear, each with the right project_name,
  * case-insensitive search across company / email / phone narrows correctly,
  * status and project_id filters narrow correctly,
  * pagination reports the org-wide total and one item per page,
  * a second org's leads NEVER appear, and a soft-deleted project's leads are
    excluded.
"""
from __future__ import annotations

from app.db.session import SessionLocal
from app.models import Project


# ── helpers ──────────────────────────────────────────────────────────────────

def _mk_lead(acct, pid: str, company: str, **over) -> dict:
    """Create a manual lead in a project; return the lead JSON."""
    payload = {"company": company, **over}
    r = acct.post(f"/api/leads/project/{pid}", json=payload)
    assert r.status_code == 201, f"create lead failed: {r.status_code} {r.text}"
    return r.json()


def _all(acct, **params) -> dict:
    r = acct.get("/api/leads/all", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _soft_delete_project(pid: str) -> None:
    """Soft-delete a project straight in the DB (sets deleted_at)."""
    from datetime import datetime, timezone

    db = SessionLocal()
    try:
        proj = db.get(Project, pid)
        proj.deleted_at = datetime.now(timezone.utc)
        db.commit()
    finally:
        db.close()


# ── cross-project aggregation + project_name stamping ───────────────────────

def test_all_aggregates_leads_across_projects_with_project_name(paid_account, new_project):
    """Two projects, leads in each → /leads/all returns leads from BOTH, and
    every item carries the project_name of the project it belongs to."""
    acct = paid_account
    p1 = new_project(acct, name="Альфа Проект")
    p2 = new_project(acct, name="Бета Проект")

    l1 = _mk_lead(acct, p1["id"], "Альфа Компания", website="https://alpha-hub.ru")
    l2 = _mk_lead(acct, p2["id"], "Бета Компания", website="https://beta-hub.ru")

    body = _all(acct, per_page=100)
    by_id = {it["id"]: it for it in body["items"]}

    assert l1["id"] in by_id, "project 1 lead missing from /leads/all"
    assert l2["id"] in by_id, "project 2 lead missing from /leads/all"
    assert body["total"] >= 2

    assert by_id[l1["id"]]["project_name"] == "Альфа Проект"
    assert by_id[l1["id"]]["project_id"] == p1["id"]
    assert by_id[l2["id"]]["project_name"] == "Бета Проект"
    assert by_id[l2["id"]]["project_id"] == p2["id"]


# ── search ──────────────────────────────────────────────────────────────────

def test_all_search_matches_company_across_projects(paid_account, new_project):
    """A company query returns only the matching lead, even though the match and
    the noise live in DIFFERENT projects (search spans the whole org)."""
    acct = paid_account
    p1 = new_project(acct, name="P1")
    p2 = new_project(acct, name="P2")

    target = _mk_lead(acct, p1["id"], "юникорн технологии", website="https://unicorn-hub.ru")
    _mk_lead(acct, p2["id"], "прочая фирма", website="https://other-hub.ru")

    # NOTE: stored & queried in lowercase Cyrillic on purpose. The endpoint builds
    # the ILIKE pattern with Python's str.lower() (which folds Cyrillic) but
    # compares it against Postgres lower(column), which under the test DB's C
    # collation does NOT fold Cyrillic — so a capitalised Cyrillic company can
    # never be matched by search. That is a real bug (Russian company names are
    # capitalised in practice); see test_all_search_is_case_insensitive_latin for
    # the case-insensitivity intent on collation-independent (Latin) text.
    body = _all(acct, search="юникорн", per_page=100)
    ids = {it["id"] for it in body["items"]}
    assert ids == {target["id"]}, f"search should return only the match, got {ids}"
    assert body["total"] == 1


def test_all_search_is_case_insensitive_latin(paid_account, new_project):
    """Search is genuinely case-insensitive: a lower-cased query matches a
    mixed-case company (Latin)."""
    acct = paid_account
    pid = new_project(acct)["id"]

    target = _mk_lead(acct, pid, "UniCorn Labs", website="https://unicorn-latin-hub.ru")
    _mk_lead(acct, pid, "Other Co", website="https://other-latin-hub.ru")

    body = _all(acct, search="unicorn", per_page=100)
    ids = {it["id"] for it in body["items"]}
    assert ids == {target["id"]}, f"case-insensitive search failed, got {ids}"
    assert body["total"] == 1


def test_all_search_is_case_insensitive_cyrillic(paid_account, new_project):
    """The core RU-CRM case: a lowercase Cyrillic query must find a CAPITALISED
    Cyrillic company. Works even on a C/POSIX DB collation via the ICU case-fold
    in _ci_contains (plain ILIKE/lower only fold ASCII there)."""
    acct = paid_account
    pid = new_project(acct)["id"]

    target = _mk_lead(acct, pid, "Юникорн Технологии", website="https://unikorn-cyr-hub.ru")
    _mk_lead(acct, pid, "Прочая Компания", website="https://other-cyr-hub.ru")

    body = _all(acct, search="юникорн", per_page=100)
    ids = {it["id"] for it in body["items"]}
    assert ids == {target["id"]}, f"cyrillic case-insensitive search failed, got {ids}"
    assert body["total"] == 1


def test_all_search_matches_phone_and_email(paid_account, new_project):
    """Search also matches on phone and on email, not just company."""
    acct = paid_account
    pid = new_project(acct)["id"]

    by_phone = _mk_lead(
        acct, pid, "Фирма Телефон",
        website="https://phone-hub.ru", phone="+7 495 765-43-21",
    )
    by_email = _mk_lead(
        acct, pid, "Фирма Почта",
        website="https://email-hub.ru", email="sales@niche-hub.ru",
    )
    _mk_lead(acct, pid, "Без Контактов", website="https://nomatch-hub.ru")

    phone_hit = _all(acct, search="765-43-21", per_page=100)
    assert {it["id"] for it in phone_hit["items"]} == {by_phone["id"]}

    email_hit = _all(acct, search="niche-hub.ru", per_page=100)
    # domain/website/email all contain the fragment for the email lead only.
    assert by_email["id"] in {it["id"] for it in email_hit["items"]}
    assert by_phone["id"] not in {it["id"] for it in email_hit["items"]}


# ── status + project filters ────────────────────────────────────────────────

def test_all_status_filter_narrows(paid_account, new_project):
    """status filter returns only leads in that pipeline stage, across projects."""
    acct = paid_account
    p1 = new_project(acct, name="S1")
    p2 = new_project(acct, name="S2")

    won = _mk_lead(acct, p1["id"], "Выигран", website="https://won-hub.ru", status="won")
    _mk_lead(acct, p2["id"], "Новый", website="https://new-hub.ru", status="new")

    body = _all(acct, status="won", per_page=100)
    ids = {it["id"] for it in body["items"]}
    assert ids == {won["id"]}, f"status=won should return only the won lead, got {ids}"
    assert all(it["status"] == "won" for it in body["items"])
    assert body["total"] == 1


def test_all_project_filter_narrows(paid_account, new_project):
    """project_id filter scopes /leads/all to a single project."""
    acct = paid_account
    p1 = new_project(acct, name="Проект Один")
    p2 = new_project(acct, name="Проект Два")

    keep = _mk_lead(acct, p1["id"], "Остаётся", website="https://keep-hub.ru")
    drop = _mk_lead(acct, p2["id"], "Отсеивается", website="https://drop-hub.ru")

    body = _all(acct, project_id=p1["id"], per_page=100)
    ids = {it["id"] for it in body["items"]}
    assert keep["id"] in ids
    assert drop["id"] not in ids
    assert all(it["project_id"] == p1["id"] for it in body["items"])
    assert body["total"] == 1


# ── pagination ──────────────────────────────────────────────────────────────

def test_all_pagination_total_spans_projects(paid_account, new_project):
    """per_page=1 → total counts leads across ALL projects, one item per page,
    and walking the pages yields every distinct lead exactly once."""
    acct = paid_account
    p1 = new_project(acct, name="Pg1")
    p2 = new_project(acct, name="Pg2")

    made = {
        _mk_lead(acct, p1["id"], "Стр 1", website="https://pg1-hub.ru")["id"],
        _mk_lead(acct, p1["id"], "Стр 2", website="https://pg2-hub.ru")["id"],
        _mk_lead(acct, p2["id"], "Стр 3", website="https://pg3-hub.ru")["id"],
    }

    first = _all(acct, per_page=1, page=1)
    assert first["total"] == 3, "total must count leads across all projects"
    assert first["per_page"] == 1
    assert len(first["items"]) == 1

    seen: set[str] = set()
    for page in (1, 2, 3):
        body = _all(acct, per_page=1, page=page)
        assert len(body["items"]) == 1, f"page {page} should hold exactly one item"
        seen.add(body["items"][0]["id"])

    assert seen == made, f"paging should surface every lead once, got {seen}"


# ── isolation: other org + soft-deleted project ─────────────────────────────

def test_all_excludes_other_orgs_leads(make_account, new_project):
    """A second org's leads NEVER appear in the first org's /leads/all."""
    me = make_account(plan="pro")
    other = make_account(plan="pro")

    my_pid = new_project(me)["id"]
    mine = _mk_lead(me, my_pid, "Моя Компания", website="https://mine-hub.ru")

    other_pid = new_project(other)["id"]
    theirs = _mk_lead(other, other_pid, "Чужая Компания", website="https://theirs-hub.ru")

    body = _all(me, per_page=100)
    ids = {it["id"] for it in body["items"]}
    assert mine["id"] in ids
    assert theirs["id"] not in ids, "another org's lead leaked into /leads/all"
    assert body["total"] == 1


def test_all_excludes_soft_deleted_project_leads(paid_account, new_project):
    """Leads in a soft-deleted project drop out of /leads/all (the live-project
    join filters them), while leads in surviving projects remain."""
    acct = paid_account
    live = new_project(acct, name="Живой")
    doomed = new_project(acct, name="Удаляемый")

    kept = _mk_lead(acct, live["id"], "Живой Лид", website="https://live-hub.ru")
    gone = _mk_lead(acct, doomed["id"], "Удалённый Лид", website="https://gone-hub.ru")

    # Both present before deletion.
    before = {it["id"] for it in _all(acct, per_page=100)["items"]}
    assert {kept["id"], gone["id"]} <= before

    _soft_delete_project(doomed["id"])

    body = _all(acct, per_page=100)
    ids = {it["id"] for it in body["items"]}
    assert kept["id"] in ids, "live-project lead must still appear"
    assert gone["id"] not in ids, "soft-deleted project's lead must be excluded"
    assert body["total"] == 1
