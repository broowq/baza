"""Schemas for the CRM layer: tasks, activity timeline, funnel, bulk actions."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# ── Tasks / follow-ups ───────────────────────────────────────────────────────

class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    due_at: datetime | None = None
    assigned_to_user_id: UUID | None = None


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    due_at: datetime | None = None
    assigned_to_user_id: UUID | None = None
    done: bool | None = None


class TaskOut(BaseModel):
    id: UUID
    lead_id: UUID
    title: str
    due_at: datetime | None = None
    done: bool
    done_at: datetime | None = None
    assigned_to_user_id: UUID | None = None
    created_by_user_id: UUID | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class TaskWithLeadOut(TaskOut):
    """Task enriched with its lead's display info for cross-project task views."""
    lead_company: str = ""
    project_id: UUID | None = None


# ── Activity timeline ────────────────────────────────────────────────────────

class ActivityOut(BaseModel):
    id: str            # str: merged feed includes call-notes with a synthetic id
    kind: str
    text: str = ""
    user_name: str = ""
    meta: dict = Field(default_factory=dict)
    created_at: datetime


# ── Funnel / pipeline analytics ──────────────────────────────────────────────

class FunnelStageOut(BaseModel):
    key: str
    label: str
    count: int
    value: int          # sum of deal_value in this stage (rubles)
    terminal: bool
    won: bool


class FunnelOut(BaseModel):
    stages: list[FunnelStageOut]
    total_leads: int
    open_leads: int
    won_count: int
    won_value: int
    open_value: int
    conversion_rate: float   # won / (won + lost), 0..1


# ── Bulk actions ─────────────────────────────────────────────────────────────

class BulkLeadAction(BaseModel):
    lead_ids: list[UUID] = Field(min_length=1, max_length=500)
    action: str          # "assign" | "stage" | "add_tag" | "delete"
    assigned_to_user_id: UUID | None = None
    status: str | None = None
    tag: str | None = Field(default=None, max_length=30)


class BulkResult(BaseModel):
    updated: int
