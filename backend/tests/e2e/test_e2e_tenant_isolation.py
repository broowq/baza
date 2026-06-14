"""TRUE E2E: cross-tenant isolation — the most important guard in a B2B SaaS.

Two independent orgs A (Pro, with collected leads) and B (Pro, empty). B is a
full owner of its OWN org, so every refusal below is multi-tenancy enforcement,
NOT a missing-auth or missing-role error. We sweep EVERY id-bearing endpoint
under /api/leads and /api/projects and assert:

  * reading/writing A's project as B  → 404 (project routes)
  * reading/writing A's lead as B      → 404 (lead routes)
  * 404 OPACITY: a resource that belongs to another org returns the SAME status
    as a resource that does not exist at all (no existence leak across tenants)
  * presenting B's valid token with A's org id in X-Org-Id → 403 (not a member)
  * a malformed X-Org-Id header → 400
  * A's own resources stay fully usable, and B never mutates A's data — the
    refusals are isolation, not a blanket outage.

Uses ONLY the proven conftest fixtures. No conftest changes.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.models import Lead, LeadCallNote


# ── shared two-org world ─────────────────────────────────────────────────────

def _seed_org_a(make_account, stub_sources, new_project):
    """Org A: Pro, one project, leads collected (eager). Returns (acct, pid, lead_id)."""
    a = make_account(plan="pro")
    project = new_project(a, niche="стоматология", geography="Москва")
    pid = project["id"]
    collect = a.post(f"/api/leads/project/{pid}/collect", json={"lead_limit": 10})
    assert collect.status_code in (200, 201), collect.text
    table = a.get(f"/api/leads/project/{pid}/table?per_page=50")
    assert table.status_code == 200, table.text
    items = table.json()["items"]
    assert items, "Org A must have at least one collected lead to test isolation against"
    return a, pid, items[0]["id"]


# ─────────────────────────────────────────────────────────────────────────────
# 1. PROJECT-SCOPED endpoints: A's project_id, accessed as B (B's own org) → 404
# ─────────────────────────────────────────────────────────────────────────────

def test_b_cannot_read_a_project_table(make_account, stub_sources, new_project):
    _a, pid, _lead = _seed_org_a(make_account, stub_sources, new_project)
    b = make_account(plan="pro")
    r = b.get(f"/api/leads/project/{pid}/table?per_page=50")
    assert r.status_code == 404, r.text
    # The body must NOT leak A's leads.
    assert "items" not in r.json() or not r.json().get("items")


def test_b_cannot_read_a_project_lead_list(make_account, stub_sources, new_project):
    _a, pid, _lead = _seed_org_a(make_account, stub_sources, new_project)
    b = make_account(plan="pro")
    r = b.get(f"/api/leads/project/{pid}")
    assert r.status_code == 404, r.text


def test_b_cannot_read_a_project_jobs(make_account, stub_sources, new_project):
    _a, pid, _lead = _seed_org_a(make_account, stub_sources, new_project)
    b = make_account(plan="pro")
    r = b.get(f"/api/leads/jobs/project/{pid}")
    assert r.status_code == 404, r.text


def test_b_cannot_read_a_project_stats(make_account, stub_sources, new_project):
    _a, pid, _lead = _seed_org_a(make_account, stub_sources, new_project)
    b = make_account(plan="pro")
    r = b.get(f"/api/leads/project/{pid}/stats")
    assert r.status_code == 404, r.text


def test_b_cannot_export_a_project_csv(make_account, stub_sources, new_project):
    _a, pid, _lead = _seed_org_a(make_account, stub_sources, new_project)
    b = make_account(plan="pro")
    r = b.get(f"/api/leads/project/{pid}/export")
    assert r.status_code == 404, r.text
    # A CSV body would have a text/csv content-type — must not be returned.
    assert "text/csv" not in r.headers.get("content-type", "")


def test_b_cannot_export_a_project_xlsx(make_account, stub_sources, new_project):
    _a, pid, _lead = _seed_org_a(make_account, stub_sources, new_project)
    b = make_account(plan="pro")
    r = b.get(f"/api/leads/project/{pid}/export.xlsx")
    assert r.status_code == 404, r.text
    assert "spreadsheet" not in r.headers.get("content-type", "")


def test_b_cannot_collect_into_a_project(make_account, stub_sources, new_project):
    """B is owner of B's org (role check passes) → the 404 is pure tenant scope."""
    _a, pid, _lead = _seed_org_a(make_account, stub_sources, new_project)
    b = make_account(plan="pro")
    r = b.post(f"/api/leads/project/{pid}/collect", json={"lead_limit": 10})
    assert r.status_code == 404, r.text


