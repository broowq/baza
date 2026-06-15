"""CRM API: pipeline definition, tasks/follow-ups, unified activity timeline,
and the per-project sales funnel.

Built on top of the already-existing data model (LeadTask/LeadActivity), schemas
(app.schemas.crm) and the shared service (app.services.crm). Every query is
org-scoped; cross-org lead/task/project ids return 404 (opaque) just like the
leads routes.
"""
from __future__ import annotations

import uuid
from datetime import datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import asc, func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_org, get_current_user
from app.db.session import get_db
from app.models import (
    Lead,
    LeadActivity,
    LeadCallNote,
    LeadStatus,
    LeadTask,
    Membership,
    Organization,
    Project,
    User,
)
from app.schemas.crm import (
    ActivityOut,
    FunnelOut,
    FunnelStageOut,
    TaskCreate,
    TaskOut,
    TaskUpdate,
    TaskWithLeadOut,
)
from app.services.crm import (
    OPEN_STAGES,
    PIPELINE_STAGES,
    WON_STAGES,
    log_activity,
)

router = APIRouter(prefix="/crm", tags=["crm"])


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_org_lead_or_404(db: Session, lead_id: uuid.UUID, organization: Organization) -> Lead:
    """Org-scoped lead fetch (404 opacity). Mirrors the leads.py pattern but
    kept local so we don't import a private helper across modules."""
    lead = db.get(Lead, lead_id)
    if not lead or lead.organization_id != organization.id:
        raise HTTPException(status_code=404, detail="Лид не найден")
    project = db.get(Project, lead.project_id)
    if not project or project.organization_id != organization.id or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Лид не найден")
    return lead


def _get_org_task_or_404(db: Session, task_id: uuid.UUID, organization: Organization) -> LeadTask:
    """Org-scoped task fetch (404 opacity)."""
    task = db.get(LeadTask, task_id)
    if not task or task.organization_id != organization.id:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return task


def _validate_assignee(db: Session, organization: Organization, user_id: uuid.UUID) -> None:
    """Ensure the user is a member of this org before assigning (else 422)."""
    membership = db.execute(
        select(Membership.id).where(
            Membership.organization_id == organization.id,
            Membership.user_id == user_id,
        )
    ).first()
    if not membership:
        raise HTTPException(status_code=422, detail="Исполнитель не является участником организации")


# ── Pipeline definition ──────────────────────────────────────────────────────

@router.get("/pipeline")
def get_pipeline(organization: Organization = Depends(get_current_org)) -> list[dict]:
    """Stage definitions for the kanban board."""
    return PIPELINE_STAGES


# ── Tasks (per-lead) ─────────────────────────────────────────────────────────

