import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_org, require_org_roles
from app.db.session import get_db
from app.models import Lead, Organization, Project
from app.schemas.search import SearchCompaniesRequest, SearchPreviewRequest, SearchResultItem
from app.services.lead_collection import search_leads
from app.services.quota import ensure_lead_quota
from app.services.audit import log_action
from app.utils.url_tools import extract_domain

router = APIRouter(prefix="/search", tags=["search"])
logger = logging.getLogger("baza.search")


def _run_search(query: str, geography: str, limit: int) -> list[dict]:
    """Execute search_leads and return raw result dicts."""
    return search_leads(
        query=query,
        limit=limit,
        niche=query,
        geography=geography,
    )


def _to_result_items(raw_results: list[dict]) -> list[SearchResultItem]:
    """Convert raw search dicts into response items."""
    items: list[SearchResultItem] = []
    for row in raw_results:
        items.append(
            SearchResultItem(
                name=row.get("company", ""),
                domain=row.get("domain", "") or extract_domain(row.get("website", "")),
                url=row.get("website", ""),
                source=row.get("source", ""),
                city=row.get("city", ""),
                address=row.get("address", ""),
            )
        )
    return items


@router.post("/preview", response_model=list[SearchResultItem])
def search_preview(
    payload: SearchPreviewRequest,
    organization: Organization = Depends(get_current_org),
):
    """
    Dry-run search: returns matching companies from available sources
    without saving anything to the database.
    """
    raw = _run_search(payload.query, payload.geography, payload.limit)
    return _to_result_items(raw)


@router.post("/companies", response_model=list[SearchResultItem])
def search_and_save(
    payload: SearchCompaniesRequest,
    organization: Organization = Depends(get_current_org),
    membership=Depends(require_org_roles("owner", "admin")),
    db: Session = Depends(get_db),
):
    """
    Search for companies and save the results as leads in the specified project.
    """
    project = db.get(Project, payload.project_id)
    if not project or project.organization_id != organization.id:
        raise HTTPException(status_code=404, detail="Проект не найден")

    ensure_lead_quota(organization, payload.limit)

    raw = _run_search(payload.query, payload.geography, payload.limit)

    # Collect existing website URLs in this project to avoid duplicates
    existing_websites: set[str] = set(
        db.execute(
            select(Lead.website).where(Lead.project_id == project.id)
        ).scalars().all()
    )

    saved: list[dict] = []
    for row in raw:
        website = row.get("website", "")
        if not website or website in existing_websites:
            continue

        domain = row.get("domain", "") or extract_domain(website)
        lead = Lead(
            organization_id=organization.id,
            project_id=project.id,
            company=row.get("company", "")[:180],
            city=row.get("city", ""),
            website=website,
            domain=domain,
            address=row.get("address", "")[:300] if row.get("address") else "",
            source_url=row.get("source_url", ""),
            demo=bool(row.get("demo", False)),
            score=row.get("relevance_score", 0),
        )
        db.add(lead)
        existing_websites.add(website)
        saved.append(row)

    if saved:
        log_action(
            db,
            user_id=str(membership.user_id),
            organization_id=str(organization.id),
            action="search.companies.saved",
            meta={
                "project_id": str(project.id),
                "query": payload.query,
                "geography": payload.geography,
                "found": len(raw),
                "saved": len(saved),
            },
        )
        db.commit()

    return _to_result_items(saved)