def test_b_cannot_enrich_a_project(make_account, stub_sources, new_project):
    _a, pid, _lead = _seed_org_a(make_account, stub_sources, new_project)
    b = make_account(plan="pro")
    r = b.post(f"/api/leads/project/{pid}/enrich", json={"lead_limit": 10})
    assert r.status_code == 404, r.text


def test_b_cannot_enrich_selected_in_a_project(make_account, stub_sources, new_project):
    _a, pid, a_lead = _seed_org_a(make_account, stub_sources, new_project)
    b = make_account(plan="pro")
    # Even passing a real lead id from A must not leak — project scope fails first.
    r = b.post(f"/api/leads/project/{pid}/enrich-selected", json={"lead_ids": [a_lead]})
    assert r.status_code == 404, r.text


def test_b_cannot_patch_a_project(make_account, stub_sources, new_project):
    _a, pid, _lead = _seed_org_a(make_account, stub_sources, new_project)
    b = make_account(plan="pro")
    r = b.patch(f"/api/projects/{pid}", json={"name": "Захвачено B"})
    assert r.status_code == 404, r.text


def test_b_cannot_delete_a_project(make_account, stub_sources, new_project, db):
    a, pid, _lead = _seed_org_a(make_account, stub_sources, new_project)
    b = make_account(plan="pro")
    r = b.delete(f"/api/projects/{pid}")
    assert r.status_code == 404, r.text
    # Project must still be live & visible to A (delete was a soft-delete no-op).
    assert a.get(f"/api/leads/project/{pid}/table").status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# 2. LEAD-SCOPED endpoints: A's lead_id, accessed as B (B's own org) → 404
# ─────────────────────────────────────────────────────────────────────────────

def test_b_cannot_read_a_lead_detail(make_account, stub_sources, new_project):
    _a, _pid, lead = _seed_org_a(make_account, stub_sources, new_project)
    b = make_account(plan="pro")
    r = b.get(f"/api/leads/{lead}")
    assert r.status_code == 404, r.text


def test_b_cannot_patch_a_lead(make_account, stub_sources, new_project):
    a, _pid, lead = _seed_org_a(make_account, stub_sources, new_project)
    b = make_account(plan="pro")
    r = b.patch(f"/api/leads/{lead}", json={"status": "rejected", "notes": "взломано"})
    assert r.status_code == 404, r.text
    # A's lead must be untouched.
    detail = a.get(f"/api/leads/{lead}").json()
    assert detail["status"] == "new"
    assert detail["notes"] != "взломано"


def test_b_cannot_read_a_lead_calls(make_account, stub_sources, new_project):
    _a, _pid, lead = _seed_org_a(make_account, stub_sources, new_project)
    b = make_account(plan="pro")
    r = b.get(f"/api/leads/{lead}/calls")
    assert r.status_code == 404, r.text


def test_b_cannot_add_call_to_a_lead(make_account, stub_sources, new_project, db):
    a, _pid, lead = _seed_org_a(make_account, stub_sources, new_project)
    b = make_account(plan="pro")
    r = b.post(f"/api/leads/{lead}/calls", json={"comment": "звонок от B"})
    assert r.status_code == 404, r.text
    # No note row leaked into the DB for this lead.
    notes = db.execute(select(LeadCallNote).where(LeadCallNote.lead_id == uuid.UUID(lead))).scalars().all()
    assert notes == []
    # A's lead status must NOT have flipped to "contacted" by B's phantom call.
    assert a.get(f"/api/leads/{lead}").json()["status"] == "new"


