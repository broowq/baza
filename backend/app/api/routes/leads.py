import csv
import io
import json
import re
import uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_org, get_current_user, require_org_roles
from app.db.session import get_db
from app.models import CollectionJob, JobStatus, Lead, LeadCallNote, Organization, Project, User
from app.models.entities import LeadStatus
from app.schemas.leads import (
    CallNoteCreate,
    CallNoteOut,
    CollectionJobOut,
    EnrichSelectedRequest,
    LeadDetailOut,
    LeadOut,
    LeadUpdate,
    LeadWarehouseRef,
    PaginatedLeadsOut,
    RunCollectionRequest,
)
from app.services import company_warehouse
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


def _lock_project_and_check_active_job(db: Session, project_id, kind: str) -> CollectionJob | None:
    """Acquire a row-level lock on the Project row, then check for an active job of the given kind.

    Using SELECT … FOR UPDATE serialises concurrent requests against the same project:
    the second transaction blocks until the first commits (inserting the new job), then
    re-reads — finding the job — and returns it.  Without the lock, two simultaneous
    POSTs could both pass the check before either committed and spawn duplicate jobs.
    """
    # Lock the project row for the duration of this transaction.
    db.execute(
        select(Project).where(Project.id == project_id).with_for_update()
    )
    # Now safely check for an existing active job — no concurrent transaction can
    # insert a competing job for this project while we hold the lock.
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
    if _lock_project_and_check_active_job(db, project.id, "collect"):
        raise HTTPException(status_code=409, detail="Сбор уже запущен для этого проекта")
    if _count_active_org_jobs(db, organization.id) >= MAX_CONCURRENT_JOBS_PER_ORG:
        raise HTTPException(
            status_code=429,
            detail=f"Превышен лимит одновременных задач ({MAX_CONCURRENT_JOBS_PER_ORG}). Дождитесь завершения текущих задач.",
        )

    # Collect dose ceiling — the task clamps to the same 200; match it here so the
    # quota pre-check reflects what will actually be added (not the raw request).
    dose = min(payload.lead_limit, 200)
    ensure_lead_quota(organization, dose)
    job = CollectionJob(
        organization_id=organization.id,
        project_id=project.id,
        status=JobStatus.queued,
        kind="collect",
        requested_limit=dose,
    )
    db.add(job)
    db.flush()
    log_action(
        db,
        user_id=str(membership.user_id),
        organization_id=str(organization.id),
        action="leads.collect.queued",
        meta={"project_id": str(project.id), "limit": dose, "job_id": str(job.id)},
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
    if _lock_project_and_check_active_job(db, project.id, "enrich"):
        raise HTTPException(status_code=409, detail="Обогащение уже запущено для этого проекта")
    if _count_active_org_jobs(db, organization.id) >= MAX_CONCURRENT_JOBS_PER_ORG:
        raise HTTPException(
            status_code=429,
            detail=f"Превышен лимит одновременных задач ({MAX_CONCURRENT_JOBS_PER_ORG}). Дождитесь завершения текущих задач.",
        )
    # A lead is enrichable if it was never enriched, OR it still has no
    # actionable contact (no email AND no phone). We deliberately do NOT require
    # the address to also be empty: warehouse/2GIS leads often carry an address
    # but no email/phone, and gating on address left them permanently
    # un-enrichable ("Нет лидов для обогащения") even though they need contacts.
    enrichable = db.scalar(
        select(func.count(Lead.id)).where(
            Lead.project_id == project.id,
            or_(
                Lead.enriched.is_(False),
                (Lead.email == "") & (Lead.phone == ""),
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
    if _lock_project_and_check_active_job(db, project.id, "enrich"):
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
                ]
            )
            yield output.getvalue()

    return StreamingResponse(
        _generate_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


@router.get("/project/{project_id}/export.xlsx")
def export_project_xlsx(
    project_id: str,
    organization: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
):
    """Excel export (.xlsx) — opens correctly in Excel (unlike CSV with UTF-8 BOM).

    Uses openpyxl. Columns are Russian, phones/emails are hyperlinks where possible.
    For projects > 10k leads, CSV endpoint is still preferable (memory-friendly stream).
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    project = db.get(Project, project_id)
    if not project or project.organization_id != organization.id or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Проект не найден")

    safe_name = "".join(ch if ch.isascii() and (ch.isalnum() or ch in "-_") else "-" for ch in project.name.lower())
    safe_name = "-".join(part for part in safe_name.split("-") if part) or "project"
    file_name = f"leads-{safe_name}-{datetime.now(timezone.utc).date().isoformat()}.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "Лиды"

    headers = [
        ("Компания", 40), ("Город", 18), ("Сайт", 30), ("Email", 28),
        ("Телефон", 18), ("Адрес", 40), ("Score", 8), ("Статус", 14),
        ("Теги", 20), ("Последний контакт", 16), ("Напомнить", 16),
        ("Заметка", 40),
    ]
    for i, (title, width) in enumerate(headers, 1):
        cell = ws.cell(row=1, column=i, value=title)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="2F6FBD")
        cell.alignment = Alignment(vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.row_dimensions[1].height = 22
    ws.freeze_panes = "A2"

    status_labels = {
        "new": "Новый", "contacted": "Связались",
        "qualified": "Квалифицирован", "rejected": "Отклонён",
    }

    row_num = 2
    for lead in db.execute(select(Lead).where(Lead.project_id == project.id)).yield_per(500).scalars():
        ws.cell(row=row_num, column=1, value=lead.company or "")
        ws.cell(row=row_num, column=2, value=lead.city or "")
        website_cell = ws.cell(row=row_num, column=3, value=lead.website or "")
        if lead.website and lead.website.startswith("http"):
            website_cell.hyperlink = lead.website
            website_cell.font = Font(color="0000FF", underline="single")
        email_cell = ws.cell(row=row_num, column=4, value=lead.email or "")
        if lead.email:
            email_cell.hyperlink = f"mailto:{lead.email}"
            email_cell.font = Font(color="0000FF", underline="single")
        phone_cell = ws.cell(row=row_num, column=5, value=lead.phone or "")
        if lead.phone:
            phone_cell.hyperlink = f"tel:{lead.phone}"
            phone_cell.font = Font(color="0000FF", underline="single")
        ws.cell(row=row_num, column=6, value=lead.address or "")
        ws.cell(row=row_num, column=7, value=lead.score)
        ws.cell(row=row_num, column=8, value=status_labels.get(lead.status.value, lead.status.value))
        ws.cell(row=row_num, column=9, value=", ".join(lead.tags or []))
        if lead.last_contacted_at:
            ws.cell(row=row_num, column=10, value=lead.last_contacted_at.strftime("%d.%m.%Y"))
        if lead.reminder_at:
            ws.cell(row=row_num, column=11, value=lead.reminder_at.strftime("%d.%m.%Y"))
        ws.cell(row=row_num, column=12, value=lead.notes or "")
        row_num += 1

    # Write to in-memory buffer
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


VALID_STATUSES = {"new", "contacted", "qualified", "rejected"}


# Russian labels for the data source, used in the composed description.
_SOURCE_LABELS_RU = {
    "2gis": "2ГИС",
    "yandex_maps": "Яндекс.Карты",
    "rusprofile": "Rusprofile",
    "searxng": "веб-поиск",
    "bing": "Bing",
    "maps_searxng": "картам",
    "warehouse": "базе компаний",
}


def _compose_lead_description(lead: Lead, company) -> str:
    """Build a human-readable description for a lead that has none of its own.

    Composes from categories (warehouse) + city + source + contact availability.
    Returns "" only when there is genuinely nothing to say. If the lead's notes
    carry a real description (after stripping the internal "relevance=…;" /
    "demo=…;" prefixes the collector stores there), prefer that instead.
    """
    # The collector stores machine prefixes in notes ("relevance=NN; demo=true; ")
    # followed by the real snippet. Strip the prefixes to recover the snippet.
    note = (lead.notes or "")
    note = re.sub(r"^(?:relevance=\d+;\s*)?(?:demo=true;\s*)?", "", note).strip()
    if note:
        return note[:600]

    parts: list[str] = []
    categories = list(getattr(company, "categories", []) or []) if company else []
    if categories:
        parts.append(", ".join(categories[:5]))
    if lead.city:
        parts.append(f"г. {lead.city}" if not lead.city.lower().startswith("г.") else lead.city)
    if lead.source:
        label = _SOURCE_LABELS_RU.get(lead.source, lead.source)
        parts.append(f"источник: {label}")

    have = []
    if lead.phone:
        have.append("телефон")
    if lead.email:
        have.append("email")
    if lead.address:
        have.append("адрес")
    if lead.website and not lead.website.startswith("maps://"):
        have.append("сайт")
    if have:
        parts.append("есть " + ", ".join(have))
    else:
        parts.append("контакты не найдены")

    return ". ".join(p for p in parts if p).strip()


@router.get("/{lead_id}", response_model=LeadDetailOut)
def get_lead_detail(
    lead_id: uuid.UUID,
    organization: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
):
    """Full lead detail + computed description + warehouse cross-reference.

    Org-scoped: the lead (and its project) must belong to the caller's org,
    otherwise 404 (same opacity as the other lead routes — we don't leak
    existence across orgs).
    """
    lead = db.get(Lead, lead_id)
    if not lead or lead.organization_id != organization.id:
        raise HTTPException(status_code=404, detail="Лид не найден")
    project = db.get(Project, lead.project_id)
    if not project or project.organization_id != organization.id or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Лид не найден")

    # Cross-reference the shared company warehouse by the same dedup_key rule.
    # Best-effort — a warehouse miss/error just yields found=False.
    company = company_warehouse.find_company_for_lead(
        db, domain=lead.domain or "", company=lead.company or "", city=lead.city or ""
    )
    warehouse_ref = LeadWarehouseRef()
    if company is not None:
        # NOTE: Company.niches is deliberately NOT exposed here — those are
        # OTHER organizations' search niches (their go-to-market intent), a
        # cross-tenant leak. sources/categories are public data and stay.
        warehouse_ref = LeadWarehouseRef(
            found=True,
            company_id=company.id,
            times_seen=company.times_seen,
            first_seen_at=company.first_seen_at,
            last_seen_at=company.last_seen_at,
            sources=list(company.sources or []),
            categories=list(company.categories or []),
            best_score=company.best_score,
            inn=company.inn or "",
            twogis_firm_id=company.twogis_firm_id or "",
        )

    description = _compose_lead_description(lead, company)

    detail = LeadDetailOut.model_validate(lead)
    detail.description = description
    detail.warehouse = warehouse_ref
    return detail


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
    # Use model_fields_set so an explicit {"reminder_at": null} CLEARS the
    # reminder (the × button sends null); an omitted field leaves it untouched.
    # The old `is not None` guard silently ignored the clear → dead button.
    if "reminder_at" in payload.model_fields_set:
        lead.reminder_at = payload.reminder_at
    if payload.mark_contacted:
        # Convenience flag — sets last_contacted_at=now() and bumps status to "contacted"
        # if it was still "new". Lets sales click one button after a call.
        lead.last_contacted_at = datetime.now(timezone.utc)
        if lead.status == LeadStatus.new:
            lead.status = LeadStatus.contacted

    db.commit()
    db.refresh(lead)
    return lead


def _get_org_lead_or_404(db: Session, lead_id: uuid.UUID, organization: Organization) -> Lead:
    """Org-scoped lead fetch shared by the call-journal routes (404 opacity)."""
    lead = db.get(Lead, lead_id)
    if not lead or lead.organization_id != organization.id:
        raise HTTPException(status_code=404, detail="Лид не найден")
    project = db.get(Project, lead.project_id)
    if not project or project.organization_id != organization.id or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Лид не найден")
    return lead


@router.get("/{lead_id}/calls", response_model=list[CallNoteOut])
def list_call_notes(
    lead_id: uuid.UUID,
    organization: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
):
    """Call journal for a lead, newest first."""
    _get_org_lead_or_404(db, lead_id, organization)
    notes = db.execute(
        select(LeadCallNote)
        .where(
            LeadCallNote.lead_id == lead_id,
            LeadCallNote.organization_id == organization.id,
        )
        .order_by(LeadCallNote.created_at.desc())
        .limit(100)
    ).scalars().all()
    return notes


@router.post("/{lead_id}/calls", response_model=CallNoteOut, status_code=201)
def add_call_note(
    lead_id: uuid.UUID,
    payload: CallNoteCreate,
    organization: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Record a call on the lead: who called (current user) + optional comment.

    Side effects mirror mark_contacted: last_contacted_at=now(), and a lead
    still in "new" moves to "contacted" — so the journal is the single button
    sales clicks after dialing.
    """
    lead = _get_org_lead_or_404(db, lead_id, organization)
    note = LeadCallNote(
        organization_id=organization.id,
        lead_id=lead.id,
        user_id=user.id,
        user_name=(user.full_name or user.email or "")[:120],
        comment=(payload.comment or "").strip(),
    )
    db.add(note)
    lead.last_contacted_at = datetime.now(timezone.utc)
    if lead.status == LeadStatus.new:
        lead.status = LeadStatus.contacted
    db.commit()
    db.refresh(note)
    return note


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
