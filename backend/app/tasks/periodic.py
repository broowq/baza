import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, update

from app.db.session import SessionLocal
from app.models import CollectionJob, Invite, JobStatus, Organization
from app.services.notifications import send_alert
from app.tasks.celery_app import celery

logger = logging.getLogger(__name__)


@celery.task(name="periodic.reset_monthly_quotas")
def reset_monthly_quotas() -> None:
    """Reset leads_used_current_month to 0 for all organizations.

    Runs on the 1st of each month at 00:05 UTC via Celery beat.
    """
    db = SessionLocal()
    try:
        result = db.execute(
            update(Organization).values(leads_used_current_month=0)
        )
        db.commit()
        logger.info(
            "Monthly quota reset complete: %d organizations updated",
            result.rowcount,
        )
    except Exception:
        logger.exception("reset_monthly_quotas failed")
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

            # Clear reminder_at on successfully-notified leads (one-shot reminder)
            for lead in leads:
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

        logger.debug("Health check ok: stuck=%d, failed_last_hour=%d", stuck, recent_failed)
    except Exception:
        logger.exception("health_check task failed")
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
