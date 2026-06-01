from app.tasks.celery_app import celery
from app.tasks import jobs  # noqa: F401
from app.tasks import periodic  # noqa: F401
# These two MUST be imported here or the worker won't register their tasks and
# will drop them as "unregistered task" — silently breaking email verification
# (email.send_email) and CRM delivery (webhook.push_lead). The backend imports
# them directly when calling .delay(), so the bug only shows up worker-side.
from app.tasks import email_tasks  # noqa: F401
from app.tasks import webhook_tasks  # noqa: F401

__all__ = ["celery"]
