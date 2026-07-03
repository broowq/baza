import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import CollectionJob, Invite, JobStatus, Organization
from app.services.notifications import send_alert
from app.tasks.celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(name="periodic.reset_monthly_quotas")
def reset_monthly_quotas() -> None:
    """Reset leads_used_current_month AND ai_cost_used_kopecks_current_month
    to 0 for all organizations.

    Runs on the 1st of each month at 00:05 UTC via Celery beat. Both counters
    are zeroed in a single statement so they stay in lockstep — frontend
    never shows "leads reset but AI quota didn't" as an inconsistent moment.
    """
    db = SessionLocal()
    try:
        result = db.execute(
            update(Organization).values(
                leads_used_current_month=0,
                ai_cost_used_kopecks_current_month=0,
                yandex_requests_used_current_month=0,
            )
        )
        db.commit()
        logger.info(
            "Monthly quota reset complete: %d organizations updated (leads + AI cost)",
            result.rowcount,
        )
    except Exception:
        logger.exception("reset_monthly_quotas failed")
        db.rollback()
    finally:
        db.close()


def _org_owner(db, org_id) -> tuple[str, str]:
    """(user_id, email) владельца организации. ('', '') если не найден."""
    from app.models import Membership, User

    membership = db.execute(
        select(Membership).where(
            Membership.organization_id == org_id, Membership.role == "owner"
        )
    ).scalars().first()
    if not membership:
        return "", ""
    user = db.get(User, membership.user_id)
    if not user:
        return "", ""
    return str(user.id), (user.email or "")


def _org_owner_email(db, org_id) -> str:
    """Email владельца организации (для биллинг-писем). '' если не найден."""
    return _org_owner(db, org_id)[1]


