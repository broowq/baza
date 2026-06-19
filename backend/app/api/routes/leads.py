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
from app.models import (
    CollectionJob,
    JobStatus,
    Lead,
    LeadCallNote,
    LeadStatus,
    Membership,
    Organization,
    Project,
    User,
)
from app.schemas.crm import BulkLeadAction, BulkResult
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
from app.services.crm import log_activity, stage_label
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
    assigned_to: str | None = Query(
        default=None,
        description='User UUID, "me" (current user), or "none"/"unassigned" (no owner)',
    ),
    sort: str = "score",
    order: str = "desc",
    organization: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
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
    if assigned_to is not None and assigned_to != "":
        token = assigned_to.strip().lower()
        if token in ("none", "unassigned"):
            query = query.where(Lead.assigned_to_user_id.is_(None))
            count_query = count_query.where(Lead.assigned_to_user_id.is_(None))
        elif token == "me":
            query = query.where(Lead.assigned_to_user_id == user.id)
            count_query = count_query.where(Lead.assigned_to_user_id == user.id)
        else:
            # An explicit user UUID. Malformed → 422 (matches the API's strict
            # param validation elsewhere); an unknown-but-valid UUID simply
            # matches nothing (no cross-org leak — leads stay project-scoped).
            try:
                assignee_id = uuid.UUID(assigned_to)
            except ValueError as exc:
                raise HTTPException(
                    status_code=422, detail="Некорректный идентификатор пользователя"
                ) from exc
            query = query.where(Lead.assigned_to_user_id == assignee_id)
            count_query = count_query.where(Lead.assigned_to_user_id == assignee_id)

    sort_column = {
        "score": Lead.score,
        "company": Lead.company,
        "status": Lead.status,
        "created_at": Lead.created_at,
    }.get(sort, Lead.created_at)
    # Deterministic ordering with tiebreakers. Without these, ORDER BY score
    # (with many tied scores) returned a DIFFERENT order on every refetch — the
    # 6-sec poll made cards visibly reshuffle and a fresh batch of 10 looked
    # "перемешанным" with the old ones. created_at DESC groups the newest leads
    # at the top of each tie band; id is the final stable tiebreaker.
    order_cols = [sort_column.asc() if order == "asc" else sort_column.desc()]
    if sort != "created_at":
        order_cols.append(Lead.created_at.desc())
    order_cols.append(Lead.id)
    query = query.order_by(*order_cols)

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


# Full pipeline: new|contacted|qualified|proposal|won|rejected (derived from the
# LeadStatus enum so a new stage automatically becomes accepted everywhere).
VALID_STATUSES = {s.value for s in LeadStatus}


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

    fields_set = payload.model_fields_set

    if payload.status is not None:
        if payload.status not in VALID_STATUSES:
            raise HTTPException(
                status_code=422,
                detail=f"Недопустимый статус. Допустимые значения: {', '.join(sorted(VALID_STATUSES))}",
            )
        new_status = LeadStatus(payload.status)
        if new_status != lead.status:
            old_status = lead.status
            lead.status = new_status
            log_activity(
                db,
                lead=lead,
                kind="stage_changed",
                text=f"Стадия: {stage_label(old_status)} → {stage_label(new_status)}",
                user=user,
                meta={"from": old_status.value, "to": new_status.value},
            )

    # assigned_to_user_id — model_fields_set distinguishes an explicit null
    # (unassign) from an omitted field. A UUID must belong to a member of THIS
    # org (else 422); we resolve the display name for the activity text.
    if "assigned_to_user_id" in fields_set:
        new_assignee = payload.assigned_to_user_id
        if new_assignee is None:
            if lead.assigned_to_user_id is not None:
                lead.assigned_to_user_id = None
                log_activity(db, lead=lead, kind="unassigned", text="Снято назначение", user=user)
        else:
            is_member = db.scalar(
                select(func.count(Membership.id)).where(
                    Membership.organization_id == organization.id,
                    Membership.user_id == new_assignee,
                )
            ) or 0
            if not is_member:
                raise HTTPException(status_code=422, detail="Пользователь не в организации")
            if lead.assigned_to_user_id != new_assignee:
                lead.assigned_to_user_id = new_assignee
                assignee = db.get(User, new_assignee)
                name = (assignee.full_name or assignee.email or "") if assignee else ""
                log_activity(
                    db,
                    lead=lead,
                    kind="assigned",
                    text=f"Назначен: {name}",
                    user=user,
                    meta={"assigned_to": str(new_assignee)},
                )

    if payload.notes is not None and payload.notes != lead.notes:
        lead.notes = payload.notes
        log_activity(db, lead=lead, kind="note", text="Заметка обновлена", user=user)
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
    if payload.deal_value is not None and payload.deal_value != lead.deal_value:
        lead.deal_value = payload.deal_value
        log_activity(
            db,
            lead=lead,
            kind="value_changed",
            text=f"Сумма сделки: {payload.deal_value} ₽",
            user=user,
            meta={"deal_value": payload.deal_value},
        )
    # expected_close_at — explicit null clears it (model_fields_set guard).
    if "expected_close_at" in fields_set:
        lead.expected_close_at = payload.expected_close_at
    if payload.last_contacted_at is not None:
        lead.last_contacted_at = payload.last_contacted_at
    # Use model_fields_set so an explicit {"reminder_at": null} CLEARS the
    # reminder (the × button sends null); an omitted field leaves it untouched.
    # The old `is not None` guard silently ignored the clear → dead button.
    if "reminder_at" in fields_set:
        lead.reminder_at = payload.reminder_at
    if payload.mark_contacted:
        # Convenience flag — sets last_contacted_at=now() and bumps status to "contacted"
        # if it was still "new". Lets sales click one button after a call.
        lead.last_contacted_at = datetime.now(timezone.utc)
        if lead.status == LeadStatus.new:
            lead.status = LeadStatus.contacted
        log_activity(db, lead=lead, kind="contacted", text="Отмечен контакт", user=user)

    db.commit()
    db.refresh(lead)
    return lead


