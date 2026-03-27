from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.models import Organization, User

router = APIRouter(prefix="/admin", tags=["admin"])


class OrgLimitUpdate(BaseModel):
    projects_limit: int = Field(ge=1, le=100000)
    leads_limit_per_month: int = Field(ge=1, le=10000000)


@router.get("/users")
def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    total = db.scalar(select(func.count(User.id))) or 0
    capped_limit = min(limit, 200)
    users = (
        db.execute(
            select(User).order_by(User.created_at.desc()).offset(skip).limit(capped_limit)
        )
        .scalars()
        .all()
    )
    return {
        "total": total,
        "skip": skip,
        "limit": capped_limit,
        "items": [
            {"id": str(u.id), "email": u.email, "full_name": u.full_name, "is_admin": u.is_admin, "created_at": u.created_at}
            for u in users
        ],
    }


@router.get("/organizations")
def list_organizations(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    total = db.scalar(select(func.count(Organization.id))) or 0
    capped_limit = min(limit, 200)
    orgs = (
        db.execute(
            select(Organization).order_by(Organization.created_at.desc()).offset(skip).limit(capped_limit)
        )
        .scalars()
        .all()
    )
    return {
        "total": total,
        "skip": skip,
        "limit": capped_limit,
        "items": [
            {
                "id": str(o.id),
                "name": o.name,
                "plan": o.plan.value,
                "projects_limit": o.projects_limit,
                "users_limit": o.users_limit,
                "leads_limit_per_month": o.leads_limit_per_month,
                "leads_used_current_month": o.leads_used_current_month,
            }
            for o in orgs
        ],
    }


@router.patch("/organizations/{org_id}/limits")
def update_org_limits(
    org_id: str,
    payload: OrgLimitUpdate,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from uuid import UUID as _UUID
    try:
        _UUID(org_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Некорректный идентификатор организации")
    org = db.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=404, detail="Организация не найдена")
    org.projects_limit = payload.projects_limit
    org.leads_limit_per_month = payload.leads_limit_per_month
    db.commit()
    return {"message": "Лимиты обновлены"}