def test_b_cannot_delete_a_lead(make_account, stub_sources, new_project, db):
    a, _pid, lead = _seed_org_a(make_account, stub_sources, new_project)
    b = make_account(plan="pro")
    r = b.delete(f"/api/leads/{lead}")
    assert r.status_code == 404, r.text
    # The lead row must still exist and still be readable by A.
    assert db.get(Lead, uuid.UUID(lead)) is not None
    assert a.get(f"/api/leads/{lead}").status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# 3. 404 OPACITY: belongs-to-other-org === does-not-exist (no existence leak)
# ─────────────────────────────────────────────────────────────────────────────

def test_404_opacity_lead_other_org_matches_nonexistent(make_account, stub_sources, new_project):
    """A lead that belongs to A must look IDENTICAL to a lead that does not exist
    when probed by B — same status code, so B cannot enumerate A's ids."""
    _a, _pid, a_lead = _seed_org_a(make_account, stub_sources, new_project)
    b = make_account(plan="pro")
    ghost = str(uuid.uuid4())

    for path_tmpl in ("/api/leads/{}", "/api/leads/{}/calls"):
        belongs = b.get(path_tmpl.format(a_lead))
        absent = b.get(path_tmpl.format(ghost))
        assert belongs.status_code == absent.status_code == 404, (
            f"opacity break on {path_tmpl}: other-org={belongs.status_code} absent={absent.status_code}"
        )

    # Mutating routes too.
    assert (
        b.patch(f"/api/leads/{a_lead}", json={"status": "rejected"}).status_code
        == b.patch(f"/api/leads/{ghost}", json={"status": "rejected"}).status_code
        == 404
    )
    assert (
        b.delete(f"/api/leads/{a_lead}").status_code
        == b.delete(f"/api/leads/{ghost}").status_code
        == 404
    )
    assert (
        b.post(f"/api/leads/{a_lead}/calls", json={"comment": "x"}).status_code
        == b.post(f"/api/leads/{ghost}/calls", json={"comment": "x"}).status_code
        == 404
    )


def test_404_opacity_project_other_org_matches_nonexistent(make_account, stub_sources, new_project):
    _a, a_pid, _lead = _seed_org_a(make_account, stub_sources, new_project)
    b = make_account(plan="pro")
    ghost = str(uuid.uuid4())

    for path_tmpl in (
        "/api/leads/project/{}/table",
        "/api/leads/project/{}",
        "/api/leads/jobs/project/{}",
        "/api/leads/project/{}/export",
        "/api/leads/project/{}/stats",
    ):
        belongs = b.get(path_tmpl.format(a_pid))
        absent = b.get(path_tmpl.format(ghost))
        assert belongs.status_code == absent.status_code == 404, (
            f"opacity break on {path_tmpl}: other-org={belongs.status_code} absent={absent.status_code}"
        )

    assert (
        b.post(f"/api/leads/project/{a_pid}/collect", json={"lead_limit": 5}).status_code
        == b.post(f"/api/leads/project/{ghost}/collect", json={"lead_limit": 5}).status_code
        == 404
    )
    # name >= 2 chars so the body passes validation (422 would mask the 404).
    assert (
        b.patch(f"/api/projects/{a_pid}", json={"name": "xx"}).status_code
        == b.patch(f"/api/projects/{ghost}", json={"name": "xx"}).status_code
        == 404
    )
    assert (
        b.delete(f"/api/projects/{a_pid}").status_code
        == b.delete(f"/api/projects/{ghost}").status_code
        == 404
    )


# ─────────────────────────────────────────────────────────────────────────────
# 4. HEADER-LEVEL isolation: X-Org-Id spoofing & malformed header
# ─────────────────────────────────────────────────────────────────────────────

def test_b_token_with_a_org_id_in_header_is_403(make_account, stub_sources, new_project):
    """B presents a VALID token but A's org id in X-Org-Id → 403 (not a member).
    This is the auth-layer guard that backs the route-level 404 scoping."""
    a, _pid, _lead = _seed_org_a(make_account, stub_sources, new_project)
    b = make_account(plan="pro")
    # Override only X-Org-Id; B's own token still applies via b.headers.
    r = b.get("/api/organizations/me", headers={"X-Org-Id": a.org_id})
    assert r.status_code == 403, r.text


