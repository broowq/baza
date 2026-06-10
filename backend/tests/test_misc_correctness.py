"""Tests for verified audit fixes (misc correctness).

Covers:
  * POST /organizations/invites/accept — a valid, future-dated invite must NOT
    500. The columns are `timestamp without time zone`, so psycopg2 returns
    NAIVE datetimes; the old naive-vs-aware comparison raised TypeError on
    EVERY accept. Also: an expired invite returns 410 (not 500).
  * get_current_org / get_org_membership without X-Org-Id — a user with
    SEVERAL memberships must get a deterministic org (the old
    scalar_one_or_none raised MultipleResultsFound → 500); zero memberships
    still 403s.
  * LeadWarehouseRef — must not expose `other_niches` (other organizations'
    search niches, a cross-tenant leak).

These hit the real local Postgres like the other endpoint tests. Each test
creates and removes its own rows, so they're independent and rerunnable.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.api.deps import get_current_org, get_current_user, get_org_membership
from app.db.session import SessionLocal, get_db
from app.main import app
from app.models import ActionLog, Invite, Membership, Organization, User

_PFX = "misctest-"

# Single shared client for the module (no lifespan; the `with` form would
# open+close an event loop per use and break on reuse — see other test files).
_client = TestClient(app)


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    import app.main as main

    monkeypatch.setattr(main, "_get_rate_limit", lambda path: None)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


# ── invite accept: naive expires_at must not 500 ────────────────────────────

@pytest.fixture
def invite_env(db):
    """Org + accepting user (real DB row: log_action writes user_id FK) +
    pending invite addressed to that user. Yields (client, user, invite)."""
    org = Organization(name=f"{_PFX}org-{uuid.uuid4().hex[:8]}")
    db.add(org)
    db.flush()
    user = User(
        email=f"{_PFX}{uuid.uuid4().hex[:8]}@t.ru",
        full_name="Приглашённый",
        hashed_password="x",
    )
    db.add(user)
    db.flush()
    invite = Invite(
        organization_id=org.id,
        email=user.email,
        role="member",
        token=f"{_PFX}{uuid.uuid4().hex}",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.add(invite)
    db.commit()

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: db.get(User, user.id)
    try:
        yield _client, user, invite
    finally:
        app.dependency_overrides.clear()
        db.rollback()
        db.execute(delete(ActionLog).where(ActionLog.organization_id == org.id))
        db.execute(delete(Membership).where(Membership.organization_id == org.id))
        db.execute(delete(Invite).where(Invite.id == invite.id))
        db.execute(delete(User).where(User.id == user.id))
        db.execute(delete(Organization).where(Organization.id == org.id))
        db.commit()


def test_accept_invite_with_future_expiry_does_not_500(invite_env, db):
    """The DB returns a NAIVE expires_at; comparing it against an aware
    datetime.now(timezone.utc) raised TypeError → 500 on EVERY accept."""
    client, user, invite = invite_env
    # Sanity: the round-tripped value is naive (timestamp without time zone).
    db.expire_all()
    stored = db.get(Invite, invite.id)
    assert stored.expires_at.tzinfo is None, "precondition: DB returns naive datetimes"

    resp = client.post("/api/organizations/invites/accept", json={"token": invite.token})
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == str(invite.organization_id)
    # Membership actually created and the invite consumed.
    db.expire_all()
    membership = db.execute(
        select(Membership).where(
            Membership.organization_id == invite.organization_id,
            Membership.user_id == user.id,
        )
    ).scalar_one_or_none()
    assert membership is not None, "accept must create the membership"
    assert db.get(Invite, invite.id).accepted is True


def test_accept_expired_invite_returns_410_not_500(invite_env, db):
    client, user, invite = invite_env
    db.get(Invite, invite.id).expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    db.commit()
    resp = client.post("/api/organizations/invites/accept", json={"token": invite.token})
    assert resp.status_code == 410, resp.text


# ── deps: multi-org user without X-Org-Id ────────────────────────────────────

@pytest.fixture
def multi_org_user(db):
    """User who belongs to THREE orgs. Yields (user, {org_id: membership})."""
    user = User(
        email=f"{_PFX}{uuid.uuid4().hex[:8]}@t.ru",
        full_name="Мульти Орг",
        hashed_password="x",
    )
    orgs = [Organization(name=f"{_PFX}morg{i}-{uuid.uuid4().hex[:8]}") for i in range(3)]
    db.add(user)
    db.add_all(orgs)
    db.flush()
    memberships = [
        Membership(organization_id=org.id, user_id=user.id, role="member") for org in orgs
    ]
    db.add_all(memberships)
    db.commit()
    try:
        yield user, {m.organization_id: m for m in memberships}
    finally:
        db.rollback()
        db.execute(delete(Membership).where(Membership.user_id == user.id))
        db.execute(delete(User).where(User.id == user.id))
        db.execute(delete(Organization).where(Organization.id.in_([o.id for o in orgs])))
        db.commit()


def test_get_current_org_multi_membership_is_deterministic(db, multi_org_user):
    """scalar_one_or_none raised MultipleResultsFound (500) for multi-org users.
    Now: the membership with the smallest id wins, every time."""
    user, by_org = multi_org_user
    expected_org_id = min(by_org.values(), key=lambda m: m.id).organization_id

    results = {get_current_org(x_org_id=None, user=user, db=db).id for _ in range(5)}
    assert results == {expected_org_id}, "same (lowest-membership-id) org on every call"


def test_get_org_membership_multi_membership_is_deterministic(db, multi_org_user):
    user, by_org = multi_org_user
    expected_id = min(m.id for m in by_org.values())
    results = {get_org_membership(x_org_id=None, user=user, db=db).id for _ in range(5)}
    assert results == {expected_id}


def test_get_current_org_zero_memberships_403(db):
    user = User(
        email=f"{_PFX}{uuid.uuid4().hex[:8]}@t.ru",
        full_name="Без Орг",
        hashed_password="x",
    )
    db.add(user)
    db.commit()
    try:
        with pytest.raises(HTTPException) as exc:
            get_current_org(x_org_id=None, user=user, db=db)
        assert exc.value.status_code == 403
        with pytest.raises(HTTPException) as exc:
            get_org_membership(x_org_id=None, user=user, db=db)
        assert exc.value.status_code == 403
    finally:
        db.execute(delete(User).where(User.id == user.id))
        db.commit()


def test_get_current_org_x_org_id_path_unchanged(db, multi_org_user):
    """With an explicit X-Org-Id the user gets exactly that org."""
    user, by_org = multi_org_user
    for org_id in by_org:
        org = get_current_org(x_org_id=str(org_id), user=user, db=db)
        assert org.id == org_id


# ── schema: no cross-tenant niche leak ───────────────────────────────────────

def test_lead_warehouse_ref_has_no_other_niches_field():
    """Warehouse niches are other organizations' search intents (go-to-market
    data) — the schema must not expose them. sources/categories are public."""
    from app.schemas.leads import LeadWarehouseRef

    assert "other_niches" not in LeadWarehouseRef.model_fields
    assert "sources" in LeadWarehouseRef.model_fields
    assert "categories" in LeadWarehouseRef.model_fields
