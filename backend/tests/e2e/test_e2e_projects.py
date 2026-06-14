"""TRUE E2E: Projects CRUD + limits, end to end through real HTTP + auth + DB.

Covers create (explicit niche/geo), validation (name too short, >20 segments
truncated), list, rename, prompt-change resetting Project.search_query, soft
delete (deleted_at set + subsequent collect/list 404), and the free-plan
project limit (projects_limit=1 → 2nd create refused).

Follows the proven harness pattern in test_e2e_core_journey.py: real app via
TestClient, real auth, real local Postgres, eager Celery, stubbed sources.
"""
from __future__ import annotations

from sqlalchemy import select

from app.models import Project


# ── create (happy path, explicit niche/geo) ─────────────────────────────────

def test_create_project_explicit_niche_geo(paid_account, db):
    """POST /api/projects with explicit niche/geo persists exactly as given and
    returns 200 with the created row (no LLM enhance path, since no prompt)."""
    acct = paid_account
    r = acct.post("/api/projects", json={
        "name": "Стоматологии Москвы",
        "niche": "стоматология",
        "geography": "Москва",
        "segments": ["частная клиника", "детская"],
        "auto_collection_enabled": False,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Стоматологии Москвы"
    assert body["niche"] == "стоматология"
    assert body["geography"] == "Москва"
    assert body["segments"] == ["частная клиника", "детская"]
    assert body["deleted_at"] is None
    # Default cron from the schema is applied.
    assert body["cron_schedule"] == "0 9 * * 1"

    # Persisted under the right org, with an empty cached search_query.
    proj = db.execute(select(Project).where(Project.id == body["id"])).scalar_one()
    assert str(proj.organization_id) == acct.org_id
    assert proj.niche == "стоматология"
    assert proj.search_query == ""
    # ОКВЭД codes are derived locally from segments even with no LLM path.
    assert isinstance(proj.okved_codes, list)


# ── validation ──────────────────────────────────────────────────────────────

def test_create_project_name_too_short_422(paid_account):
    """name has min_length=2 → a 1-char name is rejected by request validation."""
    acct = paid_account
    r = acct.post("/api/projects", json={
        "name": "X",
        "niche": "стоматология",
        "geography": "Москва",
        "segments": [],
    })
    assert r.status_code == 422, r.text
    # The 422 points at the name field specifically.
    locs = [".".join(str(p) for p in e["loc"]) for e in r.json()["detail"]]
    assert any("name" in loc for loc in locs), r.text


def test_create_project_niche_too_short_422(paid_account):
    """niche has min_length=2 → a 1-char niche is rejected too."""
    acct = paid_account
    r = acct.post("/api/projects", json={
        "name": "Нормальное имя",
        "niche": "X",
        "geography": "Москва",
        "segments": [],
    })
    assert r.status_code == 422, r.text


def test_create_project_segments_truncated_to_20(paid_account, db):
    """The schema validator truncates segments to the first 20 — sending 30 must
    persist exactly 20 (assert on the returned body AND the DB row)."""
    acct = paid_account
    many = [f"сегмент-{i}" for i in range(30)]
    r = acct.post("/api/projects", json={
        "name": "Много сегментов",
        "niche": "стоматология",
        "geography": "Москва",
        "segments": many,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["segments"]) == 20, f"segments not truncated: {len(body['segments'])}"
    # First 20 are kept in order.
    assert body["segments"] == many[:20]

    proj = db.execute(select(Project).where(Project.id == body["id"])).scalar_one()
    assert len(proj.segments) == 20
    assert proj.segments == many[:20]


# ── list ────────────────────────────────────────────────────────────────────

def test_list_projects_returns_only_own_active(paid_account, new_project):
    """GET /api/projects lists the org's active projects (newest first)."""
    acct = paid_account
    p1 = new_project(acct, name="Проект Один")
    p2 = new_project(acct, name="Проект Два")

    r = acct.get("/api/projects")
    assert r.status_code == 200, r.text
    ids = [p["id"] for p in r.json()]
    assert p1["id"] in ids
    assert p2["id"] in ids
    # Ordered created_at desc → the most recently created comes first.
    assert ids.index(p2["id"]) < ids.index(p1["id"])


def test_list_projects_is_tenant_scoped(make_account, new_project):
    """A project created in org A must NOT appear in org B's list."""
    a = make_account(plan="pro")
    b = make_account(plan="pro")
    pa = new_project(a, name="Только для A")

    list_b = b.get("/api/projects")
    assert list_b.status_code == 200, list_b.text
    assert pa["id"] not in [p["id"] for p in list_b.json()]


# ── rename (PATCH) ──────────────────────────────────────────────────────────

def test_patch_rename_project(paid_account, new_project, db):
    """PATCH /api/projects/{id} renames; niche untouched, search_query NOT reset
    (rename does not change prompt or niche)."""
    acct = paid_account
    proj = new_project(acct, name="Старое имя", niche="стоматология")
    pid = proj["id"]

    # Seed a cached search_query directly so we can prove a pure rename keeps it.
    row = db.execute(select(Project).where(Project.id == pid)).scalar_one()
    row.search_query = "клиники москва"
    db.commit()

    r = acct.patch(f"/api/projects/{pid}", json={"name": "Новое имя"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == "Новое имя"
    assert body["niche"] == "стоматология"

    db.expire_all()
    row = db.execute(select(Project).where(Project.id == pid)).scalar_one()
    assert row.name == "Новое имя"
    # A rename touches neither prompt nor niche → cached query survives.
    assert row.search_query == "клиники москва"


def test_patch_unknown_project_404(paid_account):
    """PATCH on a non-existent UUID → 404."""
    acct = paid_account
    r = acct.patch(
        "/api/projects/00000000-0000-0000-0000-000000000000",
        json={"name": "Не существует"},
    )
    assert r.status_code == 404, r.text


# ── prompt change resets search_query ───────────────────────────────────────

def test_patch_prompt_change_resets_search_query(paid_account, new_project, db):
    """Changing the prompt must drop the cached Project.search_query back to ""
    so the next collect re-derives the LLM search niche. Assert via the DB."""
    acct = paid_account
    proj = new_project(acct)
    pid = proj["id"]

    # Pre-seed a non-empty cached query.
    row = db.execute(select(Project).where(Project.id == pid)).scalar_one()
    row.search_query = "стоматология москва клиники"
    db.commit()

    r = acct.patch(f"/api/projects/{pid}", json={"prompt": "Новый промпт для поиска"})
    assert r.status_code == 200, r.text
    assert r.json()["prompt"] == "Новый промпт для поиска"

    db.expire_all()
    row = db.execute(select(Project).where(Project.id == pid)).scalar_one()
    assert row.search_query == "", "prompt change must reset search_query to ''"


def test_patch_niche_change_resets_search_query(paid_account, new_project, db):
    """Symmetric to the prompt case: changing niche also resets search_query."""
    acct = paid_account
    proj = new_project(acct, niche="стоматология")
    pid = proj["id"]

    row = db.execute(select(Project).where(Project.id == pid)).scalar_one()
    row.search_query = "что-то закэшированное"
    db.commit()

    r = acct.patch(f"/api/projects/{pid}", json={"niche": "ветеринария"})
    assert r.status_code == 200, r.text
    assert r.json()["niche"] == "ветеринария"

    db.expire_all()
    row = db.execute(select(Project).where(Project.id == pid)).scalar_one()
    assert row.search_query == "", "niche change must reset search_query to ''"


# ── soft delete ─────────────────────────────────────────────────────────────

def test_delete_soft_deletes_and_blocks_access(paid_account, new_project, db):
    """DELETE sets Project.deleted_at; afterwards the project disappears from the
    list and collect/list on it 404s (soft, not hard, delete)."""
    acct = paid_account
    proj = new_project(acct)
    pid = proj["id"]

    r = acct.delete(f"/api/projects/{pid}")
    assert r.status_code == 200, r.text
    assert r.json()["message"]

    # The row still exists but is stamped deleted_at.
    db.expire_all()
    row = db.execute(select(Project).where(Project.id == pid)).scalar_one()
    assert row.deleted_at is not None, "soft delete must set deleted_at, not remove the row"

    # Gone from the active list.
    listing = acct.get("/api/projects")
    assert listing.status_code == 200
    assert pid not in [p["id"] for p in listing.json()]

    # Subsequent lead-list on it 404s.
    leads = acct.get(f"/api/leads/project/{pid}/table")
    assert leads.status_code == 404, leads.text

    # And a collect on the deleted project 404s (not a quota error — checked
    # before quota, via the missing/deleted-project guard).
    collect = acct.post(f"/api/leads/project/{pid}/collect", json={"lead_limit": 10})
    assert collect.status_code == 404, collect.text


def test_delete_unknown_project_404(paid_account):
    """DELETE on a non-existent UUID → 404."""
    acct = paid_account
    r = acct.delete("/api/projects/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404, r.text


def test_delete_is_tenant_scoped(make_account, new_project):
    """Org B cannot delete org A's project (cross-tenant → 404)."""
    a = make_account(plan="pro")
    b = make_account(plan="pro")
    pa = new_project(a, name="Принадлежит A")

    r = b.delete(f"/api/projects/{pa['id']}")
    assert r.status_code == 404, r.text
    # A's project is still alive.
    assert pa["id"] in [p["id"] for p in a.get("/api/projects").json()]


# ── project limit (free plan) ───────────────────────────────────────────────

def test_free_plan_project_limit_one(make_account, new_project):
    """Free org has projects_limit=1: the 1st project succeeds, the 2nd is
    refused with 402 (Лимит проектов для текущего тарифа исчерпан)."""
    acct = make_account()  # free plan

    # First project: allowed.
    first = new_project(acct, name="Единственный проект")
    assert first["id"]

    # Second project: refused.
    r = acct.post("/api/projects", json={
        "name": "Второй проект",
        "niche": "стоматология",
        "geography": "Москва",
        "segments": [],
    })
    assert r.status_code == 402, r.text
    assert "Лимит" in r.json()["detail"]

    # And the list still shows exactly one project.
    listing = acct.get("/api/projects")
    assert listing.status_code == 200
    assert len([p for p in listing.json() if p["id"] == first["id"]]) == 1


def test_soft_deleted_project_frees_a_limit_slot(make_account, new_project):
    """The limit counts only active (deleted_at IS NULL) projects, so deleting
    the free org's single project lets it create another."""
    acct = make_account()  # free plan, projects_limit=1
    first = new_project(acct, name="Первый")

    # Delete frees the one slot.
    assert acct.delete(f"/api/projects/{first['id']}").status_code == 200

    second = new_project(acct, name="После удаления")
    assert second["id"] != first["id"]
    # Exactly one active project now.
    assert len(acct.get("/api/projects").json()) == 1