@celery.task(name="periodic.renew_subscriptions")
def renew_subscriptions() -> None:
    """Автопродление подписок: списание по сохранённой карте ЮKassa.

    Гоняется каждую ночь в 01:30 UTC — ЗА СУТКИ до конца оплаченного периода
    (и с ретраями до 72 ч после), чтобы к ночному downgrade (02:30) продление
    уже было активно и клиент не терял доступ даже на минуту.

    Для каждой активной подписки с auto_renew + сохранённой картой, чей период
    кончается в ближайшие 24 ч (или уже кончился < 72 ч назад, попыток < 3):
      1. пропускаем, если орг уже покрыт более свежей активной подпиской
         (клиент продлил/сменил тариф руками) или есть pending-платёж < 26 ч
         (продление уже в полёте — не задваиваем списание);
      2. создаём новую pending-подписку и merchant-initiated платёж ЮKassa по
         payment_method_id (idempotence_key = id новой подписки: повтор задачи
         не спишет дважды);
      3. ответ succeeded → активируем сразу (продлеваем период, письмо
         «подписка продлена»); canceled → счётчик попыток +1, письмо «не
         удалось списать»; pending → финал доедет вебхуком payment.succeeded.

    Отдельно: клиентам БЕЗ автопродления (нет согласия или карты) за 72 ч до
    конца периода шлём одно напоминание «подписка заканчивается».

    Каждая подписка коммитится отдельно — одна ошибка не валит весь проход.
    """
    from app.api.routes.billing import _build_receipt
    from app.api.routes.plans import PLAN_NAMES, PLAN_PRICES_RUB
    from app.models import PlanType, Subscription
    from app.services.notifications import send_email
    from app.services.quota import apply_plan_limits
    from app.services.yookassa import YooKassaClient, YooKassaError

    settings = get_settings()
    base_url = (settings.frontend_app_url or "https://usebaza.ru").rstrip("/")
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)

        # ── 1. Напоминания тем, у кого автопродление НЕ работает ────────────
        reminder_window = now + timedelta(hours=72)
        need_reminder = db.execute(
            select(Subscription).where(
                Subscription.status == "active",
                Subscription.current_period_end.is_not(None),
                Subscription.current_period_end > now,
                Subscription.current_period_end <= reminder_window,
                Subscription.expiry_reminder_sent_at.is_(None),
                # авто-продление не сработает: нет согласия ИЛИ нет карты
                ((Subscription.auto_renew.is_(False)) | (Subscription.payment_method_id == "")),
            )
        ).scalars().all()
        for sub in need_reminder:
            try:
                email = _org_owner_email(db, sub.organization_id)
                if email:
                    end = sub.current_period_end.strftime("%d.%m.%Y")
                    plan_name = PLAN_NAMES.get(sub.plan_id, sub.plan_id)
                    send_email(
                        f"БАЗА: тариф {plan_name} действует до {end}",
                        (
                            f"Ваш тариф «{plan_name}» действует до {end}.\n\n"
                            "Автопродление не подключено, поэтому после этой даты "
                            "организация перейдёт на Free и лимиты обнулятся.\n\n"
                            f"Продлить: {base_url}/plans\n\n"
                            "Совет: при оплате отметьте «Автопродление» — и тариф "
                            "будет продлеваться сам, отключить можно в любой момент."
                        ),
                        email,
                    )
                sub.expiry_reminder_sent_at = now
                db.commit()
            except Exception:
                logger.exception("renewal reminder failed for sub=%s", sub.id)
                db.rollback()

        # ── 2. Автосписания ─────────────────────────────────────────────────
        if not (settings.yookassa_shop_id and settings.yookassa_secret_key):
            logger.debug("renew_subscriptions: YooKassa не настроена — списания пропущены")
            return

        renew_window = now + timedelta(hours=24)
        grace_floor = now - timedelta(hours=72)
        due = db.execute(
            select(Subscription).where(
                Subscription.status == "active",
                Subscription.auto_renew.is_(True),
                Subscription.payment_method_id != "",
                Subscription.renew_attempts < 3,
                Subscription.current_period_end.is_not(None),
                Subscription.current_period_end <= renew_window,
                Subscription.current_period_end > grace_floor,
            )
        ).scalars().all()
        if not due:
            return

        client = YooKassaClient(settings.yookassa_shop_id, settings.yookassa_secret_key)
        renewed = failed = skipped = 0
        for sub in due:
            try:
                # (a) Уже покрыт более свежей активной подпиской (ручное
                #     продление / апгрейд) → автосписание не нужно.
                newer_active = db.execute(
                    select(func.count(Subscription.id)).where(
                        Subscription.organization_id == sub.organization_id,
                        Subscription.id != sub.id,
                        Subscription.status == "active",
                        Subscription.current_period_end > sub.current_period_end,
                    )
                ).scalar_one() or 0
                # (b) Продление уже в полёте (pending-платёж, в т.ч. наш же
                #     вчерашний, ждущий вебхука) → не задваиваем.
                inflight = db.execute(
                    select(func.count(Subscription.id)).where(
                        Subscription.organization_id == sub.organization_id,
                        Subscription.status == "pending",
                        Subscription.created_at > now - timedelta(hours=26),
                    )
                ).scalar_one() or 0
                if newer_active or inflight:
                    skipped += 1
                    continue

                amount = PLAN_PRICES_RUB.get(sub.plan_id)
                if not amount or amount <= 0:
                    logger.warning("renew: у плана %s нет цены — пропуск (sub=%s)", sub.plan_id, sub.id)
                    skipped += 1
                    continue

                org = db.get(Organization, sub.organization_id)
                if org is None:
                    skipped += 1
                    continue
                owner_id, owner_email = _org_owner(db, sub.organization_id)
                plan_name = PLAN_NAMES.get(sub.plan_id, sub.plan_id)

                new_sub = Subscription(
                    organization_id=sub.organization_id,
                    plan_id=sub.plan_id,
                    status="pending",
                    current_period_start=now,
                    current_period_end=now + timedelta(days=30),
                    auto_renew=True,
                    payment_method_id=sub.payment_method_id,
                )
                db.add(new_sub)
                db.flush()

                payment = client.create_recurring_payment(
                    amount_rub=amount,
                    description=f"БАЗА · {plan_name} · автопродление · {org.name}"[:128],
                    payment_method_id=sub.payment_method_id,
                    metadata={
                        "organization_id": str(sub.organization_id),
                        "plan_id": sub.plan_id,
                        "subscription_id": str(new_sub.id),
                        # user_id ОБЯЗАТЕЛЕН: вебхук пишет его в ActionLog (UUID).
                        "user_id": owner_id,
                        "renewal_of": str(sub.id),
                    },
                    receipt=_build_receipt(
                        user_email=owner_email, plan_id=sub.plan_id, amount_rub=amount
                    ),
                    idempotence_key=str(new_sub.id),
                )

                status = payment.get("status")
                new_sub.provider_subscription_id = payment.get("id") or ""
                if status == "succeeded":
                    new_sub.status = "active"
                    pm = payment.get("payment_method") or {}
                    if pm.get("saved") and pm.get("id"):
                        new_sub.payment_method_id = pm["id"]
                    org.plan = PlanType(sub.plan_id)
                    apply_plan_limits(org)
                    renewed += 1
                    if owner_email:
                        send_email(
                            f"БАЗА: тариф {plan_name} продлён",
                            (
                                f"Подписка «{plan_name}» продлена ещё на 30 дней, "
                                f"списано {amount} ₽.\n\n"
                                f"Отключить автопродление: {base_url}/dashboard/settings"
                            ),
                            owner_email,
                        )
                elif status == "canceled":
                    new_sub.status = "canceled"
                    sub.renew_attempts = (sub.renew_attempts or 0) + 1
                    failed += 1
                    reason = ((payment.get("cancellation_details") or {}).get("reason")) or "отклонено"
                    logger.warning(
                        "renew: списание отклонено (org=%s sub=%s attempt=%d reason=%s)",
                        sub.organization_id, sub.id, sub.renew_attempts, reason,
                    )
                    if owner_email:
                        send_email(
                            "БАЗА: не удалось продлить тариф",
                            (
                                f"Не получилось списать {amount} ₽ за продление "
                                f"тарифа «{plan_name}» (банк отклонил платёж).\n\n"
                                f"Мы попробуем ещё раз завтра (попытка "
                                f"{sub.renew_attempts} из 3). Чтобы не потерять "
                                f"доступ, оплатите вручную: {base_url}/plans"
                            ),
                            owner_email,
                        )
                # status == "pending": оставляем pending-подписку — финал
                # придёт вебхуком payment.succeeded/canceled.
                db.commit()
            except YooKassaError as e:
                db.rollback()
                # Помечаем неудачную попытку в НОВОЙ транзакции (rollback снёс new_sub).
                try:
                    sub.renew_attempts = (sub.renew_attempts or 0) + 1
                    db.commit()
                except Exception:
                    db.rollback()
                failed += 1
                logger.error("renew: YooKassa error (sub=%s): %s", sub.id, e)
            except Exception:
                db.rollback()
                logger.exception("renew: unexpected failure (sub=%s)", sub.id)

        logger.info(
            "renew_subscriptions: %d продлено, %d отказов, %d пропущено (из %d кандидатов)",
            renewed, failed, skipped, len(due),
        )
    except Exception:
        logger.exception("renew_subscriptions failed")
        db.rollback()
    finally:
        db.close()


