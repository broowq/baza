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
    # --- Task timeouts (Bug #2 fix) ---
    # Without a hard limit, OOM-killed workers leave jobs stuck in 'running'
    # forever and block the project with a 409. 1800s hard / 1500s soft gives
    # ~25 min for large enrichments while ensuring the job always transitions
    # to 'failed' cleanly. SoftTimeLimitExceeded is caught inside each task
    # so the job status is updated before the worker shuts down.
    task_time_limit=1800,        # hard kill after 30 min
    task_soft_time_limit=1500,   # SIGXCPU at 25 min → tasks can clean up
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
        # 152-ФЗ ст. 5 ч. 7: ежедневно подчищать лиды старше
        # Organization.leads_retention_days. Сразу после cleanup invites
        # чтобы оба задания шли в ночь когда нагрузка минимальна.
        "purge-old-leads": {
            "task": "periodic.purge_old_leads",
            "schedule": crontab(minute=0, hour=4),
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
