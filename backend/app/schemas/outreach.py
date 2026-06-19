"""Schemas for email outreach: SMTP settings, sequences, enrollment, stats."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


# ── Per-org sending settings ─────────────────────────────────────────────────

class EmailSettingsIn(BaseModel):
    from_name: str = Field(default="", max_length=120)
    from_email: EmailStr
    smtp_host: str = Field(min_length=1, max_length=255)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_user: str = Field(min_length=1, max_length=255)
    # Write-only. Send to set/change; omit/empty to keep the stored one.
    smtp_password: str | None = Field(default=None, max_length=512)
    smtp_use_tls: bool = True
    imap_host: str = Field(default="", max_length=255)
    imap_port: int = Field(default=993, ge=1, le=65535)
    imap_user: str = Field(default="", max_length=255)
    imap_password: str | None = Field(default=None, max_length=512)
    daily_limit: int = Field(default=200, ge=1, le=5000)


class EmailSettingsOut(BaseModel):
    configured: bool = False
    from_name: str = ""
    from_email: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password_set: bool = False   # never return the secret, just whether it's set
    smtp_use_tls: bool = True
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password_set: bool = False
    daily_limit: int = 200
    sent_today: int = 0
    verified: bool = False


class TestEmailRequest(BaseModel):
    to_email: EmailStr


# ── Sequences + steps ────────────────────────────────────────────────────────

class SequenceStepIn(BaseModel):
    delay_days: int = Field(default=0, ge=0, le=365)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)


class SequenceStepOut(BaseModel):
    id: UUID
    step_order: int
    delay_days: int
    subject: str
    body: str

    class Config:
        from_attributes = True


class SequenceIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    project_id: UUID | None = None
    steps: list[SequenceStepIn] = Field(default_factory=list, max_length=20)


class SequenceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    status: str | None = None  # active | paused | archived
    steps: list[SequenceStepIn] | None = Field(default=None, max_length=20)


class SequenceStatsOut(BaseModel):
    enrolled: int = 0
    active: int = 0
    completed: int = 0
    replied: int = 0
    unsubscribed: int = 0
    bounced: int = 0
    stopped: int = 0
    sent_messages: int = 0


class SequenceOut(BaseModel):
    id: UUID
    name: str
    status: str
    project_id: UUID | None = None
    created_at: datetime
    steps: list[SequenceStepOut] = Field(default_factory=list)
    stats: SequenceStatsOut = Field(default_factory=SequenceStatsOut)

    class Config:
        from_attributes = True


# ── Enrollment ───────────────────────────────────────────────────────────────

class EnrollRequest(BaseModel):
    lead_ids: list[UUID] = Field(min_length=1, max_length=1000)


class EnrollResult(BaseModel):
    enrolled: int
    skipped: int       # no email / opted-out / already enrolled


class EnrollmentOut(BaseModel):
    id: UUID
    lead_id: UUID
    lead_company: str = ""
    to_email: str = ""
    status: str
    current_step: int
    next_send_at: datetime | None = None
    last_sent_at: datetime | None = None