def test_b_token_with_a_org_id_blocks_project_and_lead_routes(make_account, stub_sources, new_project):
    """The same spoof against id-bearing routes is refused at the org dep (403),
    before any project/lead lookup runs — so it never even reaches the 404 path."""
    a, a_pid, a_lead = _seed_org_a(make_account, stub_sources, new_project)
    b = make_account(plan="pro")
    spoof = {"X-Org-Id": a.org_id}

    # Read paths under A's own ids but with B's token → membership check fails 403.
    assert b.get(f"/api/leads/project/{a_pid}/table", headers=spoof).status_code == 403
    assert b.get(f"/api/leads/{a_lead}", headers=spoof).status_code == 403
    # Write path: get_org_membership (role dep) also rejects with 403.
    assert b.post(
        f"/api/leads/project/{a_pid}/collect", json={"lead_limit": 5}, headers=spoof
    ).status_code == 403


def test_malformed_x_org_id_is_400(make_account):
    """A non-UUID X-Org-Id is a client error (400), distinct from 403/404."""
    b = make_account(plan="pro")
    r = b.get("/api/organizations/me", headers={"X-Org-Id": "not-a-uuid"})
    assert r.status_code == 400, r.text


def test_malformed_x_org_id_on_id_bearing_routes_is_400(make_account, stub_sources, new_project):
    """Even on lead/project routes the malformed-header 400 fires at the org dep,
    not a 404/422 from the route body."""
    a, a_pid, a_lead = _seed_org_a(make_account, stub_sources, new_project)
    b = make_account(plan="pro")
    bad = {"X-Org-Id": "12345-not-uuid"}
    assert b.get(f"/api/leads/project/{a_pid}/table", headers=bad).status_code == 400
    assert b.get(f"/api/leads/{a_lead}", headers=bad).status_code == 400
    assert b.get("/api/projects", headers=bad).status_code == 400


# ─────────────────────────────────────────────────────────────────────────────
# 5. Positive control + leak-direction symmetry
# ─────────────────────────────────────────────────────────────────────────────

def test_a_retains_full_access_to_own_resources(make_account, stub_sources, new_project):
    """Prove the isolation 404s are SCOPE, not an outage: A's owner can do
    everything B was refused, on the very same ids."""
    a, pid, lead = _seed_org_a(make_account, stub_sources, new_project)

    assert a.get(f"/api/leads/project/{pid}/table").status_code == 200
    assert a.get(f"/api/leads/jobs/project/{pid}").status_code == 200
    assert a.get(f"/api/leads/project/{pid}/stats").status_code == 200
    assert a.get(f"/api/leads/project/{pid}/export").status_code == 200
    assert a.get(f"/api/leads/{lead}").status_code == 200
    assert a.get(f"/api/leads/{lead}/calls").status_code == 200

    patched = a.patch(f"/api/leads/{lead}", json={"notes": "мой лид"})
    assert patched.status_code == 200, patched.text
    assert patched.json()["notes"] == "мой лид"


def test_isolation_is_symmetric_a_cannot_touch_b(make_account, stub_sources, new_project):
    """The wall blocks both directions: A also cannot see B's project/lead.
    B collects its own leads; A (a different Pro org) is shut out the same way."""
    a, _a_pid, _a_lead = _seed_org_a(make_account, stub_sources, new_project)

    b = make_account(plan="pro")
    b_project = new_project(b, niche="автосервис", geography="Казань")
    b_pid = b_project["id"]
    assert b.post(f"/api/leads/project/{b_pid}/collect", json={"lead_limit": 10}).status_code in (200, 201)
    b_items = b.get(f"/api/leads/project/{b_pid}/table?per_page=50").json()["items"]
    assert b_items, "Org B should have its own leads"
    b_lead = b_items[0]["id"]

    # A (the first org) is blocked from B's resources, exactly mirroring B→A.
    assert a.get(f"/api/leads/project/{b_pid}/table").status_code == 404
    assert a.get(f"/api/leads/{b_lead}").status_code == 404
    assert a.delete(f"/api/leads/{b_lead}").status_code == 404
    assert a.patch(f"/api/projects/{b_pid}", json={"name": "xx"}).status_code == 404

    # And B's data survived A's attempts intact.
    assert b.get(f"/api/leads/{b_lead}").status_code == 200
