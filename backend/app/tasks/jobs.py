import logging
import re as _re
from datetime import datetime, timedelta, timezone
from uuid import UUID

from celery.exceptions import SoftTimeLimitExceeded
from croniter import croniter
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal
from app.core.config import get_settings
from app.models import CollectionJob, JobStatus, Lead, Membership, Organization, Project, User
from app.services import company_warehouse
from app.services import quota
from app.services.lead_collection import _NATIONWIDE_GEOS, _get_redis, enrich_2gis_lead, enrich_website_contacts, search_leads, yandex_search_company_lookup
from app.services.llm_filter import filter_candidates_llm
from app.services.notifications import send_email, send_telegram
from app.services.scoring import score_lead
from app.tasks.celery_app import celery
from app.utils.url_tools import extract_domain, get_base_domain, is_aggregator_domain, is_real_domain, normalize_url

# Maximum concurrent queued/running jobs per organisation (mirrors the API guard).
# Used by the auto-enrich step so it doesn't bypass the same cap the API enforces.
_MAX_CONCURRENT_JOBS_PER_ORG = 3

# Минимальная доля лидов с контактами в дозе. Аудит 09.07: warehouse-first
# забивал дозу бесконтактными строками, live-поиск (единственный источник
# телефонов) не запускался месяц, 57% июльских лидов ушли клиентам пустыми.
# Если доля ниже — live-добор стартует ДАЖЕ при заполненной дозе, и пустышки
# заменяются контактными live-находками.
_DOSE_MIN_CONTACT_SHARE = 0.7


def _matches_website_preference(c: dict, preference: str) -> bool:
    """Соответствие кандидата требованию к сайту клиента (инцидент 14.07).

    «Реальный сайт» = извлекаемый домен с точкой (maps:// и пустые не в счёт).
    Для no_website такой кандидат не годится ДАЖЕ с контактами — юзер
    (веб-студия) продаёт создание сайта тем, у кого его нет.
    """
    if preference not in ("no_website", "with_website"):
        return True
    website = normalize_url(c.get("website") or "")
    domain = (extract_domain(website) if website else "") or (c.get("domain") or "").strip().lower()
    has_site = bool(domain) and "." in domain
    return not has_site if preference == "no_website" else has_site


def _candidate_has_contact(c: dict) -> bool:
    return bool((c.get("phone") or "").strip() or (c.get("email") or "").strip())

logger = logging.getLogger(__name__)


# Sources whose results can be a real B2B lead WITHOUT a website/domain:
# map cards (2GIS / Yandex), our own warehouse, and rusprofile registry rows.
# rusprofile rows are name-only at collect time, but they are verified legal
# entities and enrichment's 2GIS-by-name fallback can fill contacts later.
_NO_DOMAIN_OK_SOURCES = {"2gis", "yandex_maps", "warehouse", "rusprofile"}


def _has_rusprofile_id(c: dict) -> bool:
    return bool(str(c.get("rusprofile_id") or "").strip())


def _candidate_saveable(c: dict) -> bool:
    """True when a candidate can pass the save-loop checks in collect_leads_task.

    _take() uses this so unsaveable rows never occupy a dose slot. Without it,
    rows that can never be persisted (e.g. name-only registry rows) fill the
    dose, the deficit gate sees no deficit, live search never runs, added==0 —
    and the user gets a permanent, false «всё доступное уже собрано».

    KEEP IN SYNC with the save loop in collect_leads_task.
    """
    if not (c.get("company") or "").strip():
        return False
    website = normalize_url(c.get("website") or "")
    domain = (extract_domain(website) if website else "") or (c.get("domain") or "").strip().lower()
    if domain and (not is_real_domain(domain) or is_aggregator_domain(domain)):
        return False
    if not domain:
        if c.get("source", "") not in _NO_DOMAIN_OK_SOURCES:
            return False
        phone_val = (c.get("phone") or "").strip()
        address_val = (c.get("address") or "").strip()
        # Contact-less rows are only useful when enrichment can recover the
        # contacts later — which it can for rusprofile-identified entities
        # (2GIS-by-name fallback in enrich_leads_task).
        if not phone_val and not address_val and not _has_rusprofile_id(c):
            return False
    return True


