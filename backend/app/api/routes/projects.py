import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_org, require_org_roles
from app.db.session import get_db
from app.models import Organization, Project
from app.schemas.common import APIMessage
from app.schemas.projects import (
    ProjectCreateRequest,
    ProjectOut,
    ProjectUpdateRequest,
    PromptEnhanceRequest,
    PromptEnhanceResponse,
)
from app.services.audit import log_action

router = APIRouter(prefix="/projects", tags=["projects"])

# Simple cron expression pattern: 5 fields (minute hour day month weekday)
# Each field allows: number, *, ranges (1-5), lists (1,3,5), steps (*/2)
_CRON_FIELD = r"(\*|[0-9]{1,2})([,-/][0-9*]{1,3})*"
_CRON_PATTERN = re.compile(
    rf"^\s*{_CRON_FIELD}\s+{_CRON_FIELD}\s+{_CRON_FIELD}\s+{_CRON_FIELD}\s+{_CRON_FIELD}\s*$"
)


def _validate_cron(expression: str) -> None:
    """Validate a cron expression. Raises HTTPException 422 if invalid."""
    if not _CRON_PATTERN.match(expression):
        raise HTTPException(
            status_code=422,
            detail=f"Некорректное cron-выражение: '{expression}'. Ожидается 5 полей: минута час день месяц день_недели",
        )


@router.post("/enhance-prompt", response_model=PromptEnhanceResponse)
def enhance_prompt(
    payload: PromptEnhanceRequest,
    organization: Organization = Depends(get_current_org),
):
    """Enhance a raw user prompt into an optimized search strategy."""
    from app.services.prompt_enhancer import enhance_prompt as do_enhance

    result = do_enhance(payload.prompt)
    return PromptEnhanceResponse(
        enhanced_prompt=result.get("enhanced_prompt", payload.prompt),
        project_name=result.get("project_name", "Новый проект"),
        niche=result.get("niche", payload.prompt[:120]),
        geography=result.get("geography", "Россия"),
        segments=result.get("segments", []),
        target_customer_types=result.get("target_customer_types", []),
        search_queries_niche=result.get("search_queries_niche", ""),
        explanation=result.get("explanation", ""),
    )


@router.get("", response_model=list[ProjectOut])
def list_projects(
    organization: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
):
    return (
        db.execute(
            select(Project)
            .where(Project.organization_id == organization.id, Project.deleted_at.is_(None))
            .order_by(Project.created_at.desc())
        )
        .scalars()
        .all()
    )


@router.post("", response_model=ProjectOut)
def create_project(
    payload: ProjectCreateRequest,
    organization: Organization = Depends(get_current_org),
    membership=Depends(require_org_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    _validate_cron(payload.cron_schedule)

    count = db.scalar(
        select(func.count(Project.id)).where(
            Project.organization_id == organization.id,
            Project.deleted_at.is_(None),
        )
    ) or 0
    if count >= organization.projects_limit:
        raise HTTPException(status_code=402, detail="Лимит проектов для текущего тарифа исчерпан")

    # Auto-enhance: if prompt is provided and niche looks like raw prompt, enhance it
    final_name = payload.name
    final_niche = payload.niche
    final_geo = payload.geography
    final_segments = payload.segments
    if payload.prompt and payload.prompt.strip() == payload.niche.strip():
        try:
            from app.services.prompt_enhancer import enhance_prompt as do_enhance
            enhanced = do_enhance(payload.prompt)
            if enhanced.get("niche"):
                final_niche = enhanced["niche"]
            if enhanced.get("geography") and enhanced["geography"] != "Россия":
                final_geo = enhanced["geography"]
            if enhanced.get("segments"):
                final_segments = enhanced["segments"]
            if enhanced.get("project_name"):
                final_name = enhanced["project_name"]
        except Exception:
            pass  # Use original values

    project = Project(
        organization_id=organization.id,
        name=final_name,
        prompt=payload.prompt,
        niche=final_niche,
        geography=final_geo,
        segments=final_segments,
        cron_schedule=payload.cron_schedule,
        auto_collection_enabled=payload.auto_collection_enabled,
    )
    db.add(project)
    db.flush()
    log_action(
        db,
        user_id=str(membership.user_id),
        organization_id=str(organization.id),
        action="project.created",
        meta={"project_id": str(project.id), "name": project.name},
    )
    db.commit()
    db.refresh(project)
    return project


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: str,
    payload: ProjectUpdateRequest,
    organization: Organization = Depends(get_current_org),
    membership=Depends(require_org_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if not project or project.organization_id != organization.id or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Проект не найден")

    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return project

    if "cron_schedule" in updates:
        _validate_cron(updates["cron_schedule"])

    for field, value in updates.items():
        setattr(project, field, value)

    log_action(
        db,
        user_id=str(membership.user_id),
        organization_id=str(organization.id),
        action="project.updated",
        meta={"project_id": str(project.id), "fields": sorted(updates.keys())},
    )
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", response_model=APIMessage)
def delete_project(
    project_id: str,
    organization: Organization = Depends(get_current_org),
    membership=Depends(require_org_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if not project or project.organization_id != organization.id or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Проект не найден")
    project.deleted_at = datetime.now(timezone.utc)
    log_action(
        db,
        user_id=str(membership.user_id),
        organization_id=str(organization.id),
        action="project.deleted",
        meta={"project_id": str(project.id), "name": project.name},
    )
    db.commit()
    return APIMessage(message="Проект удален")