@router.post("/leads/{lead_id}/tasks", response_model=TaskOut, status_code=201)
def create_task(
    lead_id: uuid.UUID,
    payload: TaskCreate,
    organization: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    lead = _get_org_lead_or_404(db, lead_id, organization)

    assignee_id = payload.assigned_to_user_id or user.id
    if payload.assigned_to_user_id is not None:
        _validate_assignee(db, organization, payload.assigned_to_user_id)

    task = LeadTask(
        organization_id=organization.id,
        lead_id=lead.id,
        assigned_to_user_id=assignee_id,
        created_by_user_id=user.id,
        title=payload.title,
        due_at=payload.due_at,
    )
    db.add(task)
    log_activity(db, lead=lead, kind="task_created", text=f"Задача: {payload.title}", user=user)
    db.commit()
    db.refresh(task)
    return task


@router.get("/leads/{lead_id}/tasks", response_model=list[TaskOut])
def list_lead_tasks(
    lead_id: uuid.UUID,
    organization: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
):
    """Tasks for a lead — open first, then by due_at (nulls last), then created_at."""
    _get_org_lead_or_404(db, lead_id, organization)
    tasks = db.execute(
        select(LeadTask)
        .where(
            LeadTask.lead_id == lead_id,
            LeadTask.organization_id == organization.id,
        )
        .order_by(
            LeadTask.done.asc(),
            asc(LeadTask.due_at).nulls_last(),
            LeadTask.created_at.asc(),
        )
    ).scalars().all()
    return tasks


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(
    task_id: uuid.UUID,
    payload: TaskUpdate,
    organization: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    task = _get_org_task_or_404(db, task_id, organization)

    if payload.title is not None:
        task.title = payload.title
    # Nullable PATCH: explicit null clears the due date; omitted leaves it.
    if "due_at" in payload.model_fields_set:
        task.due_at = payload.due_at
    if "assigned_to_user_id" in payload.model_fields_set:
        if payload.assigned_to_user_id is not None:
            _validate_assignee(db, organization, payload.assigned_to_user_id)
        task.assigned_to_user_id = payload.assigned_to_user_id

    if payload.done is not None:
        if payload.done and not task.done:
            # false → true: stamp completion + log timeline event.
            task.done = True
            task.done_at = datetime.now(timezone.utc)
            lead = db.get(Lead, task.lead_id)
            if lead is not None:
                log_activity(
                    db, lead=lead, kind="task_done", text=f"Выполнено: {task.title}", user=user
                )
        elif not payload.done and task.done:
            # true → false: reopen.
            task.done = False
            task.done_at = None

    db.commit()
    db.refresh(task)
    return task


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(
    task_id: uuid.UUID,
    organization: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
):
    task = _get_org_task_or_404(db, task_id, organization)
    db.delete(task)
    db.commit()
    return Response(status_code=204)


# ── Tasks (cross-project list) ───────────────────────────────────────────────

@router.get("/tasks", response_model=list[TaskWithLeadOut])
def list_tasks(
    scope: str = Query(default="open"),
    assignee: str | None = Query(default=None),
    organization: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cross-project task list joined with the lead's company + project_id.

    scope: "open" (default, not done), "today" (due today, not done),
           "overdue" (due before today, not done), "done".
    assignee: "me" (current user), a user UUID, or omitted (all).
    """
    query = (
        select(LeadTask, Lead.company, Lead.project_id)
        .join(Lead, Lead.id == LeadTask.lead_id)
        .where(LeadTask.organization_id == organization.id)
    )

    now = datetime.now(timezone.utc)
    today_start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    tomorrow_start = datetime.combine(now.date(), time.max, tzinfo=timezone.utc)

    if scope == "done":
        query = query.where(LeadTask.done.is_(True))
    elif scope == "today":
        query = query.where(
            LeadTask.done.is_(False),
            LeadTask.due_at >= today_start,
            LeadTask.due_at <= tomorrow_start,
        )
    elif scope == "overdue":
        query = query.where(
            LeadTask.done.is_(False),
            LeadTask.due_at < today_start,
        )
    else:  # "open" (default)
        query = query.where(LeadTask.done.is_(False))

    if assignee == "me":
        query = query.where(LeadTask.assigned_to_user_id == user.id)
    elif assignee:
        try:
            assignee_uuid = uuid.UUID(assignee)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Некорректный идентификатор исполнителя") from exc
        query = query.where(LeadTask.assigned_to_user_id == assignee_uuid)

    query = query.order_by(
        asc(LeadTask.due_at).nulls_last(),
        LeadTask.created_at.asc(),
    )

    rows = db.execute(query).all()
    result: list[TaskWithLeadOut] = []
    for task, company, project_id in rows:
        out = TaskWithLeadOut.model_validate(task)
        out.lead_company = company or ""
        out.project_id = project_id
        result.append(out)
    return result


# ── Unified activity timeline ────────────────────────────────────────────────

@router.get("/leads/{lead_id}/activities", response_model=list[ActivityOut])
def list_activities(
    lead_id: uuid.UUID,
    organization: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
):
    """Unified timeline: LeadActivity rows merged with LeadCallNote rows
    (call notes rendered as kind="call"), newest first, limited."""
    _get_org_lead_or_404(db, lead_id, organization)

    activities = db.execute(
        select(LeadActivity)
        .where(
            LeadActivity.lead_id == lead_id,
            LeadActivity.organization_id == organization.id,
        )
        .order_by(LeadActivity.created_at.desc())
        .limit(200)
    ).scalars().all()

    call_notes = db.execute(
        select(LeadCallNote)
        .where(
            LeadCallNote.lead_id == lead_id,
            LeadCallNote.organization_id == organization.id,
        )
        .order_by(LeadCallNote.created_at.desc())
        .limit(200)
    ).scalars().all()

    merged: list[ActivityOut] = [
        ActivityOut(
            id=str(a.id),
            kind=a.kind,
            text=a.text or "",
            user_name=a.user_name or "",
            meta=a.meta or {},
            created_at=a.created_at,
        )
        for a in activities
    ]
    merged.extend(
        ActivityOut(
            id=f"call:{note.id}",
            kind="call",
            text=note.comment or "",
            user_name=note.user_name or "",
            meta={},
            created_at=note.created_at,
        )
        for note in call_notes
    )

    merged.sort(key=lambda item: item.created_at, reverse=True)
    return merged[:200]


# ── Funnel ───────────────────────────────────────────────────────────────────

@router.get("/project/{project_id}/funnel", response_model=FunnelOut)
def get_funnel(
    project_id: uuid.UUID,
    organization: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
):
    """Per-project sales funnel: count + deal_value sum per pipeline stage,
    plus open/won aggregates and a conversion rate."""
    project = db.get(Project, project_id)
    if not project or project.organization_id != organization.id or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Проект не найден")

    rows = db.execute(
        select(
            Lead.status,
            func.count(Lead.id),
            func.coalesce(func.sum(Lead.deal_value), 0),
        )
        .where(Lead.project_id == project.id)
        .group_by(Lead.status)
    ).all()

    # status (LeadStatus enum) → (count, value)
    by_status: dict[str, tuple[int, int]] = {}
    for status, count, value in rows:
        key = status.value if isinstance(status, LeadStatus) else str(status)
        by_status[key] = (int(count or 0), int(value or 0))

    stages: list[FunnelStageOut] = []
    total_leads = 0
    open_leads = 0
    open_value = 0
    won_count = 0
    won_value = 0
    for stage in PIPELINE_STAGES:
        key = stage["key"]
        count, value = by_status.get(key, (0, 0))
        total_leads += count
        if key in OPEN_STAGES:
            open_leads += count
            open_value += value
        if key in WON_STAGES:
            won_count += count
            won_value += value
        stages.append(
            FunnelStageOut(
                key=key,
                label=stage["label"],
                count=count,
                value=value,
                terminal=stage["terminal"],
                won=stage["won"],
            )
        )

    lost_count = by_status.get(LeadStatus.rejected.value, (0, 0))[0]
    denom = won_count + lost_count
    conversion_rate = (won_count / denom) if denom else 0.0

    return FunnelOut(
        stages=stages,
        total_leads=total_leads,
        open_leads=open_leads,
        won_count=won_count,
        won_value=won_value,
        open_value=open_value,
        conversion_rate=conversion_rate,
    )