def _as_utc(dt: datetime | None) -> datetime | None:
    """Treat a stored (possibly naive) timestamp as UTC for tz-aware math."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _project_dedup_keys(db, project_id) -> set[str]:
    """dedup_keys of every company already collected for a project — the set we
    exclude so each dose returns NEW businesses. Keys match the warehouse's
    identity rule (base domain, else normalized_name|city)."""
    keys: set[str] = set()
    for domain, company, city in db.execute(
        select(Lead.domain, Lead.company, Lead.city).where(Lead.project_id == project_id)
    ).all():
        k = company_warehouse.lead_key(domain=domain or "", company=company or "", city=city or "")
        if k:
            keys.add(k)
    return keys


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
        # acks_late guard: with task_acks_late + reject_on_worker_lost, a task
        # whose worker died mid-run is redelivered. If health_check already
        # failed this job (or it somehow finished), do NOT revive it — just ack
        # and exit. A still-'running'/'queued' job is re-run from scratch, which
        # is safe (dedup-by-domain prevents duplicate leads, savepoints isolate
        # per-lead writes).
        if job.status in (JobStatus.failed, JobStatus.done):
            logger.info("collect_leads_task: job %s already %s — skip redelivery", job_id, job.status)
            return
        project = db.get(Project, job.project_id)
        if not project:
            job.status = JobStatus.failed
            job.error = "Project not found"
            db.commit()
            return
        job.status = JobStatus.running
        # Heartbeat: bump updated_at on the queued→running transition so the
        # 30-min reaper in periodic.health_check doesn't measure staleness from
        # the row's creation time and kill a job that only just started.
        job.updated_at = datetime.now(timezone.utc)
        db.commit()

        # Search terms. The project already stores the enhanced geo/segments (set
        # at create/edit). For the niche we use the LLM "search_queries_niche",
        # but CACHED on the project (project.search_query) — computed once and
        # reused by every dose, so dosed collection doesn't pay for an LLM
        # prompt-enhance on each run. Cache miss (prompt set, no cached query yet)
        # → enhance ONCE here and persist.
        effective_niche = project.niche
        effective_geo = project.geography
        effective_segments = list(project.segments) if project.segments else []
        # Жёсткие исключения из промпта («только b2b» → не розница/НКО/фермы):
        # уважаются складским отбором, LLM-фильтром дозы и live-поиском.
        excluded_segments = [
            e.strip() for e in (getattr(project, "excluded_segments", None) or [])
            if e and e.strip()
        ]
        user_prompt = project.prompt or ""
        # Требование к сайту клиента («без сайтов» — инцидент 14.07):
        # уважается складским SQL, live-скорингом, LLM-фильтром и save-loop'ом.
        website_preference = getattr(project, "website_preference", "any") or "any"

        if user_prompt and not (project.search_query or "").strip():
            try:
                from app.services.prompt_enhancer import enhance_prompt
                enhanced = enhance_prompt(user_prompt, organization_id=str(job.organization_id))
                sq = (enhanced.get("search_queries_niche") or enhanced.get("niche") or "").strip()
                # Cache the enhanced query ONLY when it came from the real LLM
                # ("source" absent defaults to "llm" for backward compat).
                # Caching a rule-based fallback would permanently lock the
                # project on degraded terms after a single LLM outage.
                if sq and enhanced.get("source", "llm") == "llm":
                    project.search_query = sq[:300]
                    db.commit()
                    logger.info("AI enhanced search (cached): niche='%s'", project.search_query)
                elif sq:
                    effective_niche = sq[:300]
                    logger.info(
                        "AI enhancer fallback (source=%s): using terms for this run only, not caching",
                        enhanced.get("source"),
                    )
            except Exception:
                logger.warning("Prompt enhancement failed in job, using stored niche", exc_info=True)

        if (project.search_query or "").strip():
            effective_niche = project.search_query.strip()

        # Yandex Maps only for paid tiers with a Yandex cap (Team/Pro/Business —
        # premium feature), AND only while the org has paid Yandex-request budget
        # left this month — the per-org cap that bounds the dominant variable
        # cost. When exhausted, collection silently falls back to the free
        # sources (2GIS/SearXNG) for this org.
        org = db.get(Organization, job.organization_id)
        use_yandex = (
            org.plan.value in ("growth", "pro", "team")
            and quota.yandex_requests_remaining(org) > 0
            if org else False
        )

        # ─── Dosed, warehouse-first, no-repeat collection ─────────────────
        # Selection layer = our own company warehouse; seeding layer = live
        # search. Each run delivers a small DOSE of companies NOT already in this
        # project, served first from the warehouse (free, cross-org), and only if
        # the dose can't be filled do we pay for a live search — which is written
        # through to the warehouse so future doses (here AND for any other org on
        # the same niche+geo) come for free. See memory: dosed-warehouse-first.
        settings = get_settings()
        warehouse_on = getattr(settings, "warehouse_search_enabled", True)
        seed_limit = int(getattr(settings, "warehouse_seed_limit", 150))
        cooldown_h = int(getattr(settings, "collect_exhaust_cooldown_hours", 12))
        batch_size = max(1, min(int(job.requested_limit or 10), 200))
        # Clamp the dose to the org's remaining monthly quota at selection time:
        # selecting candidates the save loop will refuse anyway only burns
        # warehouse rows and LLM-filter calls. May clamp to 0 → nothing is
        # selected and the job reports the quota stop honestly below.
        org_remaining_quota = (
            max(0, org.leads_limit_per_month - org.leads_used_current_month) if org else 0
        )
        batch_size = min(batch_size, org_remaining_quota)

        # Companies already collected for THIS project — excluded so every dose
        # brings genuinely NEW businesses (no repeats on re-run).
        already_keys = _project_dedup_keys(db, project.id)

        candidates: list[dict] = []
        chosen: set[str] = set(already_keys)

        def _take(rows: list[dict]) -> int:
            n = 0
            for r in rows:
                if len(candidates) >= batch_size:
                    break
                k = company_warehouse.candidate_key(r)
                if not k or k in chosen:
                    continue
                # Mirror the save-loop viability rules: a candidate that can
                # never be persisted must not occupy a dose slot, or unsaveable
                # rows re-served by best_score DESC brick the dose forever
                # (deficit gate falsely False → live never runs → «всё собрано»).
                # Mark it chosen anyway so warehouse re-selects skip it this run.
                if not _candidate_saveable(r):
                    chosen.add(k)
                    continue
                if not _matches_website_preference(r, website_preference):
                    chosen.add(k)
                    continue
                chosen.add(k)
                candidates.append(r)
                n += 1
            return n

        # 1) Warehouse-first (free): pull a dose from our DB, excluding what the
        #    project already has.
        wh_used = 0
        if warehouse_on:
            try:
                wh_used = _take(company_warehouse.search_warehouse(
                    db, niche=effective_niche, geography=effective_geo,
                    segments=effective_segments,
                    excluded_segments=excluded_segments,
                    website_preference=website_preference, limit=batch_size,
                    exclude_keys=already_keys,
                ))
            except Exception:
                logger.warning("warehouse-first select failed", exc_info=True)
                db.rollback()

        # 2) Live seed (paid) only when the warehouse can't fill the dose AND we
        #    are not in the post-exhaustion cooldown. Live finds are written
        #    through, then we re-select the dose from the now-seeded warehouse.
        live_count = 0
        did_live = False
        contactful = sum(1 for c in candidates if _candidate_has_contact(c))
        contact_deficit = bool(candidates) and contactful < int(len(candidates) * _DOSE_MIN_CONTACT_SHARE)
        if contact_deficit:
            logger.info(
                "dose contact deficit: %d/%d candidates have contacts (<%d%%) — live seed will run",
                contactful, len(candidates), int(_DOSE_MIN_CONTACT_SHARE * 100),
            )
        # Contact-deficit-only (доза ПОЛНА, но бедна контактами): без кулдауна
        # это жгло бы Яндекс/LLM на КАЖДОМ сборе контакто-бедной ниши (ревью
        # 09.07). Redis-кулдаун (тот же что у exhaustion) — не чаще раза в
        # cooldown_h часов на проект, если прошлый live-добор не принёс контактов.
        contact_deficit_only = contact_deficit and len(candidates) >= batch_size
        _contact_cd_key = f"contact_live_cd:{project.id}"
        if contact_deficit_only:
            _r = _get_redis()
            try:
                if _r is not None and _r.get(_contact_cd_key):
                    contact_deficit = False  # ещё в кулдауне — отдаём складскую дозу как есть
                    logger.info("contact-deficit live in cooldown — delivering warehouse dose as-is")
            except Exception:
                pass
        if len(candidates) < batch_size or contact_deficit:
            exhausted_at = _as_utc(project.leads_exhausted_at)
            in_cooldown = (
                exhausted_at is not None
                and (datetime.now(timezone.utc) - exhausted_at) < timedelta(hours=cooldown_h)
            )
            # Non-locking quota estimate: don't pay for a live seed the org can't
            # use anyway (the save loop still enforces the precise locked cap).
            # This also keeps a pure quota-stop from being mistaken for source
            # exhaustion below (did_live stays False → no cooldown stamp).
            org_remaining = (org.leads_limit_per_month - org.leads_used_current_month) if org else 0
            if not in_cooldown and org_remaining > 0:
                did_live = True
                query = f"{effective_niche} {effective_geo} {' '.join(effective_segments)}"
                live = search_leads(
                    query=query.strip(),
                    limit=max(seed_limit, batch_size),
                    niche=effective_niche,
                    geography=effective_geo,
                    segments=effective_segments,
                    prompt=user_prompt,
                    excluded_segments=excluded_segments,
                    website_preference=website_preference,
                    use_yandex=use_yandex,
                    organization_id=str(job.organization_id),
                )
                live_count = len(live)
                # Web rows (searxng/bing) carry no city → their warehouse rows
                # would have empty city/region/address and the geo-filtered
                # re-select below could never surface them. Stamp the project
                # geo onto city-less rows before write-through — but only when
                # the geo is specific (skip «Россия»-style nationwide geos).
                geo_backfill = (effective_geo or "").strip()
                if geo_backfill and geo_backfill.lower() not in _NATIONWIDE_GEOS:
                    for r in live:
                        if not (r.get("city") or "").strip():
                            r["city"] = geo_backfill
                stored = 0
                if warehouse_on:
                    try:
                        stored = company_warehouse.upsert_companies(db, live, niche=effective_niche)
                        logger.info("warehouse: seeded %d/%d live finds", stored, live_count)
                    except Exception:
                        logger.warning("warehouse seed write-through failed", exc_info=True)
                        db.rollback()
                    # Re-select the dose from the freshly-seeded warehouse so the
                    # whole selection stays single-sourced and consistently ranked.
                    try:
                        _take(company_warehouse.search_warehouse(
                            db, niche=effective_niche, geography=effective_geo,
                            segments=effective_segments,
                            excluded_segments=excluded_segments,
                            website_preference=website_preference, limit=batch_size,
                            exclude_keys=chosen,
                        ))
                    except Exception:
                        logger.warning("warehouse re-select after seed failed", exc_info=True)
                        db.rollback()
                # Fall back to the raw live rows whenever the dose is still
                # under-filled. (Previously gated on `stored == 0`, which sent
                # paid live finds to the customer ZERO times when the rows
                # upserted fine but the geo re-select couldn't surface them.)
                # Strictly safe: _take dedups via `chosen`, so nothing already
                # delivered by the re-select is taken twice.
                if len(candidates) < batch_size:
                    _take(live)

                # Доза полна, но бедна контактами → заменяем пустышки на
                # контактные live-находки (сами пустышки остаются в `chosen`,
                # чтобы этот запуск их больше не подобрал; в склад они уже
                # записаны и дождутся обогащения).
                if contact_deficit:
                    pool = [
                        r for r in live
                        if _candidate_has_contact(r) and _candidate_saveable(r)
                        and _matches_website_preference(r, website_preference)
                        and (company_warehouse.candidate_key(r) or "") not in chosen
                    ]
                    replaced = 0
                    for i, c in enumerate(candidates):
                        if not pool:
                            break
                        if _candidate_has_contact(c):
                            continue
                        repl = pool.pop(0)
                        rk = company_warehouse.candidate_key(repl)
                        if rk:
                            chosen.add(rk)
                        candidates[i] = repl
                        replaced += 1
                    if replaced:
                        logger.info("dose contact upgrade: replaced %d contactless candidate(s)", replaced)
                    # Если live НЕ добавил контактов (нет контактных строк в
                    # нише) — ставим кулдаун, чтобы следующие сборы не жгли
                    # Яндекс/LLM впустую до истечения окна.
                    if contact_deficit_only and replaced == 0:
                        try:
                            _r2 = _get_redis()
                            if _r2 is not None:
                                _r2.setex(_contact_cd_key, cooldown_h * 3600, "1")
                        except Exception:
                            pass

        # ─── Buyer-vs-competitor LLM filter on the assembled dose ────────
        # The only other filter_candidates_llm call lives inside search_leads
        # (live path) — doses served from the WAREHOUSE used to reach the
        # project with no competitor check at all, so customer B could receive
        # competitors that merely passed customer A's filter. Filter the whole
        # dose here (the 7-day Redis verdict cache makes repeats nearly free)
        # and top the dose back up from the warehouse if it shrank.
        if candidates:
            try:
                kept = filter_candidates_llm(
                    candidates, effective_niche, effective_geo, effective_segments,
                    prompt=user_prompt, excluded_segments=excluded_segments,
                    website_preference=website_preference,
                    organization_id=str(job.organization_id),
                )
            except Exception:
                logger.warning("dose LLM filter failed — delivering unfiltered dose", exc_info=True)
                kept = candidates
            dropped = len(candidates) - len(kept)
            if dropped > 0:
                logger.info("dose filter: dropped %d/%d candidate(s)", dropped, len(candidates))
            candidates = kept
            topup_round = 0
            while (
                dropped > 0 and warehouse_on
                and len(candidates) < batch_size and topup_round < 3
            ):
                topup_round += 1
                try:
                    rows = company_warehouse.search_warehouse(
                        db, niche=effective_niche, geography=effective_geo,
                        segments=effective_segments,
                        excluded_segments=excluded_segments,
                        website_preference=website_preference, limit=batch_size,
                        exclude_keys=chosen,
                    )
                except Exception:
                    logger.warning("warehouse top-up select failed", exc_info=True)
                    db.rollback()
                    break
                # Stage viable, novel rows; mark their keys chosen so the next
                # round skips them whether or not they survive the filter.
                staged: list[dict] = []
                for r in rows:
                    if len(candidates) + len(staged) >= batch_size:
                        break
                    k = company_warehouse.candidate_key(r)
                    if not k or k in chosen:
                        continue
                    chosen.add(k)
                    if not _candidate_saveable(r):
                        continue
                    staged.append(r)
                if not staged:
                    break  # warehouse exhausted for this niche+geo
                try:
                    staged = filter_candidates_llm(
                        staged, effective_niche, effective_geo, effective_segments,
                        prompt=user_prompt, excluded_segments=excluded_segments,
                        website_preference=website_preference,
                        organization_id=str(job.organization_id),
                    )
                except Exception:
                    logger.warning("top-up LLM filter failed — keeping unfiltered top-up", exc_info=True)
                candidates.extend(staged[: max(0, batch_size - len(candidates))])

        logger.info(
            "dosed collect: dose=%d delivered=%d (warehouse=%d, live_seed=%d, did_live=%s, "
            "with_contacts=%d/%d)",
            batch_size, len(candidates), wh_used, live_count, did_live,
            sum(1 for c in candidates if _candidate_has_contact(c)), len(candidates),
        )
        # Верификация «сайта нет» (website_preference=no_website): карточка
        # 2ГИС/склада без сайта ≠ компания без сайта — часто его просто не
        # заполнили (инцидент 14.07: клиент проверил выдачу руками и нашёл
        # сайты у «бездоменных»). Один платный Yandex Search-запрос на
        # кандидата: нашёлся официальный сайт → кандидат отсеивается; заодно
        # телефон/email из сниппетов достаются бесплатным бонусом.
        nosite_verify_note = ""
        if website_preference == "no_website" and candidates:
            from app.services.lead_collection import _yandex_search_configured

            if not _yandex_search_configured(get_settings()):
                # Верификация недоступна — честно, а не молча (повтор паттерна
                # инцидента: Geosearch протух беззвучно). Кандидаты идут как
                # есть — «карточка без сайта», без гарантии.
                logger.warning("no_website verify skipped: Yandex Search не настроен")
                nosite_verify_note = (
                    "Проверка «нет сайта» временно недоступна — компании "
                    "отобраны по карточкам без сайта."
                )
            else:
                verify_budget = max(0, int(getattr(get_settings(), "nosite_verify_max_per_job", 30)))
                verified: list[dict] = []
                dropped_has_site = 0
                for c in candidates:
                    if verify_budget <= 0:
                        verified.append(c)  # бюджет кончился — пропускаем без проверки
                        continue
                    verify_budget -= 1  # кэш-хиты lookup бесплатны, но бюджет консервативно тратим
                    try:
                        found = yandex_search_company_lookup(c.get("company", ""), c.get("city", ""))
                    except Exception:
                        found = {}
                    found_site = (found.get("website") or "").strip()
                    if found_site:
                        dropped_has_site += 1
                        k = company_warehouse.candidate_key(c)
                        if k:
                            chosen.add(k)
                        # ПЕРСИСТЕНЦИЯ вердикта (блокер ревью 14.07): пишем
                        # найденный сайт в строку склада — SQL-фильтр
                        # no_website исключит её из ВСЕХ будущих доз, иначе
                        # топ-ранжированные отбраковки возвращались бы в дозу
                        # каждый сбор и вечно жгли платные lookup'ы.
                        try:
                            with db.begin_nested():
                                wh_row = company_warehouse.find_company_for_lead(
                                    db, domain="", company=c.get("company") or "",
                                    city=c.get("city") or "",
                                )
                                if wh_row is not None and not (wh_row.domain or "").strip():
                                    nd = extract_domain(found_site)
                                    if nd and "." in nd:
                                        wh_row.domain = nd
                                        if not (wh_row.website or "").strip() or (wh_row.website or "").startswith("maps://"):
                                            wh_row.website = _clip(found_site, 300)
                                        db.flush()
                        except Exception:
                            logger.debug("no_website verify write-back failed", exc_info=True)
                        continue
                    if found.get("phone") and not (c.get("phone") or "").strip():
                        c["phone"] = found["phone"]
                    if found.get("email") and not (c.get("email") or "").strip():
                        c["email"] = found["email"]
                    verified.append(c)
                if dropped_has_site:
                    logger.info(
                        "no_website verify: dropped %d/%d candidate(s) that DO have a site",
                        dropped_has_site, len(candidates),
                    )
                    # Прозрачность: доза уменьшилась не «просто так» — юзер
                    # видит, что проверка сайтов реально работает.
                    nosite_verify_note = (
                        f"Проверка сайтов: {dropped_has_site} комп. отсеяно — "
                        "у них уже есть сайт."
                    )
                candidates = verified

        job.found_count = len(candidates)
        # Heartbeat after the (potentially slow) search + filter phase so the
        # 30-min reaper sees progress before the first save-loop commit.
        job.updated_at = datetime.now(timezone.utc)
        db.commit()

        added = 0
        charged = 0  # usage already booked to the org in per-chunk commits
        new_lead_ids: list[str] = []  # passed to the auto-enrich task below
        # When the dose was clamped to 0 by the remaining quota, report the
        # quota stop honestly instead of «новых компаний не найдено».
        quota_stopped = org_remaining_quota <= 0
        for c in candidates:
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
            # Prefer domain derived from the website; fall back to the candidate's
            # own domain field (warehouse hits and some maps results carry it).
            domain = (extract_domain(website) if website else "") or (c.get("domain") or "").strip().lower()
            base_domain = get_base_domain(domain) if domain else ""
            company_name = c.get("company", "").strip()
            city_name = c.get("city", "").strip()
            source = c.get("source", "")

            # For maps leads without website — generate stable placeholder URL so unique constraint works.
            # Prefer a 2GIS firm_id (incl. warehouse-reused 2GIS rows that carry it)
            # so enrichment can hit the firm page directly instead of name-searching.
            if not website and company_name:
                firm_id = (c.get("firm_id") or "").strip()
                if firm_id and source in {"2gis", "warehouse"}:
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
            # 2GIS/Yandex and our own warehouse can yield a real B2B lead with no
            # domain (address/phone only) — keep those; a bare web URL that never
            # resolved to a domain is dropped.
            is_maps = source in _NO_DOMAIN_OK_SOURCES
            if not domain and not is_maps:
                continue
            # Maps lead without website needs at least address or phone to be
            # useful — UNLESS it carries a rusprofile id: those are verified
            # legal entities and the enrichment 2GIS-by-name fallback can fill
            # contacts later. (Keep in sync with _candidate_saveable above.)
            phone_val = (c.get("phone") or "").strip()
            address_val = (c.get("address") or "").strip()
            email_val = (c.get("email") or "").strip()
            if not domain and not phone_val and not address_val and not _has_rusprofile_id(c):
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
                # Pass effective_segments so target-buyer matches earn the
                # +8/+16 segment bonus. Previously omitted, which silently
                # cost real B2B buyers ~10 points relative to seller noise.
                segments=effective_segments,
            )
            # Extract a stable external id we can link back to (2GIS firm_id,
            # rusprofile entity id, etc.). Preference order: explicit firm_id
            # → rusprofile_id → (empty). Keep short.
            ext_id = (
                str(c.get("firm_id") or "").strip()
                or str(c.get("rusprofile_id") or "").strip()
            )[:80]
            # Bug #3 fix: store the relevance_score in notes so enrich can recover
            # it when re-scoring (the Lead model has no dedicated column for it).
            # Format: "relevance=NN; " prefix so it can be parsed back reliably.
            raw_relevance = int(c.get("relevance_score", 0))
            notes_prefix = f"relevance={raw_relevance}; " if raw_relevance else ""
            notes_prefix += "demo=true; " if c.get("demo") else ""
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
                source=_clip(str(c.get("source") or ""), 24),
                external_id=ext_id,
                # «О компании»: реальный текст описания кандидата (2ГИС/веб/склад);
                # сниппет НЕ дублируем — он и так уходит в notes ниже.
                description=_clip(str(c.get("description") or ""), 2000),
                score=base_score,
                notes=notes_prefix + c.get("snippet", ""),
                demo=bool(c.get("demo", False)),
            )
            db.add(lead)
            # Bug #1 fix: use a SAVEPOINT for each lead so an IntegrityError
            # (duplicate key) only rolls back *this one lead*, not all leads
            # flushed since the last commit.  Without this, db.rollback() on a
            # dupe undoes up to 9 already-flushed leads while 'added' was already
            # incremented for them — causing lost leads and inflated quota usage.
            try:
                with db.begin_nested():  # issues SAVEPOINT / RELEASE SAVEPOINT
                    db.flush()
            except IntegrityError:
                # Only the savepoint is rolled back; previously flushed leads
                # in this transaction are still intact.  Do NOT increment 'added'.
                continue
            added += 1
            new_lead_ids.append(str(lead.id))
            if added % 10 == 0:
                # Quota integrity: book the usage for THIS chunk inside the same
                # transaction as the chunk's leads, so a worker death mid-run
                # can't hand out free leads / leave the counter behind. The org
                # row is already locked by _check_quota_with_lock at the start
                # of the chunk (same transaction), so this re-select is instant
                # and the FOR UPDATE is never held across chunk boundaries.
                org_locked = db.execute(
                    select(Organization)
                    .where(Organization.id == job.organization_id)
                    .with_for_update()
                ).scalar_one_or_none()
                if org_locked:
                    org_locked.leads_used_current_month += added - charged
                charged = added
                job.added_count = added
                job.updated_at = datetime.now(timezone.utc)
                db.commit()
        # Respect the reaper: health_check flips jobs with no heartbeat for
        # >30 min to 'failed'. Re-read the row (the in-session attribute still
        # holds the cached 'running' value!) and never overwrite failed → done.
        db.refresh(job)
        reaped = job.status == JobStatus.failed
        job.added_count = added
        # SELECT FOR UPDATE to prevent race when two collect jobs finish at the
        # same time and both read+write leads_used_current_month concurrently
        # (lost-update would let them collectively bypass the monthly cap).
        # Charge only the tail not yet booked by the per-chunk commits above.
        organization = db.execute(
            select(Organization)
            .where(Organization.id == job.organization_id)
            .with_for_update()
        ).scalar_one_or_none()
        if organization:
            organization.leads_used_current_month += added - charged
        # Exhaustion cooldown: only when the live search ACTUALLY RETURNED rows and
        # still nothing new was added is the niche+geo truly tapped out. A live
        # run that returned zero rows is indistinguishable from an outage
        # (search_leads swallows source errors and returns []) — never stamp
        # the cooldown for it, or a temporary outage masquerades as «всё
        # собрано» for cooldown_h hours. Any successful add clears the flag.
        if live_count > 0 and added == 0 and not quota_stopped:
            project.leads_exhausted_at = datetime.now(timezone.utc)
        elif added > 0:
            project.leads_exhausted_at = None
        if not reaped:
            job.status = JobStatus.done
            if quota_stopped:
                job.error = "Остановлено: месячная квота лидов исчерпана"
            elif did_live and live_count == 0 and added == 0:
                # Sources down (or returned nothing) — honest, distinct message
                # instead of the misleading «всё уже собрано». Name the known
                # culprits cheaply via the breaker flags (same pattern as the
                # enrich-task reporting below).
                issues: list[str] = []
                try:
                    from app.services import lead_collection as _lc
                    if getattr(_lc, "_TWOGIS_DEAD_KEY", False):
                        issues.append("2GIS API (ошибка ключа)")
                    if getattr(_lc, "_YANDEX_DEAD_KEY", False):
                        issues.append("Yandex Maps API (ошибка ключа)")
                    if getattr(_lc, "_TWOGIS_SCRAPE_BLOCKED", False):
                        issues.append("2GIS веб-поиск (защита от ботов)")
                except Exception:
                    pass
                job.error = "Источники временно недоступны — попробуйте позже" + (
                    f" ({', '.join(issues)})" if issues else "."
                )
            elif added == 0:
                job.error = (
                    "Новых компаний не найдено: всё доступное по этому запросу уже собрано. "
                    "Измените нишу/гео/сегменты или включите автосбор для новых со временем."
                )
            if nosite_verify_note and not job.error:
                job.error = nosite_verify_note
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
        if added > 0 and not quota_stopped and not reaped:
            try:
                # Bug #4 fix: check org-level concurrency before auto-queuing so
                # auto-enrich doesn't bypass the same MAX_CONCURRENT_JOBS_PER_ORG
                # cap enforced by the API.  If the org is already at the limit the
                # user can trigger enrich manually once a running job finishes.
                active_jobs = db.scalar(
                    select(func.count(CollectionJob.id)).where(
                        CollectionJob.organization_id == job.organization_id,
                        CollectionJob.status.in_([JobStatus.queued, JobStatus.running]),
                    )
                ) or 0
                if active_jobs >= _MAX_CONCURRENT_JOBS_PER_ORG:
                    logger.info(
                        "Auto-enrich skipped: org=%s already at concurrent job limit (%d/%d). "
                        "User can trigger enrich manually.",
                        job.organization_id, active_jobs, _MAX_CONCURRENT_JOBS_PER_ORG,
                    )
                else:
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
                        # Pass the EXACT ids collected this run so auto-enrich
                        # works on the fresh leads instead of whatever the
                        # unordered project-wide select happens to return.
                        enrich_leads_task.delay(str(enrich_job.id), new_lead_ids)
                        logger.info("Auto-enrich queued after collect: project=%s enrich_job=%s",
                                    job.project_id, enrich_job.id)
            except Exception:
                logger.warning("Failed to auto-queue enrich after collect", exc_info=True)
    except SoftTimeLimitExceeded:
        # Task hit its soft time limit (collect = 1800s / 30 min). Mark the job
        # failed so it doesn't stay 'running' forever and block subsequent API
        # calls with a 409. We do NOT raise so Celery won't attempt a retry —
        # the job simply timed out and the user should re-trigger manually.
        logger.warning("collect_leads_task soft time limit exceeded for job_id=%s", job_id)
        db.rollback()
        job = db.get(CollectionJob, UUID(job_id))
        if job:
            job.status = JobStatus.failed
            job.error = "Задача прервана: превышен лимит времени выполнения (30 мин)"
            db.commit()
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
        # acks_late guard: a redelivered task (worker lost mid-run) must not
        # revive a job health_check already failed, nor re-run a finished one.
        if job.status in (JobStatus.failed, JobStatus.done):
            logger.info("enrich_leads_task: job %s already %s — skip redelivery", job_id, job.status)
            return
        job.status = JobStatus.running
        # Heartbeat for the 30-min reaper (see collect_leads_task).
        job.updated_at = datetime.now(timezone.utc)
        db.commit()

        # Bug #5 fix: when specific lead_ids are requested, track which leads
        # were skipped (already enriched + have contacts) so the caller can see
        # why enriched_count is lower than the number of requested IDs.
        skipped_already_enriched: list[str] = []

        # Enrichable = never enriched, OR still missing an actionable contact
        # (no email AND no phone). Address is intentionally NOT part of this
        # check — a lead with only an address still needs a phone/email.
        query = select(Lead).where(
            Lead.project_id == job.project_id,
            or_(
                Lead.enriched.is_(False),
                (Lead.email == "") & (Lead.phone == ""),
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
                # Bug #5 fix: find the leads that WILL be skipped (already
                # enriched with contacts) so we can report them in job.error.
                all_requested = db.execute(
                    select(Lead).where(Lead.id.in_(safe_ids))
                ).scalars().all()
                enrichable_ids = {
                    lead.id for lead in all_requested
                    if not lead.enriched or not (lead.email or lead.phone)
                }
                for lead in all_requested:
                    if lead.id not in enrichable_ids:
                        skipped_already_enriched.append(str(lead.id))
        # Never-enriched newest leads first. Without an order_by the select
        # returned arbitrary rows while limit == the dose size, so permanently
        # contactless leads (email='' AND phone='', re-eligible forever) could
        # monopolize every run and freshly collected leads never got enriched.
        # TODO: an attempts-cap column would let us stop re-scraping leads that
        # repeatedly yield no contacts, but that needs a migration — for now
        # they merely sort behind never-enriched ones.
        query = query.order_by(Lead.enriched.asc(), Lead.created_at.desc())
        query = query.limit(job.requested_limit)
        leads = db.execute(query).scalars().all()
        project = db.get(Project, job.project_id)
        project_niche = project.niche if project else ""
        # Re-use the project's segments during enrichment scoring so the
        # buyer-match bonus stays consistent with the initial collect-pass.
        project_segments = list(project.segments) if (project and project.segments) else []
        enriched = 0
        contacts_found = 0  # leads that ended this run with an email or phone
        # Бюджет веб-фолбэка (Yandex Search, платный ₽/запрос): последний
        # шанс добыть контакты, когда карточные источники легли разом
        # (инцидент 14.07: 2GIS-тариф без contact_groups + Geosearch 403 +
        # скрейп под капчей → у клиента 20/20 лидов без телефона).
        web_lookup_budget = max(0, int(getattr(get_settings(), "enrich_web_lookup_max_per_job", 20)))
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
                # Fallback: if website scraping found NO phone AND NO email
                # (site is JS-rendered, or has no public contacts, or blocked us),
                # try to find this company's card on 2gis.ru by name and
                # scrape phones/emails from there. This closes ~30-50% of
                # "unenriched" leads — most real RU businesses have a 2GIS
                # listing even if their own site is weak.
                if (not contacts.get("phones") and not contacts.get("emails")
                        and lead.company and len(lead.company) >= 3):
                    try:
                        extra = enrich_2gis_lead(lead.company, lead.city or "")
                        merged_phones = contacts.get("phones") or []
                        merged_emails = contacts.get("emails") or []
                        merged_addresses = contacts.get("addresses") or []
                        for p in extra.get("phones", []):
                            if p not in merged_phones:
                                merged_phones.append(p)
                        for e in extra.get("emails", []):
                            if e not in merged_emails:
                                merged_emails.append(e)
                        for a in extra.get("addresses", []):
                            if a not in merged_addresses:
                                merged_addresses.append(a)
                        contacts["phones"] = merged_phones[:5]
                        contacts["emails"] = merged_emails[:5]
                        contacts["addresses"] = merged_addresses[:3]
                        if extra.get("phones") or extra.get("emails"):
                            logger.info(
                                "enrichment: 2GIS-fallback found %d phones / %d emails for %s",
                                len(extra.get("phones", [])),
                                len(extra.get("emails", [])),
                                lead.company,
                            )
                    except Exception:
                        logger.debug("2GIS fallback failed for %s", lead.company, exc_info=True)
            # Последний фолбэк: Yandex Search по названию — телефон/email из
            # сниппетов + официальный сайт. Только когда всё остальное дало
            # ноль контактов, в пределах бюджета джобы.
            if (web_lookup_budget > 0
                    and not (contacts.get("phones") or contacts.get("emails"))
                    and not (lead.phone or lead.email)
                    and lead.company and len(lead.company) >= 3):
                web_lookup_budget -= 1
                try:
                    found = yandex_search_company_lookup(lead.company, lead.city or "")
                except Exception:
                    found = {}
                    logger.debug("web lookup failed for %s", lead.company, exc_info=True)
                if found.get("phone"):
                    contacts.setdefault("phones", []).append(found["phone"])
                if found.get("email"):
                    contacts.setdefault("emails", []).append(found["email"])
                found_site = (found.get("website") or "").strip()
                if found_site and website.startswith("maps://"):
                    # Нашли официальный сайт maps-лида: дожимаем контакты со
                    # страниц сайта и записываем его В ЛИД — но только если
                    # домен не занят другим лидом проекта (uq_project_website)
                    # и проекту не нужны «клиенты без сайта».
                    try:
                        site_contacts = enrich_website_contacts(found_site)
                        for ph in site_contacts.get("phones", []):
                            if ph not in (contacts.get("phones") or []):
                                contacts.setdefault("phones", []).append(ph)
                        for em in site_contacts.get("emails", []):
                            if em not in (contacts.get("emails") or []):
                                contacts.setdefault("emails", []).append(em)
                        if site_contacts.get("site_description") and not contacts.get("site_description"):
                            contacts["site_description"] = site_contacts["site_description"]
                    except Exception:
                        logger.debug("site contacts after web lookup failed", exc_info=True)
                    wp = getattr(project, "website_preference", "any") if project else "any"
                    new_domain = extract_domain(found_site)
                    if wp == "no_website":
                        # Проект «клиенты без сайта», а сайт у лида нашёлся:
                        # website НЕ пишем, но честно помечаем тегом — юзер
                        # сам решит, звонить ли (ревью 14.07).
                        tags = list(lead.tags or [])
                        if "есть сайт" not in tags:
                            lead.tags = tags + ["есть сайт"]
                    elif new_domain:
                        # SAVEPOINT: конкурентный enrich мог занять домен между
                        # check и set — конфликт uq_project_website не должен
                        # ронять весь джоб (ревью 14.07). base-домен в проверке
                        # зеркалит дедуп save-loop'а.
                        try:
                            with db.begin_nested():
                                taken = db.execute(
                                    select(Lead.id).where(
                                        Lead.project_id == lead.project_id,
                                        (Lead.website == found_site)
                                        | (Lead.domain == new_domain)
                                        | (Lead.domain == get_base_domain(new_domain)),
                                        Lead.id != lead.id,
                                    )
                                ).first()
                                if taken is None:
                                    lead.website = _clip(found_site, 300)
                                    lead.domain = new_domain
                                    db.flush()
                        except Exception:
                            logger.debug("website write after lookup failed", exc_info=True)
                if found:
                    logger.info(
                        "enrichment: web lookup for %r → phone=%s email=%s site=%s (budget left %d)",
                        lead.company[:40], bool(found.get("phone")),
                        bool(found.get("email")), bool(found_site), web_lookup_budget,
                    )
            lead.contacts = contacts
            lead.contacts_json = contacts
            # «О компании»: meta-description главной — лучший короткий ответ,
            # чем занимается компания. Перезаписываем только пустое/куцое
            # описание (сниппеты со сбора бывают обрубками). Write-back в склад
            # — ниже, единым блоком вместе с контактами.
            site_desc = (contacts.get("site_description") or "").strip() if isinstance(contacts, dict) else ""
            if site_desc and len(site_desc) > len(lead.description or ""):
                lead.description = _clip(site_desc, 2000)
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
            if lead.email or lead.phone:
                contacts_found += 1

            # ── Write-back в склад: добытые обогащением контакты и описание ──
            # накапливаются в общем активе companies (семантика fill-empty).
            # Аудит 09.07: companies.email был 0 у всех 1661 строк при 456
            # добытых email в лидах — актив не копился, каждый новый проект
            # заново скрейпил те же сайты, а warehouse-first раздавал пустышки.
            # SAVEPOINT: строку склада могли удалить конкурентно (TTL-очистка
            # Яндекс-данных, чистки), и тогда UPDATE словил бы StaleDataError
            # на ОБЩЕМ flush — падал весь enrich-проход (флаки в CI, найдено
            # ревью 13.07). Вложенная транзакция изолирует write-back: его
            # провал не трогает изменения лида.
            try:
                with db.begin_nested():
                    wh_company = company_warehouse.find_company_for_lead(
                        db, domain=lead.domain or "", company=lead.company or "", city=lead.city or ""
                    )
                    if wh_company is not None:
                        if lead.email and not (wh_company.email or "").strip():
                            wh_company.email = lead.email
                        if lead.phone and not (wh_company.phone or "").strip():
                            wh_company.phone = lead.phone
                        if lead.address and not (wh_company.address or "").strip():
                            wh_company.address = lead.address
                        if (lead.website and not lead.website.startswith("maps://")
                                and not (wh_company.website or "").strip()):
                            wh_company.website = _clip(lead.website, 300)
                        if lead.description and not (wh_company.description or "").strip():
                            wh_company.description = _clip(lead.description, 2000)
                        db.flush()  # StaleDataError ловится ЗДЕСЬ, внутри savepoint
            except Exception:
                logger.debug("warehouse write-back failed", exc_info=True)

            # Email deliverability check — syntax + MX record lookup.
            # Cheap (1 DNS query, cached) and catches ~80% of bounces.
            # Real enterprise upsell: NeverBounce-style SMTP handshake.
            if lead.email:
                try:
                    from app.utils.email_verifier import verify_email
                    status = verify_email(lead.email)
                    lead.email_status = status.value
                except Exception:
                    logger.debug("email verify failed for %s", lead.email, exc_info=True)
                    lead.email_status = ""
            else:
                lead.email_status = ""

            lead.enriched = True
            # Treat no_mx / syntax as no-email for scoring: a bouncy address
            # is worse than no address at all (it wastes sales-rep time).
            usable_email = bool(lead.email) and lead.email_status in ("valid", "skipped", "")

            # Bug #3 fix: recover the original relevance_score stored in notes
            # at collect time (format: "relevance=NN; ...").  Without this, every
            # enrich pass called score_lead with relevance_score=0, silently
            # dropping up to 15 pts for map-source leads and causing visible
            # score regressions (e.g. 70 → 55).
            stored_relevance = 0
            if lead.notes:
                _rel_match = _re.match(r"relevance=(\d+);", lead.notes)
                if _rel_match:
                    stored_relevance = int(_rel_match.group(1))

            lead.score = score_lead(
                domain=lead.domain,
                company=lead.company,
                niche=project_niche,
                has_email=usable_email,
                has_phone=bool(lead.phone),
                has_address=bool(lead.address),
                demo=lead.demo,
                relevance_score=stored_relevance,
                segments=project_segments,
            )
            enriched += 1

            # Push to CRM webhook if configured (Bitrix24 / AmoCRM / custom).
            # Fire-and-forget via Celery — doesn't block enrichment loop.
            try:
                org = db.get(Organization, lead.organization_id)
                if org and org.lead_webhook_url:
                    from app.tasks.webhook_tasks import push_lead_webhook
                    payload = {
                        "id": str(lead.id),
                        "company": lead.company,
                        "city": lead.city,
                        "email": lead.email,
                        "phone": lead.phone,
                        "address": lead.address,
                        "website": lead.website,
                        "score": lead.score,
                        "status": lead.status.value,
                        "tags": lead.tags or [],
                        "project_id": str(lead.project_id),
                        "project_name": project.name if project else "",
                    }
                    push_lead_webhook.delay(org.lead_webhook_url, payload)
            except Exception:
                logger.debug("webhook queue failed for lead=%s", lead.id, exc_info=True)
            if enriched % 5 == 0:
                job.enriched_count = enriched
                job.updated_at = datetime.now(timezone.utc)
                db.commit()
        # Respect the reaper: re-read the row (the in-session attribute still
        # holds the cached 'running' value) and never overwrite failed → done.
        db.refresh(job)
        reaped = job.status == JobStatus.failed
        job.enriched_count = enriched
        if not reaped:
            job.status = JobStatus.done
            job.updated_at = datetime.now(timezone.utc)
        # Non-fatal informational messages surfaced to the user via job.error
        # (shown in История задач + a completion toast). Same convention as the
        # quota_stopped note in collect_leads_task.
        messages: list[str] = []
        # Honest signal: we processed leads but found NO contacts AND a contact
        # source was unavailable this run — tell the user WHY instead of silently
        # reporting 0. Usual cause: expired/invalid 2GIS/Yandex API key, or 2GIS
        # bot-protection (captcha) blocking the scrape fallback.
        if leads and contacts_found == 0:
            from app.services import lead_collection as _lc
            issues = []
            if getattr(_lc, "_TWOGIS_DEAD_KEY", False):
                issues.append("2GIS API (ошибка ключа)")
            if getattr(_lc, "_YANDEX_DEAD_KEY", False):
                issues.append("Yandex Maps API (ошибка ключа)")
            if getattr(_lc, "_TWOGIS_SCRAPE_BLOCKED", False) or getattr(_lc, "_TWOGIS_SCRAPE_BLOCKED_ENRICH", False):
                issues.append("2GIS веб-поиск (защита от ботов)")
            if issues:
                # Юзеру — человеческий текст (клиент не «проверяет API-ключи
                # на сервере»); технические детали — админу алертом (инцидент
                # 14.07: клиент увидел операторское сообщение и растерялся).
                messages.append(
                    "Контакты у этой партии пока не найдены: внешние источники "
                    "временно недоступны. Мы уже знаем о проблеме; попробуйте "
                    "обогащение позже — лиды останутся в проекте."
                )
                try:
                    from app.services.notifications import send_alert
                    send_alert(
                        "error",
                        "Все источники контактов легли: обогащение дало 0",
                        f"job={job.id} leads={len(leads)} причины: {', '.join(issues)}",
                        key="enrich-sources-down",
                        throttle_seconds=3600,
                    )
                except Exception:
                    logger.debug("sources-down alert failed", exc_info=True)
        # Bug #5: record skipped (already-enriched-with-contact) leads so the
        # user sees why enriched_count may be lower than the number requested.
        if skipped_already_enriched:
            messages.append(
                f"Пропущено уже обогащённых: {len(skipped_already_enriched)} лид(ов)."
            )
        if messages and not reaped:
            job.error = " ".join(messages)
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
    except SoftTimeLimitExceeded:
        # Task hit its soft time limit (enrich = 3600s / 60 min). Mark failed so
        # the job doesn't stay 'running' and block the project with 409 errors.
        logger.warning("enrich_leads_task soft time limit exceeded for job_id=%s", job_id)
        db.rollback()
        job = db.get(CollectionJob, UUID(job_id))
        if job:
            job.status = JobStatus.failed
            job.error = "Задача прервана: превышен лимит времени выполнения (60 мин)"
            db.commit()
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
    auto_dose = int(getattr(get_settings(), "auto_collect_dose", 25))
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
            # Clamp the auto-dose to the org's remaining monthly quota: a job
            # the save loop will fully refuse only burns a worker slot and
            # spams «квота исчерпана». Skip entirely at zero remaining. (Do
            # NOT call ensure_lead_quota here — it raises HTTPException.)
            org = db.get(Organization, project.organization_id)
            remaining = (
                max(0, org.leads_limit_per_month - org.leads_used_current_month) if org else 0
            )
            if remaining <= 0:
                logger.info(
                    "auto-collect skipped: org=%s out of monthly lead quota",
                    project.organization_id,
                )
                continue
            job = CollectionJob(
                organization_id=project.organization_id,
                project_id=project.id,
                status=JobStatus.queued,
                kind="collect",
                requested_limit=min(auto_dose, remaining),
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
