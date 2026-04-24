import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PlanType(str, enum.Enum):
    free = "free"
    starter = "starter"
    pro = "pro"
    team = "team"


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


class LeadStatus(str, enum.Enum):
    new = "new"
    contacted = "contacted"
    qualified = "qualified"
    rejected = "rejected"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    plan: Mapped[PlanType] = mapped_column(Enum(PlanType), default=PlanType.free, nullable=False)
    leads_used_current_month: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    leads_limit_per_month: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    projects_limit: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    users_limit: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    can_invite_members: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Webhook URL for CRM integrations (Bitrix24, AmoCRM, etc). Each new lead
    # is POSTed there as JSON. Empty = disabled.
    lead_webhook_url: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    memberships = relationship("Membership", back_populates="organization", cascade="all, delete-orphan")
    projects = relationship("Project", back_populates="organization", cascade="all, delete-orphan")
    invites = relationship("Invite", back_populates="organization", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    memberships = relationship("Membership", back_populates="user", cascade="all, delete-orphan")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("organization_id", "user_id", name="uq_org_user"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(32), default="member", nullable=False)

    organization = relationship("Organization", back_populates="memberships")
    user = relationship("User", back_populates="memberships")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(140), nullable=False)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    niche: Mapped[str] = mapped_column(String(120), nullable=False)
    geography: Mapped[str] = mapped_column(String(120), nullable=False)
    segments: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    # OKVED codes of TARGET CUSTOMERS (not the seller). Extracted by LLM at
    # project creation / prompt-enhance time. List of {code, label, confidence}.
    # Phase 1: used only for UI display + future ФНС ЕГРЮЛ lookups.
    # Phase 2 (later): drives direct ФНС dump queries.
    okved_codes: Mapped[list[dict]] = mapped_column(JSONB, default=list, nullable=False)
    cron_schedule: Mapped[str] = mapped_column(String(120), default="0 9 * * 1", nullable=False)
    auto_collection_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)

    organization = relationship("Organization", back_populates="projects")
    leads = relationship("Lead", back_populates="project", cascade="all, delete-orphan")
    jobs = relationship("CollectionJob", back_populates="project", cascade="all, delete-orphan")


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (UniqueConstraint("project_id", "website", name="uq_project_website"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), index=True)
    company: Mapped[str] = mapped_column(String(180), nullable=False)
    city: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    website: Mapped[str] = mapped_column(String(300), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    # Deliverability status after MX-record check at enrichment time.
    # One of: "valid" (MX present), "no_mx" (syntax-OK but dead domain),
    # "syntax" (invalid format), "skipped" (DNS temp error), "" (not checked).
    email_status: Mapped[str] = mapped_column(String(20), default="", nullable=False)
    phone: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    address: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    contacts: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    contacts_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Workflow fields — sales user adds these after first contact
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None, index=True)
    reminder_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None, index=True)
    status: Mapped[LeadStatus] = mapped_column(Enum(LeadStatus), default=LeadStatus.new, nullable=False, index=True)
    source_url: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    # Data source that originally surfaced this lead:
    # "yandex_maps" | "2gis" | "rusprofile" | "searxng" | "bing" | "maps_searxng"
    # Empty for legacy leads imported before this field existed.
    source: Mapped[str] = mapped_column(String(24), default="", nullable=False, index=True)
    # External identifier from the source: 2GIS firm_id, rusprofile.ru entity id,
    # ЕГРЮЛ ОГРН (future), etc. Users can click through to the source's card.
    external_id: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    enriched: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    project = relationship("Project", back_populates="leads")


class CollectionJob(Base):
    __tablename__ = "collection_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), index=True)
    project_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"), index=True)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.queued, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), default="collect", nullable=False)
    requested_limit: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    found_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    added_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    enriched_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    project = relationship("Project", back_populates="jobs")


class Invite(Base):
    __tablename__ = "invites"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"))
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="member", nullable=False)
    token: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    accepted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    organization = relationship("Organization", back_populates="invites")


class ActionLog(Base):
    __tablename__ = "action_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    plan_id: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    provider_subscription_id: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