@celery.task(name="periodic.downgrade_expired_subscriptions")
def downgrade_expired_subscriptions() -> None:
    """Downgrade orgs whose paid subscription period has lapsed.

    Without this, an org that paid once (or was bumped to a paid plan) keeps the
    elevated plan + quotas FOREVER — nothing reverted entitlements after
    Subscription.current_period_end. Runs nightly via Celery beat.

    Idempotent: each lapsed subscription flips active → expired once. The org is
    downgraded to free only if NO other still-valid active subscription covers
    it (so renewals/upgrades, which create a fresh subscription row, are safe).
    """
    from app.models import Subscription, PlanType
    from app.services.quota import reconcile_org_plan

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        lapsed = db.execute(
            select(Subscription).where(
                Subscription.status == "active",
                Subscription.current_period_end.is_not(None),
                Subscription.current_period_end < now,
            )
        ).scalars().all()
        changed = 0
        for sub in lapsed:
            try:
                sub.status = "expired"
                org = db.get(Organization, sub.organization_id)
                downgraded_to = None
                if org and org.plan != PlanType.free:
                    before = org.plan
                    # Reconcile to whatever the org STILL actively pays for
                    # (free if nothing), excluding this just-lapsed row.
                    after = reconcile_org_plan(db, org, now=now, exclude_sub_id=sub.id)
                    if after != before:
                        changed += 1
                        downgraded_to = after
                        logger.info(
                            "Subscription lapsed: org=%s %s → %s (sub=%s, period_end=%s)",
                            org.id, before.value, after.value, sub.id, sub.current_period_end,
                        )
                # Commit per row so one bad row can't roll back the whole sweep.
                db.commit()
                # Письмо о даунгрейде — ПОСЛЕ коммита (сбой почты не должен
                # откатывать сам даунгрейд). Best-effort.
                if downgraded_to is not None:
                    try:
                        from app.services.notifications import send_email

                        email = _org_owner_email(db, sub.organization_id)
                        if email:
                            base_url = (get_settings().frontend_app_url or "https://usebaza.ru").rstrip("/")
                            send_email(
                                "БАЗА: подписка закончилась — тариф изменён",
                                (
                                    "Оплаченный период вашей подписки закончился, "
                                    f"организация переведена на тариф «{downgraded_to.value}».\n\n"
                                    f"Вернуть тариф: {base_url}/plans"
                                ),
                                email,
                            )
                    except Exception:
                        logger.warning("downgrade email failed for org=%s", sub.organization_id, exc_info=True)
            except Exception:
                logger.exception("downgrade_expired_subscriptions: failed on sub=%s", sub.id)
                db.rollback()
        # Observability: active subs with NULL period_end are invisible to the
        # lapse query above — surface them so a plan can't silently persist.
        orphan_null = db.scalar(
            select(func.count(Subscription.id)).where(
                Subscription.status == "active",
                Subscription.current_period_end.is_(None),
            )
        ) or 0
        if orphan_null:
            logger.warning(
                "downgrade_expired_subscriptions: %d active subs have NULL period_end "
                "(invisible to expiry sweep — investigate)", orphan_null,
            )
        if lapsed:
            logger.info(
                "downgrade_expired_subscriptions: %d lapsed, %d orgs reconciled",
                len(lapsed), changed,
            )
    except Exception:
        logger.exception("downgrade_expired_subscriptions failed")
        db.rollback()
    finally:
        db.close()


