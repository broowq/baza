"""Regression tests for the daily periodic tasks (app/tasks/periodic.py).

Locks in two data-integrity fixes:
  * send_reminder_emails — must clear reminder_at ONLY on the ≤50 leads that
    actually made it into the (capped) digest email. Leads 51+ keep their
    reminder so they resurface tomorrow instead of being silently dropped.
  * purge_old_leads — GDPR/152-ФЗ retention must delete by *inactivity*
    (Lead.updated_at), not by creation date, so a recently-worked old lead
    is kept while a long-dormant one is removed.

Like the warehouse tests, these hit the real local Postgres via SessionLocal
and clean up their own rows. The periodic tasks open their own session, so the
test commits its setup, runs the task, then expire_all() to observe the result.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.models import (
    Lead,
    LeadStatus,
    Membership,
    Organization,
    PlanType,
    Project,
    User,
)

_PFX = "pertest-"


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _mk_lead(org_id, project_id, suffix, **overrides):
    base = dict(
        organization_id=org_id,
        project_id=project_id,
        company=f"{_PFX}{suffix}",
        city="Томск",
        website=f"https://{_PFX}{suffix}.ru",  # (project_id, website) is unique
        source="2gis",
        status=LeadStatus.new,
        score=10,
    )
    base.update(overrides)
    return Lead(**base)


def test_reminder_digest_keeps_leads_beyond_50(db, monkeypatch):
    """55 due reminders → digest emails the first 50 and clears only those 50;
    the remaining 5 keep reminder_at so they aren't silently lost."""
    import app.services.notifications as notif
    from app.tasks import periodic

    now = datetime.now(timezone.utc)
    org = Organization(name=f"{_PFX}org-{uuid.uuid4().hex[:6]}", plan=PlanType.pro)
    db.add(org)
    db.flush()
    user = User(
        email=f"{_PFX}{uuid.uuid4().hex[:8]}@example.test",
        full_name="Owner",
        hashed_password="x",
    )
    db.add(user)
    db.flush()
    db.add(Membership(organization_id=org.id, user_id=user.id, role="owner"))
    proj = Project(
        organization_id=org.id, name=f"{_PFX}p",
        niche="x", geography="Томск", segments=[], prompt="",
    )
    db.add(proj)
    db.flush()

    n = 55
    for i in range(n):
        db.add(_mk_lead(org.id, proj.id, f"co{i}", reminder_at=now - timedelta(hours=1)))
    db.commit()

    sent: list[tuple] = []
    monkeypatch.setattr(notif, "send_email", lambda subject, body, to: sent.append((subject, to)))

    try:
        periodic.send_reminder_emails()
        db.expire_all()
        rows = db.execute(select(Lead).where(Lead.project_id == proj.id)).scalars().all()
        cleared = [l for l in rows if l.reminder_at is None]
        still = [l for l in rows if l.reminder_at is not None]
        assert len(cleared) == 50, "exactly the 50 emailed leads get reminder_at cleared"
        assert len(still) == n - 50, "leads beyond the 50-cap keep their reminder (not lost)"
        assert any(to == user.email for _, to in sent), "digest is emailed to the org owner"
    finally:
        db.rollback()
        db.execute(delete(Lead).where(Lead.project_id == proj.id))
        db.execute(delete(Project).where(Project.id == proj.id))
        db.execute(delete(Membership).where(Membership.organization_id == org.id))
        db.execute(delete(Organization).where(Organization.id == org.id))
        db.execute(delete(User).where(User.id == user.id))
        db.commit()


def test_purge_deletes_by_inactivity_not_creation(db):
    """Both leads are created 'now'; only updated_at differs. With a 30-day
    retention, the lead last touched 40 days ago is purged and the one touched
    5 days ago is kept — proving the purge keys on updated_at, not created_at."""
    from app.tasks import periodic

    now = datetime.now(timezone.utc)
    org = Organization(
        name=f"{_PFX}org-{uuid.uuid4().hex[:6]}", plan=PlanType.pro,
        leads_retention_days=30,
    )
    db.add(org)
    db.flush()
    proj = Project(
        organization_id=org.id, name=f"{_PFX}p",
        niche="x", geography="Томск", segments=[], prompt="",
    )
    db.add(proj)
    db.flush()

    old = _mk_lead(org.id, proj.id, "dormant", updated_at=now - timedelta(days=40))
    recent = _mk_lead(org.id, proj.id, "active", updated_at=now - timedelta(days=5))
    db.add_all([old, recent])
    db.commit()
    old_id, recent_id = old.id, recent.id

    try:
        periodic.purge_old_leads()
        db.expire_all()
        assert db.get(Lead, old_id) is None, "lead inactive 40d (> 30d retention) is purged"
        assert db.get(Lead, recent_id) is not None, "lead active 5d ago is kept"
    finally:
        db.rollback()
        db.execute(delete(Lead).where(Lead.project_id == proj.id))
        db.execute(delete(Project).where(Project.id == proj.id))
        db.execute(delete(Organization).where(Organization.id == org.id))
        db.commit()
