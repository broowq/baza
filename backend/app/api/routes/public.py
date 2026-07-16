"""Public, unauthenticated stats for the marketing landing page.

The landing page (frontend/components/landing/landing-v2.tsx) renders live-looking
product previews. Instead of hardcoded/fabricated numbers, those previews are fed
from THIS endpoint with REAL data drawn from the curated demo project that ships
with every БАЗА install (seeded by app/seed.py).

Safety / privacy:
- Aggregates only; sample rows come exclusively from the demo organization
  ("БАЗА Демо"), never from real customer projects.
- Contact details (email / phone) are NEVER returned — only boolean has_email /
  has_phone flags — so nothing sensitive is exposed on a public endpoint.
- Result is cached in-process for 5 minutes to shield the DB from landing traffic.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import CollectionJob, Lead, LeadStatus, Organization, Project

router = APIRouter(prefix="/public", tags=["public"])

_DEMO_ORG_NAME = "БАЗА Демо"
_CACHE_TTL_SECONDS = 300
_cache: dict[str, object] = {"at": 0.0, "data": None}


def _empty_payload() -> dict:
    return {
        "available": False,
        "totals": {"leads": 0, "enriched": 0, "with_email": 0, "with_phone": 0, "qualified": 0},
        "rates": {"enrichment": 0.0, "email": 0.0, "phone": 0.0, "qualified": 0.0},
        "avg_score": 0.0,
        "sources": [],
        "by_city": [],
        "funnel": {"found": 0, "added": 0, "enriched": 0, "qualified": 0},
        "samples": [],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _compute(db: Session) -> dict:
    org = db.execute(
        select(Organization).where(Organization.name == _DEMO_ORG_NAME)
    ).scalar_one_or_none()
    project = None
    if org is not None:
        # Витрина = живой демо-проект с НАИБОЛЬШИМ числом лидов (инцидент
        # 14.07: «первый по created_at» оказался пустым после чистки старых
        # демо-проектов — лендинг показывал «0 лидов в демо-базе» на первом
        # экране в день старта продаж).
        project = db.execute(
            select(Project)
            .outerjoin(Lead, Lead.project_id == Project.id)
            .where(
                Project.organization_id == org.id,
                Project.deleted_at.is_(None),
            )
            .group_by(Project.id)
            .order_by(func.count(Lead.id).desc(), Project.created_at.asc())
        ).scalars().first()
    if project is None:
        return _empty_payload()

    pid = project.id

    def count(*conds) -> int:
        return db.scalar(select(func.count(Lead.id)).where(Lead.project_id == pid, *conds)) or 0

    total = count()
    if total == 0:
        return _empty_payload()

    enriched = count(Lead.enriched.is_(True))
    with_email = count(Lead.email != "")
    with_phone = count(Lead.phone != "")
    qualified = count(Lead.status == LeadStatus.qualified)
    avg_score = float(
        db.scalar(select(func.avg(Lead.score)).where(Lead.project_id == pid)) or 0
    )

    # Source distribution (real).
    source_rows = db.execute(
        select(Lead.source, func.count(Lead.id))
        .where(Lead.project_id == pid, Lead.source != "")
        .group_by(Lead.source)
        .order_by(func.count(Lead.id).desc())
    ).all()
    sources = [{"source": s, "count": int(c)} for s, c in source_rows]

    # Per-city distribution (real) — powers the regional chart with lead volume +
    # average score (NOT fabricated "revenue").
    city_rows = db.execute(
        select(Lead.city, func.count(Lead.id), func.avg(Lead.score))
        .where(Lead.project_id == pid, Lead.city != "")
        .group_by(Lead.city)
        .order_by(func.count(Lead.id).desc())
        .limit(9)
    ).all()
    by_city = [
        {"city": c, "count": int(n), "avg_score": round(float(a or 0))}
        for c, n, a in city_rows
    ]

    # Funnel from real collection-job aggregates, falling back to lead counts.
    found_sum = int(
        db.scalar(
            select(func.coalesce(func.sum(CollectionJob.found_count), 0)).where(
                CollectionJob.project_id == pid
            )
        ) or 0
    )
    added_sum = int(
        db.scalar(
            select(func.coalesce(func.sum(CollectionJob.added_count), 0)).where(
                CollectionJob.project_id == pid
            )
        ) or 0
    )
    funnel = {
        "found": found_sum or total,
        "added": added_sum or total,
        "enriched": enriched,
        "qualified": qualified,
    }

    # Sample rows — top by score, contacts MASKED to booleans.
    sample_leads = db.execute(
        select(Lead).where(Lead.project_id == pid).order_by(Lead.score.desc()).limit(8)
    ).scalars().all()
    samples = [
        {
            "company": lead.company,
            "city": lead.city,
            "score": int(lead.score),
            "source": lead.source,
            "has_email": bool(lead.email),
            "has_phone": bool(lead.phone),
            "email_valid": lead.email_status == "valid",
        }
        for lead in sample_leads
    ]

    def rate(n: int) -> float:
        return round(n / total, 3) if total else 0.0

    return {
        "available": True,
        "totals": {
            "leads": total,
            "enriched": enriched,
            "with_email": with_email,
            "with_phone": with_phone,
            "qualified": qualified,
        },
        "rates": {
            "enrichment": rate(enriched),
            "email": rate(with_email),
            "phone": rate(with_phone),
            "qualified": rate(qualified),
        },
        "avg_score": round(avg_score, 1),
        "sources": sources,
        "by_city": by_city,
        "funnel": funnel,
        "samples": samples,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/landing")
def landing_stats(db: Session = Depends(get_db)) -> dict:
    """Real, cached, privacy-safe stats for the public landing page."""
    now = time.time()
    cached = _cache.get("data")
    if cached is not None and (now - float(_cache.get("at", 0.0))) < _CACHE_TTL_SECONDS:
        return cached  # type: ignore[return-value]
    data = _compute(db)
    _cache["at"] = now
    _cache["data"] = data
    return data
