import logging
from datetime import datetime, timezone
from uuid import UUID

from croniter import croniter
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from app.models import CollectionJob, JobStatus, Lead, Organization, Project
from app.services.lead_collection import enrich_website_contacts, search_leads
from app.services.notifications import send_telegram
from app.services.scoring import score_lead
from app.tasks.celery_app import celery
from app.utils.url_tools import extract_domain, get_base_domain, is_aggregator_domain, is_real_domain, normalize_url

logger = logging.getLogger(__name__)


def _check_quota_with_lock(db, organization_id) -> int:
    """Return remaining lead quota using SELECT FOR UPDATE to prevent races.

    Returns the number of leads the org can still add this month.
    """
    org = db.execute(
        select(Organization)
        .where(Organization.id == organization_id)
        .with_for_update()
    ).scalar_one()
    return max(0, org.leads_limit_per_month - org.leads_used_current_month)


def _safe_error_message(exc: Exception) -> str:
    message = str(exc).strip().replace("\n", " ")
    if not message:
        return "Неизвестная ошибка"
    return message[:500]


def _clip(value: str, max_len: int) -> str:
    return (value or "")[:max_len]


@celery.task(
    name="jobs.collect_leads",
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    max_retries=3,
)
def collect_leads_task(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(CollectionJob, UUID(job_id))
        if not job:
            return
        project = db.get(Project, job.project_id)
        if not project:
            job.status = JobStatus.failed
            job.error = "Project not found"
            db.commit()
            return
        job.status = JobStatus.running
        db.commit()

        query = f"{project.niche} {project.geography} {' '.join(project.segments)}"
        candidates = search_leads(
            query=query.strip(),
            limit=job.requested_limit,
            niche=project.niche,
            geography=project.geography,
            segments=list(project.segments) if project.segments else [],
        )
        job.found_count = len(candidates)
        db.commit()

        added = 0
        quota_stopped = False
        for i, c in enumerate(candidates):
            # Re-check quota every 10 leads using SELECT FOR UPDATE
            if added % 10 == 0:
                remaining = _check_quota_with_lock(db, job.organization_id)
                if remaining <= 0:
                    logger.warning(
                        "Quota exceeded mid-job for org=%s job=%s after %d leads",
                        job.organization_id, job.id, added,
                    )
                    quota_stopped = True
                    break

            website = normalize_url(c["website"])
            domain = extract_domain(website)
            base_domain = get_base_domain(domain)
            company_name = c.get("company", "").strip()
            if not website or not is_real_domain(domain) or is_aggregator_domain(domain) or not company_name:
                continue
            existing = db.execute(
                select(Lead.id).where(
                    Lead.project_id == project.id,
                    (Lead.website == website) | (Lead.domain == domain) | (Lead.domain == base_domain),
                )
            ).first()
            if existing:
                continue
            base_score = score_lead(
                domain=domain,
                company=company_name,
                niche=project.niche,
                has_email=False,
                has_phone=False,
                has_address=False,
                demo=bool(c.get("demo", False)),
                relevance_score=int(c.get("relevance_score", 0)),
            )
            lead = Lead(
                organization_id=job.organization_id,
                project_id=project.id,
                company=_clip(company_name, 180),
                city=_clip(c.get("city", ""), 120),
                website=_clip(website, 300),
                domain=_clip(domain, 255),
                email="",
                phone="",
                address="",
                source_url=_clip(c.get("source_url", ""), 400),
                score=base_score,
                notes=("demo=true; " if c.get("demo") else "") + c.get("snippet", ""),
                demo=bool(c.get("demo", False)),
            )
            db.add(lead)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                continue
            added += 1
            if added % 10 == 0:
                job.added_count = added
                job.updated_at = datetime.now(timezone.utc)
                db.commit()
        job.added_count = added
        organization = db.get(Organization, job.organization_id)
        if organization:
            organization.leads_used_current_month += added
        job.status = JobStatus.done
        if quota_stopped:
            job.error = "Остановлено: месячная квота лидов исчерпана"
        job.updated_at = datetime.now(timezone.utc)
        db.commit()
        send_telegram(f"Lead collection finished. Job={job.id} Added={job.added_count}")
    except (ConnectionError, TimeoutError) as exc:
        logger.warning(
            "collect_leads_task transient error for job_id=%s (retry %s/%s): %s",
            job_id,
            collect_leads_task.request.retries,
            collect_leads_task.max_retries,
            exc,
        )
        db.rollback()
        # On final retry failure, mark job as failed
        if collect_leads_task.request.retries >= collect_leads_task.max_retries:
            job = db.get(CollectionJob, UUID(job_id))
            if job:
                job.status = JobStatus.failed
                job.error = f"Все попытки исчерпаны: {_safe_error_message(exc)}"
                db.commit()
        raise  # let Celery autoretry handle it
    except Exception as exc:
        logger.exception("collect_leads_task failed for job_id=%s", job_id)
        db.rollback()
        job = db.get(CollectionJob, UUID(job_id))
        if job:
            job.status = JobStatus.failed
            job.error = _safe_error_message(exc)
            db.commit()
    finally:
        db.close()


@celery.task(
    name="jobs.enrich_leads",
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    max_retries=3,
)
def enrich_leads_task(job_id: str, lead_ids: list[str] | None = None) -> None:
    db = SessionLocal()
    try:
        job = db.get(CollectionJob, UUID(job_id))
        if not job:
            return
        job.status = JobStatus.running
        db.commit()

        query = select(Lead).where(
            Lead.project_id == job.project_id,
            or_(
                Lead.enriched.is_(False),
                (Lead.email == "") & (Lead.phone == "") & (Lead.address == ""),
            ),
        )
        if lead_ids:
            safe_ids: list[UUID] = []
            for raw in lead_ids:
                try:
                    safe_ids.append(UUID(raw))
                except Exception:
                    continue
            if safe_ids:
                query = query.where(Lead.id.in_(safe_ids))
        query = query.limit(job.requested_limit)
        leads = db.execute(query).scalars().all()
        project = db.get(Project, job.project_id)
        project_niche = project.niche if project else ""
        enriched = 0
        for lead in leads:
            contacts = enrich_website_contacts(lead.website)
            lead.contacts = contacts
            lead.contacts_json = contacts
            raw_email = (contacts.get("emails") or [""])[0] if isinstance(contacts, dict) else ""
            raw_phone = (contacts.get("phones") or [""])[0] if isinstance(contacts, dict) else ""
            raw_address = (contacts.get("addresses") or [""])[0] if isinstance(contacts, dict) else ""
            lead.email = _clip(raw_email, 255)
            lead.phone = _clip(raw_phone, 80)
            lead.address = _clip(raw_address, 300)
            lead.enriched = True
            lead.score = score_lead(
                domain=lead.domain,
                company=lead.company,
                niche=project_niche,
                has_email=bool(lead.email),
                has_phone=bool(lead.phone),
                has_address=bool(lead.address),
                demo=lead.demo,
            )
            enriched += 1
            if enriched % 5 == 0:
                job.enriched_count = enriched
                job.updated_at = datetime.now(timezone.utc)
                db.commit()
        job.enriched_count = enriched
        job.status = JobStatus.done
        job.updated_at = datetime.now(timezone.utc)
        db.commit()
        send_telegram(f"Lead enrichment finished. Job={job.id} Enriched={job.enriched_count}")
    except (ConnectionError, TimeoutError) as exc:
        logger.warning(
            "enrich_leads_task transient error for job_id=%s (retry %s/%s): %s",
            job_id,
            enrich_leads_task.request.retries,
            enrich_leads_task.max_retries,
            exc,
        )
        db.rollback()
        if enrich_leads_task.request.retries >= enrich_leads_task.max_retries:
            job = db.get(CollectionJob, UUID(job_id))
            if job:
                job.status = JobStatus.failed
                job.error = f"Все попытки исчерпаны: {_safe_error_message(exc)}"
                db.commit()
        raise
    except Exception as exc:
        logger.exception("enrich_leads_task failed for job_id=%s", job_id)
        db.rollback()
        job = db.get(CollectionJob, UUID(job_id))
        if job:
            job.status = JobStatus.failed
            job.error = _safe_error_message(exc)
            db.commit()
    finally:
        db.close()


@celery.task(name="jobs.schedule_auto_collection")
def schedule_auto_collection() -> None:
    now = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        projects = db.execute(select(Project).where(Project.auto_collection_enabled.is_(True))).scalars().all()
        for project in projects:
            try:
                current = croniter(project.cron_schedule, now).get_prev(datetime)
            except Exception:
                continue
            if int((now - current).total_seconds()) > 90:
                continue
            # Блокировка на уровне БД для предотвращения гонки между несколькими воркерами
            existing_running = db.execute(
                select(CollectionJob)
                .where(
                    CollectionJob.project_id == project.id,
                    CollectionJob.status.in_([JobStatus.queued, JobStatus.running]),
                    CollectionJob.kind == "collect",
                )
                .with_for_update(skip_locked=True)
            ).scalar_one_or_none()
            if existing_running:
                continue
            job = CollectionJob(
                organization_id=project.organization_id,
                project_id=project.id,
                status=JobStatus.queued,
                kind="collect",
                requested_limit=100,
            )
            db.add(job)
            db.flush()
            collect_leads_task.delay(str(job.id))
            # Коммитим каждый проект отдельно для минимизации окна блокировки
            db.commit()
    except Exception:
        logger.exception("schedule_auto_collection failed")
        db.rollback()
    finally:
        db.close()
