from app.tasks.celery_app import celery
from app.tasks import jobs  # noqa: F401
from app.tasks import periodic  # noqa: F401
# These MUST be imported here or the worker won't register their tasks and
# will drop them as "unregistered task" — silently breaking email verification
# (email.send_email) and CRM delivery (webhook.push_lead). The backend imports
# them directly when calling .delay(), so the bug only shows up worker-side.
from app.tasks import email_tasks  # noqa: F401
from app.tasks import webhook_tasks  # noqa: F401
# Outreach drip-sequences: beat шлёт outreach.process_sequences каждые 5 мин и
# outreach.poll_replies каждые 20 мин — без этого импорта воркер отбрасывал их
# как unregistered и email-цепочки НЕ работали на проде (288 ошибок/сутки).
# Регресс закрыт tests/test_worker_task_registry.py: каждая задача из
# beat_schedule обязана быть зарегистрирована этим модулем.
from app.tasks import outreach_tasks  # noqa: F401

__all__ = ["celery"]
