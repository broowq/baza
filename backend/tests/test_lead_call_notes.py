"""Tests for the lead call journal (who called + comment).

Covers: create (attributed to the current user, side effects on the lead),
list (newest first), org isolation (404 across orgs), comment validation.
Hits the real local Postgres like the other endpoint tests.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.api.deps import get_current_org, get_current_user
from app.db.session import SessionLocal, get_db
from app.main import app
from app.models import (
    Lead,
    LeadCallNote,
    LeadStatus,
    Organization,
    Project,
    User,
)

_PFX = "calltest-"
_client = TestClient(app)


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    import app.main as main

    monkeypatch.setattr(main, "_get_rate_limit", lambda *a, **k: None)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def env(db):
    """Org + project + lead + persisted user, wired to the API.

    The user must be a real DB row: POST /calls writes user_id as an FK.
    """
    org = Organization(name=f"{_PFX}org-{uuid.uuid4().hex[:8]}")
    other_org = Organization(name=f"{_PFX}org2-{uuid.uuid4().hex[:8]}")
    db.add_all([org, other_org])
    db.flush()
    user = User(
        email=f"{_PFX}{uuid.uuid4().hex[:8]}@t.ru",
        full_name="Мария Продажи",
        hashed_password="x",
    )
    db.add(user)
    db.flush()
    project = Project(
        organization_id=org.id, name=f"{_PFX}proj", niche="окна", geography="Томск", segments=[]
    )
    db.add(project)
    db.flush()
    lead = Lead(
        organization_id=org.id,
        project_id=project.id,
        company="Колл Тест",
        website="",
        status=LeadStatus.new,
    )
    db.add(lead)
    db.commit()

    state = {"org_id": org.id}

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_org] = lambda: db.get(Organization, state["org_id"])
    app.dependency_overrides[get_current_user] = lambda: db.get(User, user.id)
    try:
        yield _client, state, lead, other_org.id
    finally:
        app.dependency_overrides.clear()
        db.rollback()
        db.execute(delete(LeadCallNote).where(LeadCallNote.lead_id == lead.id))
        db.execute(delete(Lead).where(Lead.id == lead.id))
        db.execute(delete(Project).where(Project.id == project.id))
        db.execute(delete(User).where(User.id == user.id))
        db.execute(delete(Organization).where(Organization.id.in_([org.id, other_org.id])))
        db.commit()


def test_add_call_note_attributes_caller_and_marks_contacted(env, db):
    client, state, lead, _ = env
    resp = client.post(f"/api/leads/{lead.id}/calls", json={"comment": "ЛПР занят, перезвонить в четверг"})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user_name"] == "Мария Продажи"
    assert body["comment"] == "ЛПР занят, перезвонить в четверг"

    db.refresh(lead)
    assert lead.last_contacted_at is not None, "call must stamp last_contacted_at"
    assert lead.status == LeadStatus.contacted, "new lead moves to contacted after a call"


def test_call_note_comment_optional_and_status_not_downgraded(env, db):
    client, state, lead, _ = env
    lead.status = LeadStatus.qualified
    db.commit()
    resp = client.post(f"/api/leads/{lead.id}/calls", json={})
    assert resp.status_code == 201, resp.text
    assert resp.json()["comment"] == ""
    db.refresh(lead)
    assert lead.status == LeadStatus.qualified, "qualified must not regress to contacted"


def test_list_call_notes_newest_first(env):
    client, state, lead, _ = env
    for i in (1, 2, 3):
        assert client.post(f"/api/leads/{lead.id}/calls", json={"comment": f"звонок {i}"}).status_code == 201
    resp = client.get(f"/api/leads/{lead.id}/calls")
    assert resp.status_code == 200
    comments = [n["comment"] for n in resp.json()]
    assert comments == ["звонок 3", "звонок 2", "звонок 1"]
    assert all(n["user_name"] == "Мария Продажи" for n in resp.json())


def test_call_notes_org_isolation(env):
    client, state, lead, other_org_id = env
    # Switch the caller's org → both routes must 404 (opaque).
    state["org_id"] = other_org_id
    assert client.get(f"/api/leads/{lead.id}/calls").status_code == 404
    assert client.post(f"/api/leads/{lead.id}/calls", json={"comment": "x"}).status_code == 404


def test_call_note_comment_too_long_rejected(env):
    client, state, lead, _ = env
    resp = client.post(f"/api/leads/{lead.id}/calls", json={"comment": "х" * 2001})
    assert resp.status_code == 422