@celery.task(name="periodic.send_reminder_emails")
def send_reminder_emails() -> None:
    """Send daily digest of leads with reminder_at <= now per project owner.

    Runs every hour. Each lead is reminded once (we set reminder_at to None
    after sending). Owner of org gets one digest email listing all due leads.
    """
    from collections import defaultdict
    from app.models import Lead, Membership, Project, User
    from app.services.notifications import send_email

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        from sqlalchemy import select as _select
        due_leads = db.execute(
            _select(Lead)
            .where(Lead.reminder_at.is_not(None))
            .where(Lead.reminder_at <= now)
            .limit(500)
        ).scalars().all()
        if not due_leads:
            return

        # Group by org
        by_org: dict = defaultdict(list)
        for lead in due_leads:
            by_org[lead.organization_id].append(lead)

        for org_id, leads in by_org.items():
            # Find owner email
            membership = db.execute(
                _select(Membership).where(Membership.organization_id == org_id).where(Membership.role == "owner")
            ).scalar_one_or_none()
            if not membership:
                continue
            user = db.get(User, membership.user_id)
            if not user or not user.email:
                continue

            # Build digest body
            lines = [f"У вас {len(leads)} лидов с напоминанием на сегодня:\n"]
            project_cache: dict = {}
            for lead in leads[:50]:  # cap email size
                project = project_cache.get(lead.project_id)
                if project is None:
                    project = db.get(Project, lead.project_id)
                    project_cache[lead.project_id] = project
                proj_name = project.name if project else "—"
                last = lead.last_contacted_at.strftime("%d.%m.%Y") if lead.last_contacted_at else "никогда"
                lines.append(f"  • {lead.company} ({proj_name}) — последний контакт: {last}")
                if lead.notes:
                    lines.append(f"    Заметка: {lead.notes[:100]}")
            if len(leads) > 50:
                lines.append(f"\n  …и ещё {len(leads) - 50}")

            try:
                send_email(
                    f"БАЗА: {len(leads)} напоминаний",
                    "\n".join(lines),
                    user.email,
                )
            except Exception:
                logger.warning("reminder digest send failed for user %s", user.email, exc_info=True)
                continue

            # Clear reminder_at only on the leads we actually included in the
            # digest (email is capped at 50). Leads 51+ keep their reminder so
            # they resurface in tomorrow's digest instead of being silently lost.
            for lead in leads[:50]:
                lead.reminder_at = None
            db.commit()

        logger.info("Sent reminder digests to %d orgs", len(by_org))
    except Exception:
        logger.exception("send_reminder_emails task failed")
        db.rollback()
    finally:
        db.close()


