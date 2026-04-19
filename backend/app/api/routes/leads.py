import csv
import io
import json
import uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_org, get_current_user, require_org_roles
from app.db.session import get_db
from app.models import CollectionJob, JobStatus, Lead, Organization, Project, User
from app.models.entities import LeadStatus
from app.schemas.leads import (
    CollectionJobOut,
    EnrichSelectedRequest,
    LeadOut,
    LeadUpdate,
    PaginatedLeadsOut,
    RunCollectionRequest,
)
from app.services.quota import ensure_lead_quota
from app.services.audit import log_action
from app.tasks.jobs import collect_leads_task, enrich_leads_task
from app.utils.url_tools import extract_domain

router = APIRouter(prefix="/leads", tags=["leads"])

MAX_CONCURRENT_JOBS_PER_ORG = 3


def _count_active_org_jobs(db: Session, organization_id) -> int:
    """Count running/queued jobs across all projects in an organization."""
    return db.scalar(
        select(func.count(CollectionJob.id)).where(
            CollectionJob.organization_id == organization_id,
            CollectionJob.status.in_([JobStatus.queued, JobStatus.running]),
        )
    ) or 0


def _active_job_for_kind(db: Session, project_id, kind: str) -> CollectionJob | None:
    return db.execute(
        select(CollectionJob).where(
            CollectionJob.project_id == project_id,
            CollectionJob.kind == kind,
            CollectionJob.status.in_([JobStatus.queued, JobStatus.running]),
        )
    ).scalar_one_or_none()


