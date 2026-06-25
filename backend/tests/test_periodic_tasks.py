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
    Subscription,
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


def _mk_paid_org(db):
    org = Organization(
        name=f"{_PFX}org-{uuid.uuid4().hex[:6]}", plan=PlanType.pro,
        leads_limit_per_month=25000, projects_limit=20, users_limit=10,
        can_invite_members=True,
    )
    db.add(org)
    db.flush()
    return org


def test_expired_subscription_downgrades_org_to_free(db):
    """A lapsed (period_end in the past) active subscription must downgrade the
    org to free and restore free limits — otherwise a once-paid org keeps Pro
    forever (the billing leak)."""
    from app.tasks import periodic

    now = datetime.now(timezone.utc)
    org = _mk_paid_org(db)
    sub = Subscription(
        organization_id=org.id, plan_id="pro", status="active",
        current_period_start=now - timedelta(days=31),
        current_period_end=now - timedelta(days=1),
    )
    db.add(sub)
    db.commit()
    oid, sid = org.id, sub.id
    try:
        periodic.downgrade_expired_subscriptions()
        db.expire_all()
        org = db.get(Organization, oid)
        sub = db.get(Subscription, sid)
        assert org.plan == PlanType.free, "lapsed subscription must downgrade org to free"
        assert org.leads_limit_per_month == 0, "free limits must be restored"
        assert org.projects_limit == 1, "free limits must be restored"
        assert sub.status == "expired", "lapsed subscription must be marked expired"
    finally:
        db.rollback()
        db.execute(delete(Subscription).where(Subscription.id == sid))
        db.execute(delete(Organization).where(Organization.id == oid))
        db.commit()


def test_active_subscription_not_downgraded(db):
    """A subscription whose period is still in the future is left untouched."""
    from app.tasks import periodic

    now = datetime.now(timezone.utc)
    org = _mk_paid_org(db)
    sub = Subscription(
        organization_id=org.id, plan_id="pro", status="active",
        current_period_start=now - timedelta(days=2),
        current_period_end=now + timedelta(days=28),
    )
    db.add(sub)
    db.commit()
    oid, sid = org.id, sub.id
    try:
        periodic.downgrade_expired_subscriptions()
        db.expire_all()
        org = db.get(Organization, oid)
        sub = db.get(Subscription, sid)
        assert org.plan == PlanType.pro, "active (future) subscription must NOT be downgraded"
        assert sub.status == "active"
    finally:
        db.rollback()
        db.execute(delete(Subscription).where(Subscription.id == sid))
        db.execute(delete(Organization).where(Organization.id == oid))
        db.commit()


def test_renewed_org_not_downgraded_when_newer_sub_covers(db):
    """A renewal creates a fresh subscription row; the old one lapses. The org
    must keep its plan because a newer active subscription still covers it."""
    from app.tasks import periodic

    now = datetime.now(timezone.utc)
    org = _mk_paid_org(db)
    old = Subscription(
        organization_id=org.id, plan_id="pro", status="active",
        current_period_start=now - timedelta(days=31),
        current_period_end=now - timedelta(days=1),
    )
    new = Subscription(
        organization_id=org.id, plan_id="pro", status="active",
        current_period_start=now - timedelta(days=1),
        current_period_end=now + timedelta(days=29),
    )
    db.add_all([old, new])
    db.commit()
    oid, old_id, new_id = org.id, old.id, new.id
    try:
        periodic.downgrade_expired_subscriptions()
        db.expire_all()
        org = db.get(Organization, oid)
        assert org.plan == PlanType.pro, "org with a newer covering sub must NOT be downgraded"
        assert db.get(Subscription, old_id).status == "expired", "the lapsed row is still marked expired"
        assert db.get(Subscription, new_id).status == "active", "the covering sub stays active"
    finally:
        db.rollback()
        db.execute(delete(Subscription).where(Subscription.id.in_([old_id, new_id])))
        db.execute(delete(Organization).where(Organization.id == oid))
        db.commit()


def test_expired_higher_tier_reconciles_to_covering_lower_tier(db):
    """An org on Team whose Team sub lapses while a Pro sub still covers it must
    reconcile DOWN to Pro — not stay on Team (no longer paid) and not drop to
    free (still has paid coverage)."""
    from app.tasks import periodic

    now = datetime.now(timezone.utc)
    org = Organization(
        name=f"{_PFX}org-{uuid.uuid4().hex[:6]}", plan=PlanType.team,
        leads_limit_per_month=100000, projects_limit=100, users_limit=50,
        can_invite_members=True,
    )
    db.add(org)
    db.flush()
    team_sub = Subscription(organization_id=org.id, plan_id="team", status="active",
                            current_period_end=now - timedelta(days=1))
    pro_sub = Subscription(organization_id=org.id, plan_id="pro", status="active",
                           current_period_end=now + timedelta(days=20))
    db.add_all([team_sub, pro_sub])
    db.commit()
    oid, tid, pid = org.id, team_sub.id, pro_sub.id
    try:
        periodic.downgrade_expired_subscriptions()
        db.expire_all()
        org = db.get(Organization, oid)
        assert org.plan == PlanType.pro, "lapsed Team but Pro still covers → reconcile to Pro"
        assert org.leads_limit_per_month == 10000, "limits reconciled to Pro"
        assert db.get(Subscription, tid).status == "expired"
        assert db.get(Subscription, pid).status == "active"
    finally:
        db.rollback()
        db.execute(delete(Subscription).where(Subscription.id.in_([tid, pid])))
        db.execute(delete(Organization).where(Organization.id == oid))
        db.commit()


def test_reconcile_keeps_plan_when_other_active_sub_covers(db):
    """The refund-path core: reconciling after one subscription is removed must
    NOT strip access while another active subscription still covers the org."""
    from app.services.quota import reconcile_org_plan

    now = datetime.now(timezone.utc)
    org = Organization(
        name=f"{_PFX}org-{uuid.uuid4().hex[:6]}", plan=PlanType.pro,
        leads_limit_per_month=25000, projects_limit=20,
    )
    db.add(org)
    db.flush()
    refunded = Subscription(organization_id=org.id, plan_id="pro", status="refunded",
                            current_period_end=now + timedelta(days=20))
    active = Subscription(organization_id=org.id, plan_id="pro", status="active",
                          current_period_end=now + timedelta(days=20))
    db.add_all([refunded, active])
    db.commit()
    oid, rid, aid = org.id, refunded.id, active.id
    try:
        result = reconcile_org_plan(db, db.get(Organization, oid), exclude_sub_id=rid)
        db.commit()
        assert result == PlanType.pro, "another active sub covers → keep Pro"
        assert db.get(Organization, oid).leads_limit_per_month == 10000
    finally:
        db.rollback()
        db.execute(delete(Subscription).where(Subscription.id.in_([rid, aid])))
        db.execute(delete(Organization).where(Organization.id == oid))
        db.commit()


def test_reconcile_downgrades_to_free_when_no_coverage(db):
    """No active covering subscription → reconcile drops the org to free."""
    from app.services.quota import reconcile_org_plan

    org = Organization(
        name=f"{_PFX}org-{uuid.uuid4().hex[:6]}", plan=PlanType.pro,
        leads_limit_per_month=25000, projects_limit=20,
    )
    db.add(org)
    db.commit()
    oid = org.id
    try:
        result = reconcile_org_plan(db, db.get(Organization, oid))
        db.commit()
        assert result == PlanType.free
        assert db.get(Organization, oid).leads_limit_per_month == 0
    finally:
        db.rollback()
        db.execute(delete(Organization).where(Organization.id == oid))
        db.commit()
