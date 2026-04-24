from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models import JobStatus, LeadStatus


class RunCollectionRequest(BaseModel):
    lead_limit: int = Field(default=100, ge=10, le=5000)


class EnrichSelectedRequest(BaseModel):
    # Max 500 to prevent memory/DB blow-up from malicious oversized arrays.
    lead_ids: list[str] = Field(default_factory=list, max_length=500)


class LeadOut(BaseModel):
    id: UUID
    organization_id: UUID
    project_id: UUID
    company: str
    city: str
    website: str
    domain: str
    email: str
    email_status: str = ""   # "" | "valid" | "no_mx" | "syntax" | "skipped"
    phone: str
    address: str
    contacts: dict
    contacts_json: dict
    score: int
    notes: str
    tags: list[str] = Field(default_factory=list)
    last_contacted_at: datetime | None = None
    reminder_at: datetime | None = None
    status: LeadStatus
    source_url: str
    enriched: bool
    demo: bool
    created_at: datetime

    class Config:
        from_attributes = True


class CollectionJobOut(BaseModel):
    id: UUID
    organization_id: UUID
    project_id: UUID
    status: JobStatus
    kind: str
    requested_limit: int
    found_count: int
    added_count: int
    enriched_count: int
    error: str | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class LeadUpdate(BaseModel):
    status: str | None = None  # "new", "contacted", "qualified", "rejected"
    notes: str | None = Field(default=None, max_length=10000)
    # Workflow fields
    tags: list[str] | None = Field(default=None, max_length=20)
    last_contacted_at: datetime | None = None
    reminder_at: datetime | None = None
    # Mark contact: when sales clicks "позвонил/написал" — sets last_contacted_at=now()
    mark_contacted: bool = False


class PaginatedLeadsOut(BaseModel):
    items: list[LeadOut]
    total: int
    page: int
    per_page: int
