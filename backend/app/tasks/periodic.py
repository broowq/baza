import logging
from datetime import datetime, timezone

from sqlalchemy import delete, update

from app.db.session import SessionLocal
from app.models import Invite, Organization
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
