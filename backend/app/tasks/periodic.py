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
