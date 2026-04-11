from datetime import datetime, timedelta, timezone
from uuid import UUID as _UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.models import ActionLog, CollectionJob, Lead, Membership, Organization, PlanType, Project, User
from app.services.quota import PLAN_LIMITS, apply_plan_limits

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Schemas ──

class OrgLimitUpdate(BaseModel):
    projects_limit: int = Field(ge=1, le=100000)
    leads_limit_per_month: int = Field(ge=1, le=10000000)


class OrgPlanUpdate(BaseModel):
    plan: str


class UserUpdate(BaseModel):
    is_admin: bool | None = None
    email_verified: bool | None = None


# ── Stats ──

@router.get("/stats")
def get_stats(
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    total_users = db.scalar(select(func.count(User.id))) or 0
    total_orgs = db.scalar(select(func.count(Organization.id))) or 0
    total_projects = db.scalar(select(func.count(Project.id)).where(Project.deleted_at.is_(None))) or 0
    total_leads = db.scalar(select(func.count(Lead.id))) or 0
    total_jobs = db.scalar(select(func.count(CollectionJob.id))) or 0

    users_today = db.scalar(select(func.count(User.id)).where(User.created_at >= today_start)) or 0
    users_week = db.scalar(select(func.count(User.id)).where(User.created_at >= week_ago)) or 0
    users_month = db.scalar(select(func.count(User.id)).where(User.created_at >= month_ago)) or 0

    jobs_today = db.scalar(select(func.count(CollectionJob.id)).where(CollectionJob.created_at >= today_start)) or 0
    jobs_week = db.scalar(select(func.count(CollectionJob.id)).where(CollectionJob.created_at >= week_ago)) or 0

    leads_today = db.scalar(select(func.count(Lead.id)).where(Lead.created_at >= today_start)) or 0
    leads_week = db.scalar(select(func.count(Lead.id)).where(Lead.created_at >= week_ago)) or 0

    # Revenue estimate based on plans
    from app.api.routes.plans import PLAN_PRICES_RUB
    revenue = 0
    for plan_type in [PlanType.starter, PlanType.pro, PlanType.team]:
        count = db.scalar(select(func.count(Organization.id)).where(Organization.plan == plan_type)) or 0
        revenue += count * PLAN_PRICES_RUB.get(plan_type.value, 0)

    # Plan distribution
    plan_dist = {}
    for pt in PlanType:
        plan_dist[pt.value] = db.scalar(select(func.count(Organization.id)).where(Organization.plan == pt)) or 0

    return {
        "totals": {
            "users": total_users,
            "organizations": total_orgs,
            "projects": total_projects,
            "leads": total_leads,
            "jobs": total_jobs,
        },
        "recent": {
            "users_today": users_today,
            "users_week": users_week,
            "users_month": users_month,
            "jobs_today": jobs_today,
            "jobs_week": jobs_week,
            "leads_today": leads_today,
            "leads_week": leads_week,
        },
        "revenue_monthly_rub": revenue,
        "plan_distribution": plan_dist,
    }


# ── Users ──

@router.get("/users")
def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    total = db.scalar(select(func.count(User.id))) or 0
    users = (
        db.execute(select(User).order_by(User.created_at.desc()).offset(skip).limit(min(limit, 200)))
        .scalars().all()
    )
    return {
        "total": total,
        "items": [
            {
                "id": str(u.id),
                "email": u.email,
                "full_name": u.full_name,
                "is_admin": u.is_admin,
                "email_verified": u.email_verified,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ],
    }


@router.patch("/users/{user_id}")
def update_user(
    user_id: str,
    payload: UserUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        _UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Некорректный ID")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if str(user.id) == str(admin.id):
        raise HTTPException(status_code=400, detail="Нельзя менять свой аккаунт")

    if payload.is_admin is not None:
        user.is_admin = payload.is_admin
    if payload.email_verified is not None:
        user.email_verified = payload.email_verified
    db.commit()
    return {"message": "Пользователь обновлён"}


@router.delete("/users/{user_id}")
def delete_user(
    user_id: str,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        _UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Некорректный ID")
    if user_id == str(admin.id):
        raise HTTPException(status_code=400, detail="Нельзя удалить себя")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # Delete memberships first
    db.execute(select(Membership).where(Membership.user_id == user.id))
    for m in db.execute(select(Membership).where(Membership.user_id == user.id)).scalars().all():
        db.delete(m)
    db.delete(user)
    db.commit()
    return {"message": "Пользователь удалён"}


# ── Organizations ──

@router.get("/organizations")
def list_organizations(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    total = db.scalar(select(func.count(Organization.id))) or 0
    orgs = (
        db.execute(select(Organization).order_by(Organization.created_at.desc()).offset(skip).limit(min(limit, 200)))
        .scalars().all()
    )

    result = []
    for o in orgs:
        members_count = db.scalar(select(func.count(Membership.id)).where(Membership.organization_id == o.id)) or 0
        projects_count = db.scalar(
            select(func.count(Project.id)).where(Project.organization_id == o.id, Project.deleted_at.is_(None))
        ) or 0
        leads_count = db.scalar(select(func.count(Lead.id)).where(Lead.organization_id == o.id)) or 0

        result.append({
            "id": str(o.id),
            "name": o.name,
            "plan": o.plan.value,
            "members_count": members_count,
            "projects_count": projects_count,
            "leads_count": leads_count,
            "projects_limit": o.projects_limit,
            "users_limit": o.users_limit,
            "leads_limit_per_month": o.leads_limit_per_month,
            "leads_used_current_month": o.leads_used_current_month,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        })

    return {"total": total, "items": result}


@router.patch("/organizations/{org_id}/limits")
def update_org_limits(
    org_id: str,
    payload: OrgLimitUpdate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        _UUID(org_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Некорректный ID")
    org = db.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Организация не найдена")
    org.projects_limit = payload.projects_limit
    org.leads_limit_per_month = payload.leads_limit_per_month
    db.commit()
    return {"message": "Лимиты обновлены"}


@router.patch("/organizations/{org_id}/plan")
def update_org_plan(
    org_id: str,
    payload: OrgPlanUpdate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        _UUID(org_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Некорректный ID")
    org = db.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Организация не найдена")

    try:
        new_plan = PlanType(payload.plan)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Неверный тариф: {payload.plan}")

    org.plan = new_plan
    apply_plan_limits(org)
    db.commit()
    return {"message": f"Тариф изменён на {new_plan.value}"}


# ── Jobs ──

@router.get("/jobs")
def list_jobs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    status: str | None = Query(None),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    total_q = select(func.count(CollectionJob.id))
    q = select(CollectionJob).order_by(CollectionJob.created_at.desc())

    if status:
        total_q = total_q.where(CollectionJob.status == status)
        q = q.where(CollectionJob.status == status)

    total = db.scalar(total_q) or 0
    jobs = db.execute(q.offset(skip).limit(min(limit, 200))).scalars().all()

    result = []
    for j in jobs:
        project = db.get(Project, j.project_id)
        org = db.get(Organization, j.organization_id) if j.organization_id else None
        result.append({
            "id": str(j.id),
            "project_name": project.name if project else "—",
            "org_name": org.name if org else "—",
            "status": j.status.value if hasattr(j.status, "value") else str(j.status),
            "kind": j.kind,
            "requested_limit": j.requested_limit,
            "found_count": j.found_count,
            "added_count": j.added_count,
            "enriched_count": j.enriched_count,
            "error": j.error,
            "created_at": j.created_at.isoformat() if j.created_at else None,
        })

    return {"total": total, "items": result}


# ── Logs ──

@router.get("/logs")
def list_logs(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    total = db.scalar(select(func.count(ActionLog.id))) or 0
    logs = (
        db.execute(select(ActionLog).order_by(ActionLog.created_at.desc()).offset(skip).limit(min(limit, 200)))
        .scalars().all()
    )

    result = []
    for log in logs:
        user = db.get(User, log.user_id) if log.user_id else None
        org = db.get(Organization, log.organization_id) if log.organization_id else None
        result.append({
            "id": str(log.id),
            "action": log.action,
            "user_email": user.email if user else "—",
            "org_name": org.name if org else "—",
            "meta": log.meta,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        })

    return {"total": total, "items": result}