@router.post("/project/{project_id}/bulk", response_model=BulkResult)
def bulk_lead_action(
    project_id: uuid.UUID,
    payload: BulkLeadAction,
    organization: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Apply one action over many leads at once (assign / stage / add_tag / delete).

    Scoped to this org + project: ids outside the project are silently skipped
    (no cross-org/-project leak). Returns the count of affected leads. assign,
    stage and add_tag write an activity per affected lead; delete does not (the
    lead — and its timeline — is gone).
    """
    project = db.get(Project, project_id)
    if not project or project.organization_id != organization.id or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Проект не найден")

    action = payload.action

    # Validate the action payload up-front (before touching any rows).
    if action == "assign":
        if payload.assigned_to_user_id is not None:
            is_member = db.scalar(
                select(func.count(Membership.id)).where(
                    Membership.organization_id == organization.id,
                    Membership.user_id == payload.assigned_to_user_id,
                )
            ) or 0
            if not is_member:
                raise HTTPException(status_code=422, detail="Пользователь не в организации")
    elif action == "stage":
        if not payload.status or payload.status not in VALID_STATUSES:
            raise HTTPException(
                status_code=422,
                detail=f"Недопустимый статус. Допустимые значения: {', '.join(sorted(VALID_STATUSES))}",
            )
    elif action == "add_tag":
        tag = (payload.tag or "").strip()[:30]
        if not tag:
            raise HTTPException(status_code=422, detail="Пустой тег")
    elif action == "delete":
        pass
    else:
        raise HTTPException(status_code=422, detail="Неизвестное действие")

    # Fetch the in-scope leads (org + project). Anything not here is ignored.
    leads = db.execute(
        select(Lead).where(
            Lead.organization_id == organization.id,
            Lead.project_id == project.id,
            Lead.id.in_(payload.lead_ids),
        )
    ).scalars().all()
    if not leads:
        return BulkResult(updated=0)

    updated = 0

    if action == "assign":
        new_assignee = payload.assigned_to_user_id
        name = ""
        if new_assignee is not None:
            assignee = db.get(User, new_assignee)
            name = (assignee.full_name or assignee.email or "") if assignee else ""
        for lead in leads:
            if lead.assigned_to_user_id == new_assignee:
                continue
            lead.assigned_to_user_id = new_assignee
            if new_assignee is None:
                log_activity(db, lead=lead, kind="unassigned", text="Снято назначение", user=user)
            else:
                log_activity(
                    db,
                    lead=lead,
                    kind="assigned",
                    text=f"Назначен: {name}",
                    user=user,
                    meta={"assigned_to": str(new_assignee)},
                )
            updated += 1

    elif action == "stage":
        new_status = LeadStatus(payload.status)
        for lead in leads:
            if lead.status == new_status:
                continue
            old_status = lead.status
            lead.status = new_status
            log_activity(
                db,
                lead=lead,
                kind="stage_changed",
                text=f"Стадия: {stage_label(old_status)} → {stage_label(new_status)}",
                user=user,
                meta={"from": old_status.value, "to": new_status.value},
            )
            updated += 1

    elif action == "add_tag":
        tag = (payload.tag or "").strip()[:30]
        for lead in leads:
            existing = list(lead.tags or [])
            if any((e or "").lower() == tag.lower() for e in existing):
                continue
            if len(existing) >= 20:
                continue
            existing.append(tag)
            lead.tags = existing
            log_activity(
                db,
                lead=lead,
                kind="tag_added",
                text=f"Тег: {tag}",
                user=user,
                meta={"tag": tag},
            )
            updated += 1

    elif action == "delete":
        for lead in leads:
            db.delete(lead)
            updated += 1

    db.commit()
    return BulkResult(updated=updated)


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
