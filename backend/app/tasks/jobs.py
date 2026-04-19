import logging
from datetime import datetime, timezone
from uuid import UUID

from croniter import croniter
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from app.core.config import get_settings
from app.models import CollectionJob, JobStatus, Lead, Membership, Organization, Project, User
from app.services.lead_collection import enrich_2gis_lead, enrich_website_contacts, search_leads
from app.services.notifications import send_email, send_telegram
from app.services.scoring import score_lead
from app.tasks.celery_app import celery
from app.utils.url_tools import extract_domain, get_base_domain, is_aggregator_domain, is_real_domain, normalize_url

logger = logging.getLogger(__name__)


def _notify_owner_project_ready(db, project: Project, enriched_count: int) -> None:
    """Email the org owner that their project is enriched and ready to view.

    Best-effort — failures are logged but don't crash the enrich task.
    """
    # Find org owner (first owner in memberships)
    member = db.execute(
        select(Membership)
        .where(Membership.organization_id == project.organization_id)
        .where(Membership.role.in_(["owner", "admin"]))
        .order_by(Membership.role.asc())  # 'admin' < 'owner' alpha; we want owner first
    ).scalar_one_or_none()
    if not member:
        return
    user = db.get(User, member.user_id)
    if not user or not user.email:
        return

    # Compute lead stats for the email body
    total_leads = db.execute(
        select(func.count(Lead.id)).where(Lead.project_id == project.id)
    ).scalar_one() or 0
    with_phone = db.execute(
        select(func.count(Lead.id))
        .where(Lead.project_id == project.id)
        .where(Lead.phone != "")
    ).scalar_one() or 0
    with_email = db.execute(
        select(func.count(Lead.id))
        .where(Lead.project_id == project.id)
        .where(Lead.email != "")
    ).scalar_one() or 0

    settings = get_settings()
    site_url = settings.frontend_app_url.rstrip("/") if getattr(settings, "frontend_app_url", None) else "https://usebaza.ru"
    project_url = f"{site_url}/dashboard/projects/{project.id}"

    subject = f"БАЗА: {total_leads} лидов готовы — {project.name[:50]}"
    body = f"""Здравствуйте!

Ваш проект "{project.name}" готов:

  • Всего лидов: {total_leads}
  • Обогащено в этом запуске: {enriched_count}
  • С телефоном: {with_phone}
  • С email: {with_email}

Открыть проект:
{project_url}

Если вы не запускали этот сбор, проверьте кто из участников вашей организации это сделал.

—
БАЗА · usebaza.ru
"""

    try:
        send_email_task = celery.signature("email.send_email", args=[subject, body, user.email])
        send_email_task.delay()
        logger.info("Notified %s about project %s ready (%d leads)", user.email, project.id, total_leads)
    except Exception:
        logger.warning("Failed to enqueue notification email", exc_info=True)


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

        # If project has a prompt, use AI to determine customer-focused search terms
        effective_niche = project.niche
        effective_geo = project.geography
        effective_segments = list(project.segments) if project.segments else []
        user_prompt = project.prompt or ""

        if user_prompt:
            try:
                from app.services.prompt_enhancer import enhance_prompt
                enhanced = enhance_prompt(user_prompt)
                if enhanced.get("search_queries_niche"):
                    effective_niche = enhanced["search_queries_niche"]
                elif enhanced.get("niche"):
                    effective_niche = enhanced["niche"]
                if enhanced.get("geography") and enhanced["geography"] != "Россия":
                    effective_geo = enhanced["geography"]
                if enhanced.get("segments"):
                    effective_segments = enhanced["segments"]
                logger.info(
                    "AI enhanced search: niche='%s' geo='%s' segments=%s",
                    effective_niche, effective_geo, effective_segments,
                )
            except Exception:
                logger.warning("Prompt enhancement failed in job, using raw niche", exc_info=True)

        # Yandex Maps only for Pro/Team plans (premium feature)
        org = db.get(Organization, job.organization_id)
        use_yandex = org.plan.value in ("pro", "team") if org else False

        query = f"{effective_niche} {effective_geo} {' '.join(effective_segments)}"
        candidates = search_leads(
            query=query.strip(),
            limit=job.requested_limit,
            niche=effective_niche,
            geography=effective_geo,
            segments=effective_segments,
            prompt=user_prompt,
            use_yandex=use_yandex,
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

            website = normalize_url(c.get("website") or "")
            domain = extract_domain(website) if website else ""
            base_domain = get_base_domain(domain) if domain else ""
            company_name = c.get("company", "").strip()
            city_name = c.get("city", "").strip()
            source = c.get("source", "")

            # For maps leads without website — generate stable placeholder URL so unique constraint works.
            # For 2GIS, prefer the firm_id (if provided) — lets enrichment hit the firm page directly.
            if not website and company_name:
                import re as _re
                firm_id = (c.get("firm_id") or "").strip()
                if source == "2gis" and firm_id:
                    website = f"maps://2gis/{firm_id}"
                else:
                    slug_co = _re.sub(r"[^a-zа-я0-9]+", "-", company_name.lower()).strip("-")[:60]
                    slug_city = _re.sub(r"[^a-zа-я0-9]+", "-", city_name.lower()).strip("-")[:40]
                    website = f"maps://{source or 'offline'}/{slug_co}-{slug_city}"

            # Company name is REQUIRED (otherwise it's not a lead at all)
            if not company_name:
                continue
            # If we have a domain, it must be real (non-aggregator)
            if domain and (not is_real_domain(domain) or is_aggregator_domain(domain)):
                continue
            # For web sources without a domain — skip (they're just URLs that didn't extract)
            # For maps sources (2GIS/Yandex) without a domain — KEEP (real B2B lead with address/phone)
            is_maps = source in {"2gis", "yandex_maps"}
            if not domain and not is_maps:
                continue
            # Maps lead without website needs at least address or phone to be useful
            phone_val = (c.get("phone") or "").strip()
            address_val = (c.get("address") or "").strip()
            email_val = (c.get("email") or "").strip()
            if not domain and not phone_val and not address_val:
                continue

            # Dedup: by website/domain if present, else by (company+city) to avoid duplicates of same shop
            dup_query = select(Lead.id).where(Lead.project_id == project.id)
            if domain:
                dup_query = dup_query.where(
                    (Lead.website == website) | (Lead.domain == domain) | (Lead.domain == base_domain)
                )
            else:
                # Maps lead without site — dedup by company+city
                dup_query = dup_query.where(
                    Lead.company == _clip(company_name, 180),
                    Lead.city == _clip(city_name, 120),
                )
            existing = db.execute(dup_query).first()
            if existing:
                continue
            base_score = score_lead(
                domain=domain or "",
                company=company_name,
                niche=project.niche,
                has_email=bool(email_val),
                has_phone=bool(phone_val),
                has_address=bool(address_val),
                demo=bool(c.get("demo", False)),
                relevance_score=int(c.get("relevance_score", 0)),
            )
            lead = Lead(
                organization_id=job.organization_id,
                project_id=project.id,
                company=_clip(company_name, 180),
                city=_clip(city_name, 120),
                website=_clip(website, 300),
                domain=_clip(domain, 255),
                email=_clip(email_val, 255),
                phone=_clip(phone_val, 80),
                address=_clip(address_val, 300),
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
        # SELECT FOR UPDATE to prevent race when two collect jobs finish at the
        # same time and both read+write leads_used_current_month concurrently
        # (lost-update would let them collectively bypass the monthly cap).
        organization = db.execute(
            select(Organization)
            .where(Organization.id == job.organization_id)
            .with_for_update()
        ).scalar_one_or_none()
        if organization:
            organization.leads_used_current_month += added
        job.status = JobStatus.done
        if quota_stopped:
            job.error = "Остановлено: месячная квота лидов исчерпана"
        job.updated_at = datetime.now(timezone.utc)
        db.commit()
        send_telegram(f"Lead collection finished. Job={job.id} Added={job.added_count}")

        # ─── Auto-enrich freshly collected leads ───
        # User expectation: when a project finishes collecting, phones/emails
        # should already be populated — not in a separate manual step.
        #
        # Idempotency: collect_leads_task may be retried by Celery on transient
        # errors (ConnectionError/TimeoutError). Use SELECT FOR UPDATE to avoid
        # queueing a 2nd auto-enrich job when the first retry already queued one.
        if added > 0 and not quota_stopped:
            try:
                existing_auto_enrich = db.execute(
                    select(CollectionJob)
                    .where(
                        CollectionJob.project_id == job.project_id,
                        CollectionJob.kind == "enrich",
                        CollectionJob.status.in_([JobStatus.queued, JobStatus.running]),
                        CollectionJob.created_at >= job.created_at,
                    )
                    .with_for_update(skip_locked=True)
                ).scalar_one_or_none()
                if existing_auto_enrich:
                    logger.info(
                        "Auto-enrich already queued (job=%s), skipping duplicate",
                        existing_auto_enrich.id,
                    )
                else:
                    enrich_job = CollectionJob(
                        organization_id=job.organization_id,
                        project_id=job.project_id,
                        status=JobStatus.queued,
                        kind="enrich",
                        requested_limit=added,
                    )
                    db.add(enrich_job)
                    db.commit()
                    enrich_leads_task.delay(str(enrich_job.id))
                    logger.info("Auto-enrich queued after collect: project=%s enrich_job=%s",
                                job.project_id, enrich_job.id)
            except Exception:
                logger.warning("Failed to auto-queue enrich after collect", exc_info=True)
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
        # Alert ops — collect-job crash is unusual, worth knowing about.
        try:
            from app.services.notifications import send_alert
            send_alert(
                "error",
                "Collect job crashed",
                f"job_id={job_id}\nerror: {_safe_error_message(exc)[:300]}",
                key=f"collect_crash_{type(exc).__name__}",
                throttle_seconds=600,
            )
        except Exception:
            pass
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
            website = lead.website or ""
            if website.startswith("maps://"):
                # 2GIS/offline leads: scrape public 2gis.ru for phones/emails.
                # URL form for 2GIS: "maps://2gis/{firm_id}" — pull firm_id if present.
                firm_id = ""
                if website.startswith("maps://2gis/"):
                    candidate = website[len("maps://2gis/"):]
                    # firm IDs are purely numeric
                    if candidate.isdigit():
                        firm_id = candidate
                contacts = enrich_2gis_lead(lead.company, lead.city, firm_id=firm_id)
            else:
                contacts = enrich_website_contacts(website)
            lead.contacts = contacts
            lead.contacts_json = contacts
            raw_email = (contacts.get("emails") or [""])[0] if isinstance(contacts, dict) else ""
            raw_phone = (contacts.get("phones") or [""])[0] if isinstance(contacts, dict) else ""
            raw_address = (contacts.get("addresses") or [""])[0] if isinstance(contacts, dict) else ""
            # Preserve existing phone/email/address collected at search time
            # (2GIS API minimal tier populates these) if scraping didn't find new ones.
            if not raw_phone and lead.phone:
                raw_phone = lead.phone
            if not raw_email and lead.email:
                raw_email = lead.email
            if not raw_address and lead.address:
                raw_address = lead.address
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

        # ─── User-facing notification: project ready ───
        # Send email to the org owner so they don't have to hit refresh.
        # Only on completed jobs with leads (skip empty/failed).
        if enriched > 0 and project:
            try:
                _notify_owner_project_ready(db, project, enriched)
            except Exception:
                logger.warning("project-ready notification failed", exc_info=True)
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
        try:
            from app.services.notifications import send_alert
            send_alert(
                "error",
                "Enrich job crashed",
                f"job_id={job_id}\nerror: {_safe_error_message(exc)[:300]}",
                key=f"enrich_crash_{type(exc).__name__}",
                throttle_seconds=600,
            )
        except Exception:
            pass
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
