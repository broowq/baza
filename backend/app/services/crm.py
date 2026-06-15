"""CRM domain helpers — pipeline definition + activity-timeline logging.

Shared by the leads + crm API routes so activity events are written
consistently. log_activity does NOT commit — the caller owns the transaction.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models import LeadActivity, LeadStatus, User

# ── Sales pipeline ───────────────────────────────────────────────────────────
# Ordered stages for the kanban board + funnel. `terminal` marks closed stages.
# `won` flags the success stage (counts toward won revenue).
PIPELINE_STAGES: list[dict] = [
    {"key": "new",       "label": "Новый",          "terminal": False, "won": False},
    {"key": "contacted", "label": "Связались",      "terminal": False, "won": False},
    {"key": "qualified", "label": "Квалифицирован", "terminal": False, "won": False},
    {"key": "proposal",  "label": "КП отправлено",  "terminal": False, "won": False},
    {"key": "won",       "label": "Сделка",         "terminal": True,  "won": True},
    {"key": "rejected",  "label": "Отказ",          "terminal": True,  "won": False},
]

STAGE_LABELS: dict[str, str] = {s["key"]: s["label"] for s in PIPELINE_STAGES}
OPEN_STAGES: list[str] = [s["key"] for s in PIPELINE_STAGES if not s["terminal"]]
WON_STAGES: list[str] = [s["key"] for s in PIPELINE_STAGES if s["won"]]


def stage_label(status) -> str:
    key = status.value if isinstance(status, LeadStatus) else str(status)
    return STAGE_LABELS.get(key, key)


def log_activity(
    db: Session,
    *,
    lead,
    kind: str,
    text: str = "",
    user: Optional[User] = None,
    meta: Optional[dict] = None,
) -> LeadActivity:
    """Append a timeline event for `lead`. Caller commits.

    user_name is snapshotted so the timeline survives the user being removed.
    """
    activity = LeadActivity(
        organization_id=lead.organization_id,
        lead_id=lead.id,
        user_id=getattr(user, "id", None),
        user_name=((getattr(user, "full_name", "") or getattr(user, "email", "")) if user else "")[:120],
        kind=kind,
        text=(text or "")[:2000],
        meta=meta or {},
    )
    db.add(activity)
    return activity