@celery.task(name="periodic.health_check")
def health_check() -> None:
    """Periodic monitoring — alert on stuck/failed jobs.

    Runs every 15 min via beat. Throttled alerts via send_alert.
    """
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        # 1. Stuck jobs: status=running for > 30 min (likely killed worker)
        stuck_threshold = now - timedelta(minutes=30)
        stuck = db.execute(
            select(func.count(CollectionJob.id))
            .where(CollectionJob.status == JobStatus.running)
            .where(CollectionJob.updated_at < stuck_threshold)
        ).scalar_one() or 0
        if stuck >= 3:
            send_alert(
                "warning",
                f"{stuck} jobs stuck in 'running' state",
                "Likely killed worker / abandoned tasks. Check celery worker health.",
                key="stuck_jobs",
                throttle_seconds=1800,
            )

        # 2. Recent failed-job spike: > 5 failed jobs in last hour
        hour_ago = now - timedelta(hours=1)
        recent_failed = db.execute(
            select(func.count(CollectionJob.id))
            .where(CollectionJob.status == JobStatus.failed)
            .where(CollectionJob.updated_at >= hour_ago)
        ).scalar_one() or 0
        if recent_failed >= 5:
            send_alert(
                "error",
                f"{recent_failed} jobs failed in last hour",
                "Check worker logs for upstream API breakage (2GIS, captcha, etc.).",
                key="failed_jobs_spike",
                throttle_seconds=1800,
            )

        # 3. Auto-remediate: flip stuck 'running' jobs (no progress for >30 min)
        #    to 'failed' so the project is unblocked. A killed/OOM/evicted worker
        #    never runs its except-handler, so the row would otherwise sit in
        #    'running' forever and 409 every future collect/enrich. Both tasks
        #    bump updated_at on progress (collect every 10 leads, enrich every
        #    5), so updated_at < now-30min means genuinely no progress — a live
        #    long job stays fresh and is never wrongly failed. Placed AFTER the
        #    detection counts above so it doesn't inflate this run's failed-spike
        #    alert.
        remediated = db.execute(
            update(CollectionJob)
            .where(CollectionJob.status == JobStatus.running)
            .where(CollectionJob.updated_at < stuck_threshold)
            .values(
                status=JobStatus.failed,
                error="Задача прервана: воркер остановлен (таймаут/OOM)",
                updated_at=now,
            )
        ).rowcount
        if remediated:
            db.commit()
            logger.warning("health_check: auto-failed %d stuck job(s)", remediated)

        logger.debug("Health check ok: stuck=%d, failed_last_hour=%d", stuck, recent_failed)
    except Exception:
        logger.exception("health_check task failed")
        db.rollback()
    finally:
        db.close()


@celery.task(name="periodic.cleanup_expired_invites")
def cleanup_expired_invites() -> None:
    """Delete invites where expires_at < now().

    Runs daily at 03:00 UTC via Celery beat.
    """
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        result = db.execute(
            delete(Invite).where(Invite.expires_at < now)
        )
        db.commit()
        logger.info(
            "Expired invite cleanup complete: %d invites deleted",
            result.rowcount,
        )
    except Exception:
        logger.exception("cleanup_expired_invites failed")
        db.rollback()
    finally:
        db.close()


