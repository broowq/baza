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
    # --- Task timeouts ---
    # Global backstop for periodic/light tasks. The two heavy jobs get more
    # generous PER-TASK limits via task_annotations below — a large enrichment
    # legitimately runs longer than the global 25-min soft cap. Without these,
    # an OOM-killed worker leaves a job stuck 'running' forever (409 on the
    # project). SoftTimeLimitExceeded is caught in each task to mark the job
    # 'failed' before the worker dies; health_check sweeps up any job whose
    # worker died too hard to run its handler.
    task_time_limit=1800,        # hard kill after 30 min (global backstop)
    task_soft_time_limit=1500,   # SIGXCPU at 25 min (global backstop)
    task_annotations={
        # collect: 30 min soft / 35 min hard
        "jobs.collect_leads": {"soft_time_limit": 1800, "time_limit": 2100},
        # enrich: 60 min soft / 65 min hard (website scraping is slow per lead)
        "jobs.enrich_leads": {"soft_time_limit": 3600, "time_limit": 3900},
    },
    # --- acks_late: survive a lost worker ---
    # Acknowledge a task only after it finishes, and re-queue it if the worker
    # is lost (OOM/SIGKILL) mid-run, so the job isn't silently abandoned. On
    # Redis this needs a visibility_timeout LONGER than the longest task
    # (enrich hard cap 3900s) or Redis would redeliver an in-flight task and
    # double-run it; 7200s (2h) gives ample margin. A redelivered task is made
    # safe by a guard in each task that bails if the job is already failed/done
    # (see jobs.py) — so a job health_check already failed is never revived.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_transport_options={"visibility_timeout": 7200},
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
        # Revert entitlements when a paid subscription period lapses (nightly).
        "downgrade-expired-subscriptions": {
            "task": "periodic.downgrade_expired_subscriptions",
            "schedule": crontab(minute=30, hour=2),
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
