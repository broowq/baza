from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery = Celery(
    "lead-service",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # --- Backpressure / stability settings ---
    worker_max_tasks_per_child=100,
    worker_prefetch_multiplier=1,
    # --- Task rate limits ---
    task_routes={
        "jobs.collect_leads": {"rate_limit": "6/m"},
        "jobs.enrich_leads": {"rate_limit": "10/m"},
    },
    beat_schedule={
        "auto-collect-scan": {
            "task": "jobs.schedule_auto_collection",
            "schedule": 60.0,
        },
        "reset-monthly-quotas": {
            "task": "periodic.reset_monthly_quotas",
            "schedule": crontab(minute=5, hour=0, day_of_month=1),
        },
        "cleanup-expired-invites": {
            "task": "periodic.cleanup_expired_invites",
            "schedule": crontab(minute=0, hour=3),
        },
        "health-check": {
            "task": "periodic.health_check",
            "schedule": crontab(minute="*/15"),  # every 15 min
        },
        "send-reminder-emails": {
            "task": "periodic.send_reminder_emails",
            "schedule": crontab(minute=0, hour="9-18"),  # hourly, business hours UTC
        },
    },
)