@router.get("/project/{project_id}", response_model=list[LeadOut])
def list_project_leads(
    project_id: str,
    organization: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if not project or project.organization_id != organization.id or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Проект не найден")
    return db.execute(select(Lead).where(Lead.project_id == project.id).order_by(Lead.created_at.desc()).limit(5000)).scalars().all()


@router.get("/project/{project_id}/table", response_model=PaginatedLeadsOut)
def list_project_leads_table(
    project_id: str,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=200),
    q: str = "",
    status: LeadStatus | None = None,
    has_email: bool | None = None,
    has_phone: bool | None = None,
    min_score: int | None = Query(default=None, ge=0, le=100),
    max_score: int | None = Query(default=None, ge=0, le=100),
    sort: str = "score",
    order: str = "desc",
    organization: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if not project or project.organization_id != organization.id or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Проект не найден")

    query = select(Lead).where(Lead.project_id == project.id)
    count_query = select(func.count(Lead.id)).where(Lead.project_id == project.id)

    if q.strip():
        pattern = f"%{q.strip()}%"
        query = query.where(
            Lead.company.ilike(pattern)
            | Lead.website.ilike(pattern)
            | Lead.city.ilike(pattern)
            | Lead.domain.ilike(pattern)
            | Lead.email.ilike(pattern)
            | Lead.phone.ilike(pattern)
            | Lead.address.ilike(pattern)
        )
        count_query = count_query.where(
            Lead.company.ilike(pattern)
            | Lead.website.ilike(pattern)
            | Lead.city.ilike(pattern)
            | Lead.domain.ilike(pattern)
            | Lead.email.ilike(pattern)
            | Lead.phone.ilike(pattern)
            | Lead.address.ilike(pattern)
        )
    if status:
        query = query.where(Lead.status == status)
        count_query = count_query.where(Lead.status == status)
    if has_email is not None:
        if has_email:
            query = query.where(Lead.email != "")
            count_query = count_query.where(Lead.email != "")
        else:
            query = query.where(Lead.email == "")
            count_query = count_query.where(Lead.email == "")
    if has_phone is not None:
        if has_phone:
            query = query.where(Lead.phone != "")
            count_query = count_query.where(Lead.phone != "")
        else:
            query = query.where(Lead.phone == "")
            count_query = count_query.where(Lead.phone == "")
    if min_score is not None:
        query = query.where(Lead.score >= min_score)
        count_query = count_query.where(Lead.score >= min_score)
    if max_score is not None:
        query = query.where(Lead.score <= max_score)
        count_query = count_query.where(Lead.score <= max_score)

    sort_column = {
        "score": Lead.score,
        "company": Lead.company,
        "status": Lead.status,
        "created_at": Lead.created_at,
    }.get(sort, Lead.created_at)
    query = query.order_by(sort_column.asc() if order == "asc" else sort_column.desc())

    total = db.scalar(count_query) or 0
    items = db.execute(query.offset((page - 1) * per_page).limit(per_page)).scalars().all()
    return PaginatedLeadsOut(items=items, total=total, page=page, per_page=per_page)


@router.post("/project/{project_id}/collect", response_model=CollectionJobOut)
def run_collection(
    project_id: str,
    payload: RunCollectionRequest,
    organization: Organization = Depends(get_current_org),
    membership=Depends(require_org_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if not project or project.organization_id != organization.id or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Проект не найден")
    if _active_job_for_kind(db, project.id, "collect"):
        raise HTTPException(status_code=409, detail="Сбор уже запущен для этого проекта")
    if _count_active_org_jobs(db, organization.id) >= MAX_CONCURRENT_JOBS_PER_ORG:
        raise HTTPException(
            status_code=429,
            detail=f"Превышен лимит одновременных задач ({MAX_CONCURRENT_JOBS_PER_ORG}). Дождитесь завершения текущих задач.",
        )

    ensure_lead_quota(organization, payload.lead_limit)
    job = CollectionJob(
        organization_id=organization.id,
        project_id=project.id,
        status=JobStatus.queued,
        kind="collect",
        requested_limit=payload.lead_limit,
    )
    db.add(job)
    db.flush()
    log_action(
        db,
        user_id=str(membership.user_id),
        organization_id=str(organization.id),
        action="leads.collect.queued",
        meta={"project_id": str(project.id), "limit": payload.lead_limit, "job_id": str(job.id)},
    )
    db.commit()
    db.refresh(job)
    collect_leads_task.delay(str(job.id))
    return job


@router.post("/project/{project_id}/enrich", response_model=CollectionJobOut)
def run_enrichment(
    project_id: str,
    payload: RunCollectionRequest,
    organization: Organization = Depends(get_current_org),
    membership=Depends(require_org_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if not project or project.organization_id != organization.id or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Проект не найден")
    if _active_job_for_kind(db, project.id, "enrich"):
        raise HTTPException(status_code=409, detail="Обогащение уже запущено для этого проекта")
    if _count_active_org_jobs(db, organization.id) >= MAX_CONCURRENT_JOBS_PER_ORG:
        raise HTTPException(
            status_code=429,
            detail=f"Превышен лимит одновременных задач ({MAX_CONCURRENT_JOBS_PER_ORG}). Дождитесь завершения текущих задач.",
        )
    enrichable = db.scalar(
        select(func.count(Lead.id)).where(
            Lead.project_id == project.id,
            or_(
                Lead.enriched.is_(False),
                (Lead.email == "") & (Lead.phone == "") & (Lead.address == ""),
            ),
        )
    ) or 0
    if enrichable == 0:
        raise HTTPException(status_code=400, detail="Нет лидов для обогащения")
    job = CollectionJob(
        organization_id=organization.id,
        project_id=project.id,
        status=JobStatus.queued,
        kind="enrich",
        requested_limit=payload.lead_limit,
    )
    db.add(job)
    db.flush()
    log_action(
        db,
        user_id=str(membership.user_id),
        organization_id=str(organization.id),
        action="leads.enrich.queued",
        meta={"project_id": str(project.id), "limit": payload.lead_limit, "job_id": str(job.id)},
    )
    db.commit()
    db.refresh(job)
    enrich_leads_task.delay(str(job.id))
    return job


@router.post("/project/{project_id}/enrich-selected", response_model=CollectionJobOut)
def run_selected_enrichment(
    project_id: str,
    payload: EnrichSelectedRequest,
    organization: Organization = Depends(get_current_org),
    membership=Depends(require_org_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if not project or project.organization_id != organization.id or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Проект не найден")
    if _active_job_for_kind(db, project.id, "enrich"):
        raise HTTPException(status_code=409, detail="Обогащение уже запущено для этого проекта")
    if _count_active_org_jobs(db, organization.id) >= MAX_CONCURRENT_JOBS_PER_ORG:
        raise HTTPException(
            status_code=429,
            detail=f"Превышен лимит одновременных задач ({MAX_CONCURRENT_JOBS_PER_ORG}). Дождитесь завершения текущих задач.",
        )
    if not payload.lead_ids:
        raise HTTPException(status_code=400, detail="Не выбраны лиды для обогащения")
    safe_ids: list[UUID] = []
    for raw_id in payload.lead_ids:
        try:
            safe_ids.append(UUID(raw_id))
        except ValueError:
            continue
    if not safe_ids:
        raise HTTPException(status_code=400, detail="Переданы некорректные идентификаторы лидов")
    valid_count = db.scalar(select(func.count(Lead.id)).where(Lead.project_id == project.id, Lead.id.in_(safe_ids))) or 0
    if valid_count == 0:
        raise HTTPException(status_code=400, detail="Выбранные лиды не найдены в проекте")
    job = CollectionJob(
        organization_id=organization.id,
        project_id=project.id,
        status=JobStatus.queued,
        kind="enrich",
        requested_limit=valid_count,
    )
    db.add(job)
    db.flush()
    log_action(
        db,
        user_id=str(membership.user_id),
        organization_id=str(organization.id),
        action="leads.enrich_selected.queued",
        meta={"project_id": str(project.id), "lead_ids_count": len(safe_ids), "job_id": str(job.id)},
    )
    db.commit()
    db.refresh(job)
    enrich_leads_task.delay(str(job.id), [str(item) for item in safe_ids])
    return job


@router.get("/jobs/project/{project_id}", response_model=list[CollectionJobOut])
def list_jobs(
    project_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    organization: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
):
    """List recent collection/enrichment jobs (default last 50, max 500)."""
    project = db.get(Project, project_id)
    if not project or project.organization_id != organization.id or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Проект не найден")
    return (
        db.execute(
            select(CollectionJob)
            .where(CollectionJob.project_id == project.id)
            .order_by(CollectionJob.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )


@router.get("/project/{project_id}/export")
def export_project_csv(
    project_id: str,
    organization: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if not project or project.organization_id != organization.id or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Проект не найден")

    safe_name = "".join(ch if ch.isascii() and (ch.isalnum() or ch in "-_") else "-" for ch in project.name.lower())
    safe_name = "-".join(part for part in safe_name.split("-") if part) or "project"
    file_name = f"leads-{safe_name}-{datetime.now(timezone.utc).date().isoformat()}.csv"

    def _generate_csv():
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "company",
                "city",
                "website",
                "domain",
                "email",
                "phone",
                "address",
                "score",
                "status",
                "source_url",
                "contacts_json",
                "demo",
                "aggregator_skipped",
            ]
        )
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        for lead in db.execute(
            select(Lead).where(Lead.project_id == project.id)
        ).yield_per(500).scalars():
            output.seek(0)
            output.truncate(0)
            contacts = lead.contacts_json or lead.contacts or {}
            writer.writerow(
                [
                    lead.company,
                    lead.city,
                    lead.website,
                    lead.domain or extract_domain(lead.website),
                    lead.email,
                    lead.phone,
                    lead.address,
                    lead.score,
                    lead.status.value,
                    lead.source_url,
                    json.dumps(contacts, ensure_ascii=False),
                    str(bool(lead.demo)).lower(),
                    "false",
                ]
            )
            yield output.getvalue()

    return StreamingResponse(
        _generate_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


VALID_STATUSES = {"new", "contacted", "qualified", "rejected"}


@router.patch("/{lead_id}", response_model=LeadOut)
def update_lead(
    lead_id: uuid.UUID,
    payload: LeadUpdate,
    organization: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    lead = db.get(Lead, lead_id)
    if not lead or lead.organization_id != organization.id:
        raise HTTPException(status_code=404, detail="Лид не найден")
    project = db.get(Project, lead.project_id)
    if not project or project.organization_id != organization.id or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Лид не найден")

    if payload.status is not None:
        if payload.status not in VALID_STATUSES:
            raise HTTPException(
                status_code=422,
                detail=f"Недопустимый статус. Допустимые значения: {', '.join(sorted(VALID_STATUSES))}",
            )
        lead.status = LeadStatus(payload.status)
    if payload.notes is not None:
        lead.notes = payload.notes
    if payload.tags is not None:
        # Sanitize tags: trim, dedupe, max 30 chars each
        cleaned_tags = []
        seen = set()
        for t in payload.tags:
            t = (t or "").strip()[:30]
            if t and t.lower() not in seen:
                seen.add(t.lower())
                cleaned_tags.append(t)
        lead.tags = cleaned_tags
    if payload.last_contacted_at is not None:
        lead.last_contacted_at = payload.last_contacted_at
    if payload.reminder_at is not None:
        lead.reminder_at = payload.reminder_at
    if payload.mark_contacted:
        # Convenience flag — sets last_contacted_at=now() and bumps status to "contacted"
        # if it was still "new". Lets sales click one button after a call.
        from datetime import datetime, timezone
        lead.last_contacted_at = datetime.now(timezone.utc)
        if lead.status == LeadStatus.new:
            lead.status = LeadStatus.contacted

    db.commit()
    db.refresh(lead)
    return lead


@router.delete("/{lead_id}", status_code=204)
def delete_lead(
    lead_id: uuid.UUID,
    organization: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    lead = db.get(Lead, lead_id)
    if not lead or lead.organization_id != organization.id:
        raise HTTPException(status_code=404, detail="Лид не найден")
    project = db.get(Project, lead.project_id)
    if not project or project.organization_id != organization.id or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Лид не найден")

    db.delete(lead)
    db.commit()
    return Response(status_code=204)


@router.get("/project/{project_id}/stats")
def get_project_stats(
    project_id: uuid.UUID,
    organization: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = db.get(Project, project_id)
    if not project or project.organization_id != organization.id or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Проект не найден")

    total = db.execute(select(func.count(Lead.id)).where(Lead.project_id == project.id)).scalar()
    enriched = db.execute(
        select(func.count(Lead.id)).where(Lead.project_id == project.id, Lead.enriched == True)
    ).scalar()
    with_email = db.execute(
        select(func.count(Lead.id)).where(
            Lead.project_id == project.id, Lead.email.isnot(None), Lead.email != ""
        )
    ).scalar()
    avg_score = (
        db.execute(select(func.avg(Lead.score)).where(Lead.project_id == project.id)).scalar() or 0
    )
    return {
        "total": total,
        "enriched": enriched,
        "with_email": with_email,
        "avg_score": round(float(avg_score), 1),
    }
