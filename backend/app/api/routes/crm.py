"""CRM API: pipeline definition, tasks/follow-ups, unified activity timeline,
and the per-project sales funnel.

Built on top of the already-existing data model (LeadTask/LeadActivity), schemas
(app.schemas.crm) and the shared service (app.services.crm). Every query is
org-scoped; cross-org lead/task/project ids return 404 (opaque) just like the
leads routes.
"""
from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import Integer, asc, func, select
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
    OutreachMessage,
    OutreachReply,
    Project,
    User,
)
from app.schemas.crm import (
    ActivityOut,
    DashboardAssigneeOut,
    DashboardOut,
    DashboardPointOut,
    DashboardSourceOut,
    DashboardStatusOut,
    FunnelOut,
    FunnelStageOut,
    NotificationsOut,
    NotifGroupReminders,
    NotifGroupReplies,
    NotifGroupTasks,
    NotifReminderOut,
    NotifReplyOut,
    NotifTaskOut,
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
    """Unified timeline: LeadActivity + LeadCallNote rows merged with the lead's
    email comms (sent OutreachMessage with open/click status, inbound
    OutreachReply), newest first, capped at 200 total."""
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

    sent_emails = db.execute(
        select(OutreachMessage)
        .where(
            OutreachMessage.lead_id == lead_id,
            OutreachMessage.organization_id == organization.id,
        )
        .order_by(OutreachMessage.created_at.desc())
        .limit(200)
    ).scalars().all()

    replies = db.execute(
        select(OutreachReply)
        .where(
            OutreachReply.lead_id == lead_id,
            OutreachReply.organization_id == organization.id,
        )
        .order_by(OutreachReply.created_at.desc())
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
    merged.extend(
        ActivityOut(
            id=f"msg:{m.id}",
            kind="email_sent",
            text=m.subject or "",
            user_name="",
            meta={
                "subject": m.subject,
                "status": m.status,
                "opened": m.opened_at is not None,
                "opens": m.opens_count,
                "clicked": m.clicked_at is not None,
                "clicks": m.clicks_count,
            },
            created_at=m.created_at,
        )
        for m in sent_emails
    )
    merged.extend(
        ActivityOut(
            id=f"reply:{r.id}",
            kind="email_in",
            text=r.snippet or "",
            user_name=r.from_email or "",
            meta={"from_email": r.from_email, "subject": r.subject},
            created_at=(r.received_at or r.created_at),
        )
        for r in replies
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


# ── Org-wide dashboard ───────────────────────────────────────────────────────

@router.get("/dashboard", response_model=DashboardOut)
def get_dashboard(
    organization: Organization = Depends(get_current_org),
    db: Session = Depends(get_db),
):
    """Org-wide analytics across every live project (soft-deleted projects
    excluded via the Project join). All aggregates are grouped queries — no
    per-lead/per-user round-trips. Mirrors get_funnel's aggregation style."""
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # ── by_status: count + sum(deal_value) per stage ─────────────────────────
    status_rows = db.execute(
        select(
            Lead.status,
            func.count(Lead.id),
            func.coalesce(func.sum(Lead.deal_value), 0),
        )
        .join(Project, Project.id == Lead.project_id)
        .where(
            Lead.organization_id == organization.id,
            Project.deleted_at.is_(None),
        )
        .group_by(Lead.status)
    ).all()

    by_status_map: dict[str, tuple[int, int]] = {}
    for status, count, value in status_rows:
        key = status.value if isinstance(status, LeadStatus) else str(status)
        by_status_map[key] = (int(count or 0), int(value or 0))

    by_status: list[DashboardStatusOut] = []
    leads_total = 0
    pipeline_value = 0
    won = 0
    won_value = 0
    for stage in PIPELINE_STAGES:
        key = stage["key"]
        count, value = by_status_map.get(key, (0, 0))
        leads_total += count
        if key in OPEN_STAGES:
            pipeline_value += value
        if key in WON_STAGES:
            won += count
            won_value += value
        by_status.append(DashboardStatusOut(status=key, count=count, value=value))

    lost = by_status_map.get(LeadStatus.rejected.value, (0, 0))[0]
    denom = won + lost
    conversion_rate = (won / denom) if denom else 0.0

    # ── leads_this_month ─────────────────────────────────────────────────────
    leads_this_month = int(
        db.execute(
            select(func.count(Lead.id))
            .join(Project, Project.id == Lead.project_id)
            .where(
                Lead.organization_id == organization.id,
                Project.deleted_at.is_(None),
                Lead.created_at >= month_start,
            )
        ).scalar()
        or 0
    )

    # ── by_source: top 8 desc by count ("—" for empty) ───────────────────────
    source_rows = db.execute(
        select(Lead.source, func.count(Lead.id))
        .join(Project, Project.id == Lead.project_id)
        .where(
            Lead.organization_id == organization.id,
            Project.deleted_at.is_(None),
        )
        .group_by(Lead.source)
        .order_by(func.count(Lead.id).desc())
        .limit(8)
    ).all()
    by_source = [
        DashboardSourceOut(source=(src or "—"), count=int(cnt or 0))
        for src, cnt in source_rows
    ]

    # ── by_assignee: leads + won per owner, top 12 ───────────────────────────
    assignee_rows = db.execute(
        select(
            Lead.assigned_to_user_id,
            func.count(Lead.id),
            func.coalesce(
                func.sum(func.cast(Lead.status == LeadStatus.won, Integer)),
                0,
            ),
        )
        .join(Project, Project.id == Lead.project_id)
        .where(
            Lead.organization_id == organization.id,
            Project.deleted_at.is_(None),
        )
        .group_by(Lead.assigned_to_user_id)
        .order_by(func.count(Lead.id).desc())
        .limit(12)
    ).all()

    # Resolve owner names in a single Membership+User query (no N+1).
    owner_ids = [uid for uid, _, _ in assignee_rows if uid is not None]
    name_map: dict[uuid.UUID, str] = {}
    if owner_ids:
        name_rows = db.execute(
            select(User.id, User.full_name, User.email)
            .join(Membership, Membership.user_id == User.id)
            .where(
                Membership.organization_id == organization.id,
                User.id.in_(owner_ids),
            )
        ).all()
        for uid, full_name, email in name_rows:
            name_map[uid] = full_name or email or "—"

    by_assignee = [
        DashboardAssigneeOut(
            user_id=(str(uid) if uid is not None else None),
            name=(name_map.get(uid, "—") if uid is not None else "Не назначен"),
            leads=int(cnt or 0),
            won=int(won_cnt or 0),
        )
        for uid, cnt, won_cnt in assignee_rows
    ]

    # ── over_time: leads/day for the last 14 days incl. zero-days ────────────
    today = now.date()
    window_start = datetime.combine(
        today - timedelta(days=13), time.min, tzinfo=timezone.utc
    )
    day_expr = func.date(Lead.created_at)
    over_rows = db.execute(
        select(day_expr, func.count(Lead.id))
        .join(Project, Project.id == Lead.project_id)
        .where(
            Lead.organization_id == organization.id,
            Project.deleted_at.is_(None),
            Lead.created_at >= window_start,
        )
        .group_by(day_expr)
    ).all()

    counts_by_day: dict[str, int] = {}
    for day, cnt in over_rows:
        # func.date may return a date object (PG) or an ISO string (sqlite).
        key = day.isoformat() if hasattr(day, "isoformat") else str(day)[:10]
        counts_by_day[key] = int(cnt or 0)

    over_time = []
    for i in range(14):
        d = (today - timedelta(days=13 - i)).isoformat()
        over_time.append(DashboardPointOut(date=d, count=counts_by_day.get(d, 0)))

    return DashboardOut(
        leads_total=leads_total,
        leads_this_month=leads_this_month,
        by_status=by_status,
        won=won,
        lost=lost,
        conversion_rate=conversion_rate,
        pipeline_value=pipeline_value,
        won_value=won_value,
        by_source=by_source,
        by_assignee=by_assignee,
        over_time=over_time,
    )


# ── Notifications (the in-app bell) ──────────────────────────────────────────

@router.get("/notifications", response_model=NotificationsOut)
def get_notifications(
    organization: Organization = Depends(get_current_org),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Drives the sidebar bell: overdue tasks, due reminders, fresh inbound
    replies. Each group returns a count + up to 5 preview items. total is the
    badge number."""
    now = datetime.now(timezone.utc)

    # ── overdue tasks (done=false, due in the past) ──────────────────────────
    overdue_count = int(
        db.execute(
            select(func.count(LeadTask.id)).where(
                LeadTask.organization_id == organization.id,
                LeadTask.done.is_(False),
                LeadTask.due_at.isnot(None),
                LeadTask.due_at < now,
            )
        ).scalar()
        or 0
    )
    overdue_rows = db.execute(
        select(LeadTask, Lead.company)
        .join(Lead, Lead.id == LeadTask.lead_id)
        .where(
            LeadTask.organization_id == organization.id,
            LeadTask.done.is_(False),
            LeadTask.due_at.isnot(None),
            LeadTask.due_at < now,
        )
        .order_by(asc(LeadTask.due_at))  # soonest-overdue first
        .limit(5)
    ).all()
    overdue_items = [
        NotifTaskOut(
            id=str(task.id),
            title=task.title,
            lead_id=str(task.lead_id),
            lead_company=company or "",
            due_at=task.due_at,
        )
        for task, company in overdue_rows
    ]

    # ── due reminders (Lead.reminder_at <= now) ──────────────────────────────
    reminder_count = int(
        db.execute(
            select(func.count(Lead.id)).where(
                Lead.organization_id == organization.id,
                Lead.reminder_at.isnot(None),
                Lead.reminder_at <= now,
            )
        ).scalar()
        or 0
    )
    reminder_rows = db.execute(
        select(Lead.id, Lead.company, Lead.reminder_at).where(
            Lead.organization_id == organization.id,
            Lead.reminder_at.isnot(None),
            Lead.reminder_at <= now,
        )
        .order_by(asc(Lead.reminder_at))
        .limit(5)
    ).all()
    reminder_items = [
        NotifReminderOut(
            lead_id=str(lid),
            company=company or "",
            reminder_at=reminder_at,
        )
        for lid, company, reminder_at in reminder_rows
    ]

    # ── new inbound replies in the last 7 days ───────────────────────────────
    week_ago = now - timedelta(days=7)
    recv = func.coalesce(OutreachReply.received_at, OutreachReply.created_at)
    reply_count = int(
        db.execute(
            select(func.count(OutreachReply.id)).where(
                OutreachReply.organization_id == organization.id,
                recv >= week_ago,
            )
        ).scalar()
        or 0
    )
    reply_rows = db.execute(
        select(OutreachReply)
        .where(
            OutreachReply.organization_id == organization.id,
            recv >= week_ago,
        )
        .order_by(recv.desc())  # newest first
        .limit(5)
    ).scalars().all()
    reply_items = [
        NotifReplyOut(
            id=str(r.id),
            lead_id=(str(r.lead_id) if r.lead_id is not None else None),
            from_email=r.from_email or "",
            subject=r.subject or "",
            received_at=(r.received_at or r.created_at),
        )
        for r in reply_rows
    ]

    total = overdue_count + reminder_count + reply_count

    return NotificationsOut(
        overdue_tasks=NotifGroupTasks(count=overdue_count, items=overdue_items),
        due_reminders=NotifGroupReminders(count=reminder_count, items=reminder_items),
        new_replies=NotifGroupReplies(count=reply_count, items=reply_items),
        total=total,
    )
