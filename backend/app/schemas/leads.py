from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models import JobStatus, LeadStatus


class RunCollectionRequest(BaseModel):
    # For COLLECT this is the dose — how many NEW companies to add this run
    # (default 10; the task clamps to 200). For ENRICH it's how many leads to
    # enrich. le kept high enough for enrich batches.
    lead_limit: int = Field(default=10, ge=1, le=500)


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
    source: str = ""
    external_id: str = ""
    enriched: bool
    demo: bool
    created_at: datetime

    class Config:
        from_attributes = True


class LeadWarehouseRef(BaseModel):
    """Cross-reference into the shared company warehouse for a lead.

    Present (found=True) when a matching Company row exists (same dedup_key).
    Lets the lead-detail drawer show "seen N times across M niches" enrichment.
    """

    found: bool = False
    company_id: UUID | None = None
    times_seen: int = 0
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    # Niches this company surfaced under in OTHER searches (across all orgs).
    other_niches: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    best_score: int = 0
    inn: str = ""
    twogis_firm_id: str = ""


class LeadDetailOut(LeadOut):
    """Full Lead plus a computed description and warehouse cross-reference.

    Extends LeadOut (all lead fields) with:
      * description — a human-readable summary composed from the lead's own
        contacts/categories when the lead has no description of its own,
      * warehouse — the cross-org Company registry block (or found=False).
    """

    description: str = ""
    warehouse: LeadWarehouseRef = Field(default_factory=LeadWarehouseRef)


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
