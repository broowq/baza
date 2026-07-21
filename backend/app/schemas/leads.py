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
    # CRM fields
    assigned_to_user_id: UUID | None = None
    deal_value: int = 0
    expected_close_at: datetime | None = None
    source_url: str
    source: str = ""
    external_id: str = ""
    enriched: bool
    demo: bool
    # ── Качество компании (батч «поиск v2», 21.07.2026) ──────────────────
    rating: float | None = None          # рейтинг с карт (2GIS), 0–5
    review_count: int | None = None      # число отзывов
    inn: str = ""                        # ИНН из ЕГРЮЛ (DaData)
    legal_status: str = ""               # "" | ACTIVE | LIQUIDATING | LIQUIDATED | BANKRUPT | REORGANIZING
    hiring_vacancies: int | None = None  # открытые вакансии на hh.ru (None = не проверяли)
    created_at: datetime
    # Name of the owning project. Default "" keeps every existing endpoint
    # backward-compatible; only the org-wide /leads/all endpoint populates it.
    project_name: str = ""

    class Config:
        from_attributes = True


class LeadCreateIn(BaseModel):
    company: str = Field(min_length=1, max_length=180)
    city: str = Field(default="", max_length=120)
    website: str = Field(default="", max_length=300)
    email: str = Field(default="", max_length=255)
    phone: str = Field(default="", max_length=80)
    address: str = Field(default="", max_length=300)
    notes: str = Field(default="", max_length=10000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    status: str = "new"
    deal_value: int = Field(default=0, ge=0)
    assigned_to_user_id: UUID | None = None


class LeadImportRowError(BaseModel):
    row: int
    error: str


class LeadImportResult(BaseModel):
    total: int
    created: int
    duplicates: int
    errors: list[LeadImportRowError] = Field(default_factory=list)
    dry_run: bool
    # field -> matched original header (e.g. {"company": "Название", "email": "Почта"})
    detected_columns: dict[str, str] = Field(default_factory=dict)
    unmapped_headers: list[str] = Field(default_factory=list)
    sample: list[LeadOut] = Field(default_factory=list)


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
    # NOTE: no `other_niches` here — warehouse niches are other organizations'
    # search intents (cross-tenant data) and must not be exposed.
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
    status: str | None = None  # pipeline stage: new|contacted|qualified|proposal|won|rejected
    notes: str | None = Field(default=None, max_length=10000)
    # Workflow fields
    tags: list[str] | None = Field(default=None, max_length=20)
    last_contacted_at: datetime | None = None
    reminder_at: datetime | None = None
    # CRM fields. assigned_to_user_id: pass a UUID to assign, null to unassign
    # (use the *_set sentinels so an explicit null is distinguishable from omit).
    assigned_to_user_id: UUID | None = None
    deal_value: int | None = Field(default=None, ge=0, le=1_000_000_000)
    expected_close_at: datetime | None = None
    # Mark contact: when sales clicks "позвонил/написал" — sets last_contacted_at=now()
    mark_contacted: bool = False


class PaginatedLeadsOut(BaseModel):
    items: list[LeadOut]
    total: int
    page: int
    per_page: int


class LeadEmailIn(BaseModel):
    """Reply/write to the lead by email through the org's SMTP."""
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)


class LeadTouchIn(BaseModel):
    """A one-click channel touch (call / WhatsApp / Telegram button)."""
    channel: str  # "call" | "whatsapp" | "telegram"
    note: str = Field(default="", max_length=500)


class CallNoteCreate(BaseModel):
    """A call-journal entry. Comment is optional — just marking the call
    (who + when) is already valuable for a team splitting an outreach list."""
    comment: str = Field(default="", max_length=2000)


class CallNoteOut(BaseModel):
    id: UUID
    user_id: UUID | None
    user_name: str
    comment: str
    created_at: datetime

    class Config:
        from_attributes = True