@celery.task(name="periodic.purge_yandex_warehouse_ttl")
def purge_yandex_warehouse_ttl() -> None:
    """Yandex Geosearch ToS: результаты работы API нельзя хранить > 30 дней
    (обычный тариф — см. docs/unit-economics.md, п.3).

    Склад `companies` кэширует ПУБЛИЧНЫЕ контактные поля с провенансом в
    `sources`. `raw_json` не хранится (всегда {}), поэтому «сырьё» здесь — сам
    факт Яндекс-происхождения строки. `last_seen_at` обновляется при КАЖДОМ
    повторном сборе, так что актуальные компании не истекают — только строки,
    которых не видели `settings.yandex_raw_ttl_days` дней.

    Доставленные клиенту лиды живут в таблице `leads` (это уже его данные) и
    здесь НЕ трогаются — чистится только кэш-склад.

    Для просроченных Яндекс-строк:
      • Яндекс — единственный источник → удаляем строку целиком (все её данные
        из Яндекса).
      • есть и другие источники (2ГИС и т.п.) → снимаем метку 'yandex_maps' из
        `sources` (данные 2ГИС ограничения 30 дней не имеют), строку оставляем
        ради дедупа.

    Идемпотентно (после зачистки строка больше не матчит фильтр), гоняется
    ежедневно в 04:30 UTC из Celery beat. Всё делается bulk-SQL, без вычитки
    строк в Python — безопасно по памяти на большом складе.
    """
    from app.models import Company

    ttl_days = int(getattr(get_settings(), "yandex_raw_ttl_days", 30) or 30)
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
        # Общий фильтр: строка с Яндекс-происхождением, не виденная > TTL дней.
        stale_yandex = (
            Company.last_seen_at < cutoff,
            Company.sources.contains(["yandex_maps"]),
        )
        # 1) Яндекс — единственный источник → удалить.
        deleted = db.execute(
            delete(Company).where(
                *stale_yandex,
                func.jsonb_array_length(Company.sources) == 1,
            )
        ).rowcount
        # 2) Мульти-источник → снять только Яндекс-метку (jsonb `-` удаляет
        #    все элементы массива, равные тексту), строку сохранить.
        stripped = db.execute(
            update(Company)
            .where(*stale_yandex, func.jsonb_array_length(Company.sources) > 1)
            .values(sources=Company.sources.op("-")("yandex_maps"))
        ).rowcount
        db.commit()
        if deleted or stripped:
            logger.info(
                "yandex warehouse TTL sweep (>%dd): %d rows deleted (yandex-only), "
                "%d rows stripped of yandex provenance",
                ttl_days, deleted, stripped,
            )
    except Exception:
        logger.exception("purge_yandex_warehouse_ttl failed")
        db.rollback()
    finally:
        db.close()


@celery.task(name="periodic.purge_old_leads")
def purge_old_leads() -> None:
    """152-ФЗ ст. 5 ч. 7 — обработка прекращается по достижении цели/срока.

    Удаляет лиды, у которых:
      • не было updated_at-изменений в течение Organization.leads_retention_days
      • либо явно `marked_for_deletion=True` (после отзыва согласия —
        отдельно реализуем когда появится UI)

    Задача идемпотентная — гоняется ежедневно в 04:00 UTC из Celery beat.
    Если org.leads_retention_days == 0, лиды этой организации не трогаются
    (внутренние/тестовые аккаунты).
    """
    from app.models import Lead, Organization
    from sqlalchemy import select as _select

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        orgs = db.execute(_select(Organization)).scalars().all()
        total_deleted = 0
        for org in orgs:
            retention = int(getattr(org, "leads_retention_days", 0) or 0)
            if retention <= 0:
                continue
            cutoff = now - timedelta(days=retention)
            # SQL DELETE напрямую, без вычитки в Python — на больших таблицах
            # сэкономит memory и обойдёт ORM-cascade-tracking.
            result = db.execute(
                delete(Lead)
                .where(Lead.organization_id == org.id)
                .where(Lead.updated_at < cutoff)
            )
            if result.rowcount:
                logger.info(
                    "purge_old_leads: org=%s deleted %d leads "
                    "(retention=%d days, cutoff=%s)",
                    org.id, result.rowcount, retention, cutoff.date(),
                )
                total_deleted += result.rowcount
        db.commit()
        if total_deleted:
            logger.info(
                "Retention sweep complete: %d leads purged across %d orgs",
                total_deleted, len(orgs),
            )
    except Exception:
        logger.exception("purge_old_leads failed")
        db.rollback()
    finally:
        db.close()
