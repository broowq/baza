import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
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
    # Исторический казус имён: enum-значение `team` занято тиром Business с
    # первых миграций, поэтому средний тир «Team» живёт под значением `growth`.
    # Отображаемые имена — в plans.PLAN_NAMES (growth → «Team», team → «Business»).
    growth = "growth"
    pro = "pro"
    team = "team"


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"


class LeadStatus(str, enum.Enum):
    # Sales pipeline stages (ordered new → won; rejected is the terminal "lost").
    new = "new"
    contacted = "contacted"
    qualified = "qualified"
    proposal = "proposal"   # КП отправлено
    won = "won"             # Сделка закрыта успешно
    rejected = "rejected"   # Проигран / отказ (terminal lost)


class Organization(Base):
    __tablename__ = "organizations"
    # Mirrors the migration-created index so autogenerate doesn't drop it.
    __table_args__ = (Index("ix_organizations_name", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    plan: Mapped[PlanType] = mapped_column(Enum(PlanType), default=PlanType.free, nullable=False)
    leads_used_current_month: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    leads_limit_per_month: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    projects_limit: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    users_limit: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    can_invite_members: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Webhook URL for CRM integrations (Bitrix24, AmoCRM, etc). Each new lead
    # is POSTed there as JSON. Empty = disabled.
    lead_webhook_url: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    # ── AI cost cap (per calendar month) ────────────────────────────────────
    # Stored in kopecks (₽ × 100) to keep arithmetic integer-only and avoid
    # floating-point drift across thousands of LLM calls. Both fields reset
    # alongside leads_used_current_month on the 1st of each month.
    #   ai_cost_used_kopecks_current_month  — running spend
    #   ai_cost_limit_kopecks_per_month     — hard cap; LLM calls refused above
    # BigInteger so we don't overflow at team-tier (millions of kopecks/mo).
    ai_cost_used_kopecks_current_month: Mapped[int] = mapped_column(
        BigInteger, default=0, nullable=False, server_default="0"
    )
    ai_cost_limit_kopecks_per_month: Mapped[int] = mapped_column(
        BigInteger, default=0, nullable=False, server_default="0"
    )
    # ── Yandex Geosearch request meter (per-org, monthly) ─────────────────────
    # Yandex Geosearch is the dominant variable cost — paid per request, and
    # measured at ~0.21 request/lead. Without a per-org cap one heavy collector
    # can drain the shared paid key and blow the tier's margin (one Business at
    # full quota ≈ a whole 1k/day subscription). Capped per tier; resets on the
    # 1st with leads_used / ai_cost_used. Starter/Free = 0 (Yandex is Pro/Team).
    yandex_requests_used_current_month: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0"
    )
    yandex_requests_limit_per_month: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0"
    )
    # Персональный grandfather-кап НА PRO (сетка 2026-07-09 срезала шаблонный
    # кап Pro 1 400 → 1 200, ранним пилотам обещано 1 400 НАВСЕГДА). NULL = нет
    # оговорки. apply_plan_limits() применяет его ТОЛЬКО на PlanType.pro —
    # обещание привязано к тарифу 16 900 ₽ и не переносится ни вниз (на Team
    # 9 900 дало бы наценку ×7 — пробой ×10), ни на планы без капа. Переживает
    # любые lapse/downgrade/повторные покупки — в отличие от прежней идеи «не
    # срезать сохранённый лимит», которую адверсариал-ревью разнесло. Правится
    # только прямым UPDATE (админ-эндпоинта сознательно нет).
    yandex_requests_cap_override: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    # ── 152-ФЗ retention policy (ст. 5 ч. 7) ──────────────────────────
    # Срок хранения собранных лидов. По истечении этого срока без
    # активности лид удаляется фоновым cron-таском (purge_old_leads).
    # Дефолт 730 дней (2 года) — соответствует требованию НК РФ ст. 23
    # о хранении документов налогового учёта.
    # 0 = бесконечно (только для тестовых аккаунтов).
    leads_retention_days: Mapped[int] = mapped_column(
        Integer, default=730, nullable=False, server_default="730"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    memberships = relationship("Membership", back_populates="organization", cascade="all, delete-orphan")
    projects = relationship("Project", back_populates="organization", cascade="all, delete-orphan")
    invites = relationship("Invite", back_populates="organization", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    # Каноническая identity ящика (plus-теги/точки Gmail/алиасы Яндекса
    # схлопнуты) — анти-мультиакк триала, см. registration_guard. Индекс
    # НЕуникальный: у исторических юзеров возможны коллизии после
    # нормализации, дубль ловится app-проверкой при регистрации.
    email_normalized: Mapped[str] = mapped_column(String(255), default="", nullable=False, index=True)
    # IP регистрации (X-Real-IP от nginx) — форензика фермерства триалов.
    registration_ip: Mapped[str] = mapped_column(String(45), default="", nullable=False)
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
    # Жёсткие исключения из промпта пользователя («только b2b», «не розница»,
    # «кроме…») — типы компаний, которые НЕЛЬЗЯ приносить, даже если они
    # формально матчатся на segments. Извлекаются энхансером при создании
    # проекта; применяются складским отбором (NOT-клаузы), LLM-фильтром дозы
    # и live-фильтром. Пустой список = ограничений нет.
    excluded_segments: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    # Требование к САЙТУ клиента из промпта (инцидент 14.07: веб-студия просила
    # «клиентов, у которых НЕТ сайтов» — констрейнт молча терялся, склад выдал
    # топ по скору, где сайт даёт +8). Значения: 'any' | 'no_website' |
    # 'with_website'. Извлекается энхансером, применяется складским SQL,
    # live-скорингом, LLM-фильтром и верификацией дозы через веб-поиск.
    website_preference: Mapped[str] = mapped_column(String(16), default="any", nullable=False)
    # OKVED codes of TARGET CUSTOMERS (not the seller). Extracted by LLM at
    # project creation / prompt-enhance time. List of {code, label, confidence}.
    # Phase 1: used only for UI display + future ФНС ЕГРЮЛ lookups.
    # Phase 2 (later): drives direct ФНС dump queries.
    okved_codes: Mapped[list[dict]] = mapped_column(JSONB, default=list, nullable=False)
    cron_schedule: Mapped[str] = mapped_column(String(120), default="0 9 * * 1", nullable=False)
    auto_collection_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Set when a paid live seed found 0 new companies (sources exhausted for this
    # niche+geo vs what's already collected). Gates live re-seeding for a cooldown
    # window so repeat collects don't burn API calls returning the same set.
    leads_exhausted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    # Cached LLM search-optimized niche (enhance_prompt's search_queries_niche).
    # Computed once and reused by every dosed collect so we don't pay for an LLM
    # prompt-enhance on each dose. Reset to "" when the project prompt changes.
    search_query: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)

    organization = relationship("Organization", back_populates="projects")
    leads = relationship("Lead", back_populates="project", cascade="all, delete-orphan")
    jobs = relationship("CollectionJob", back_populates="project", cascade="all, delete-orphan")


class Lead(Base):
    __tablename__ = "leads"
    # Indexes mirror the ones created in migrations so `alembic revision
    # --autogenerate` doesn't emit drop_index for them.
    __table_args__ = (
        UniqueConstraint("project_id", "website", name="uq_project_website"),
        Index("ix_leads_project_id_status", "project_id", "status"),
        Index("ix_leads_project_score", "project_id", "score"),
        Index("ix_leads_organization_id_created_at", "organization_id", "created_at"),
        Index("ix_leads_project_domain_company", "project_id", "domain", "company"),
        Index("ix_leads_domain", "domain"),
        Index("ix_leads_website", "website"),
    )

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
    email_status: Mapped[str] = mapped_column(String(20), default="", nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    address: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    contacts: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    contacts_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    # «О компании»: чем занимается компания-лид. Источники по убыванию качества:
    # meta-description с сайта (обогащение) > описание/сниппет кандидата при
    # сборе (2ГИС/веб) > бэкфилл из склада companies (миграция). Пустая строка =
    # описания нет; карточка тогда собирает суррогат из категорий/метаданных.
    description: Mapped[str] = mapped_column(Text, default="", nullable=False, server_default="")
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    # Workflow fields — sales user adds these after first contact
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    last_contacted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None, index=True)
    reminder_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None, index=True)
    status: Mapped[LeadStatus] = mapped_column(Enum(LeadStatus), default=LeadStatus.new, nullable=False, index=True)
    # ── CRM fields ──────────────────────────────────────────────────────────
    # Owner of this lead within the org (sales rep). SET NULL on user removal so
    # the lead survives but becomes unassigned.
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Deal/opportunity value in whole rubles (0 = not set). Summed per pipeline
    # stage for the funnel/forecast.
    deal_value: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    # Expected close date for forecasting.
    expected_close_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    # Outreach suppression: set when the lead clicks unsubscribe (or hard-bounces).
    # Sequence sending skips opted-out leads; honours 152-ФЗ / CAN-SPAM opt-out.
    email_opt_out: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source_url: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    # Data source that originally surfaced this lead:
    # "yandex_maps" | "2gis" | "rusprofile" | "yandex_search" | "searxng" | "bing" | "maps_searxng"
    # Empty for legacy leads imported before this field existed.
    source: Mapped[str] = mapped_column(String(24), default="", nullable=False, index=True)
    # External identifier from the source: 2GIS firm_id, rusprofile.ru entity id,
    # ЕГРЮЛ ОГРН (future), etc. Users can click through to the source's card.
    external_id: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    enriched: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    # Bumped on every UPDATE (onupdate) — tracks last activity on the lead so
    # GDPR/152-ФЗ retention purge (purge_old_leads) can delete by inactivity,
    # not by creation date. Backfilled to created_at for pre-existing rows.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    project = relationship("Project", back_populates="leads")


class LeadCallNote(Base):
    """Call-journal entry on a lead: who called, when, and a free comment.

    user_name is a snapshot so history survives user rename/removal;
    user_id is SET NULL on user deletion, rows cascade with the lead.
    """
    __tablename__ = "lead_call_notes"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    user_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    comment: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )


class LeadTask(Base):
    """A follow-up task/to-do on a lead (call back, send КП, meeting…).

    Generalises the single reminder_at into a proper task list with an owner,
    due date and done state. Rows cascade with the lead/org; user FKs SET NULL.
    """
    __tablename__ = "lead_tasks"
    __table_args__ = (
        Index("ix_lead_tasks_org_done_due", "organization_id", "done", "due_at"),
        Index("ix_lead_tasks_assignee_done", "assigned_to_user_id", "done"),
        Index("ix_lead_tasks_lead", "lead_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    assigned_to_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    done: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    done_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )


class LeadActivity(Base):
    """Immutable activity-timeline event on a lead (stage change, assignment,
    note, call, task, value change…). Powers the unified history feed.

    user_name is snapshotted so the timeline survives user removal.
    """
    __tablename__ = "lead_activities"
    __table_args__ = (Index("ix_lead_activities_lead_created", "lead_id", "created_at"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    user_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    # created | stage_changed | assigned | unassigned | value_changed | note |
    # contacted | task_created | task_done | reminder_set
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )


# ── Email outreach (drip sequences via the client's own SMTP) ───────────────

class OrgEmailSettings(Base):
    """Per-org sending identity: the CLIENT's own SMTP (their domain/reputation/
    consent). Passwords are encrypted at rest (app.services.crypto). IMAP is
    optional — only needed to auto-stop a sequence when a lead replies."""
    __tablename__ = "org_email_settings"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    from_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    from_email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    smtp_host: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    smtp_port: Mapped[int] = mapped_column(Integer, default=587, nullable=False)
    smtp_user: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    smtp_password_enc: Mapped[str] = mapped_column(Text, default="", nullable=False)
    smtp_use_tls: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # IMAP (optional) for reply detection → auto-stop the sequence.
    imap_host: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    imap_port: Mapped[int] = mapped_column(Integer, default=993, nullable=False)
    imap_user: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    imap_password_enc: Mapped[str] = mapped_column(Text, default="", nullable=False)
    daily_limit: Mapped[int] = mapped_column(Integer, default=200, nullable=False)
    sent_today: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sent_today_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False,
    )


class EmailSequence(Base):
    """A drip campaign: ordered steps, leads enrolled, sent on a schedule."""
    __tablename__ = "email_sequences"
    __table_args__ = (Index("ix_email_sequences_org", "organization_id"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)  # active|paused|archived
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class SequenceStep(Base):
    """One email in a sequence. delay_days = wait before sending THIS step
    (from enrollment for step 0, from the previous step otherwise)."""
    __tablename__ = "sequence_steps"
    __table_args__ = (Index("ix_sequence_steps_seq_order", "sequence_id", "step_order"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sequence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("email_sequences.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    step_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    delay_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    subject: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class SequenceEnrollment(Base):
    """A lead's membership in a sequence + its send cursor."""
    __tablename__ = "sequence_enrollments"
    __table_args__ = (
        UniqueConstraint("sequence_id", "lead_id", name="uq_sequence_lead"),
        Index("ix_seq_enr_due", "status", "next_send_at"),
        Index("ix_seq_enr_org", "organization_id"),
        Index("ix_seq_enr_lead", "lead_id"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    sequence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("email_sequences.id", ondelete="CASCADE"), nullable=False
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    # active | completed | stopped | replied | unsubscribed | bounced | failed
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    current_step: Mapped[int] = mapped_column(Integer, default=0, nullable=False)  # next step index to send
    next_send_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    unsubscribe_token: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)
    stop_reason: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class OutreachMessage(Base):
    """Log of every outreach email actually sent (or attempted)."""
    __tablename__ = "outreach_messages"
    __table_args__ = (Index("ix_outreach_msg_enr", "enrollment_id"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    enrollment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sequence_enrollments.id", ondelete="SET NULL"), nullable=True
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True
    )
    step_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    to_email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    subject: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="sent", nullable=False)  # sent|failed
    error: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    # Open/click tracking (the pixel + link-redirect carry this token).
    track_token: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    opens_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    clicks_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True
    )


class OutreachReply(Base):
    """A captured inbound reply from a lead (via IMAP poll) — powers the inbox."""
    __tablename__ = "outreach_replies"
    __table_args__ = (
        Index("ix_outreach_replies_org_received", "organization_id", "received_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    enrollment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sequence_enrollments.id", ondelete="SET NULL"), nullable=True
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL"), nullable=True
    )
    from_email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    subject: Mapped[str] = mapped_column(String(300), default="", nullable=False)
    snippet: Mapped[str] = mapped_column(Text, default="", nullable=False)
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )


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
    # onupdate: any ORM update bumps the heartbeat (belt-and-braces alongside
    # the explicit bumps in the long-running collect/enrich tasks).
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

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
    # Mirrors the migration-created index so autogenerate doesn't drop it.
    __table_args__ = (Index("ix_action_logs_org_created_at", "organization_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class TrialGrant(Base):
    """Книга выданных триалов: солёный SHA-256 от канонической identity почты.

    Закрывает петлю «регистрация → 10 бесплатных лидов → удаление аккаунта
    (ФЗ-152) → регистрация на тот же ящик → снова 10 лидов»: запись создаётся
    при регистрации и ЖИВЁТ ДОЛЬШЕ аккаунта. Повторная регистрация той же
    identity получает орг с уже израсходованным триалом.

    ФЗ-152: хранится необратимый хэш с перцем (secret_key), НЕ email —
    после удаления ПД субъект по этой записи не идентифицируем, что
    допустимо для противодействия злоупотреблениям (аналог suppression-list).
    """

    __tablename__ = "trial_grants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email_identity_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # Хэш домена почты: доменный потолок триалов против catch-all ферм
    # (свой домен за $2 = безлимит «разных» ящиков в один inbox). Для
    # freemail-доменов потолок не действует (см. FREEMAIL_DOMAINS).
    domain_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class Company(Base):
    """Cross-organization registry of every company ever discovered.

    Acts as a warehouse: each search across any org upserts its candidates here
    keyed by `dedup_key` (lowercased domain, or `{normalized_name}|{city}`).
    Future searches reuse stored companies (cut 2GIS/API cost, improve recall),
    and lead cards can show rich company info (times seen, niches, sources).

    This table is NOT org-scoped — it's a shared, global registry. It holds no
    private workflow data (status/tags/notes live on Lead). Contact fields here
    come exclusively from public sources (2GIS API, Yandex Maps, rusprofile,
    web search), so cross-org sharing carries no 152-ФЗ subject-data concern
    beyond what each org already collected independently.
    """

    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # The identity key used for upsert dedupe: lowercased domain when present,
    # else f"{normalized_name}|{city_lower}". UNIQUE so ON CONFLICT can merge.
    dedup_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    domain: Mapped[str] = mapped_column(String(255), default="", nullable=False, index=True)
    # Lowercased, trimmed company name — used for ILIKE niche/name search.
    normalized_name: Mapped[str] = mapped_column(String(255), default="", nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    website: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    phone: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    address: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    city: Mapped[str] = mapped_column(String(120), default="", nullable=False, index=True)
    region: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    categories: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    # Distinct niche strings this company surfaced under (across all orgs).
    niches: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    # Distinct source strings: '2gis','yandex_maps','rusprofile','yandex_search','searxng','bing'.
    sources: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    twogis_firm_id: Mapped[str] = mapped_column(String(80), default="", nullable=False, index=True)
    rusprofile_id: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    inn: Mapped[str] = mapped_column(String(20), default="", nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    contacts_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    best_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    times_seen: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    raw_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Subscription(Base):
    __tablename__ = "subscriptions"
    # Mirrors the migration-created index so autogenerate doesn't drop it.
    __table_args__ = (Index("ix_subscriptions_org_created_at", "organization_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=False)
    plan_id: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    provider_subscription_id: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    # ── Автопродление (ЮKassa recurring) ──────────────────────────────────
    # Согласие на автосписание (чекбокс в checkout; выключается в настройках).
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Сохранённый способ оплаты ЮKassa (payment_method.id из первого платежа,
    # когда payment_method.saved == true). Пустая строка = карты нет.
    payment_method_id: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    # Счётчик неудачных попыток автосписания (ретраим до 3, потом сдаёмся —
    # подписку добьёт ночной downgrade_expired_subscriptions).
    renew_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Когда отправлено письмо «подписка скоро закончится» (для тех, кто без
    # автопродления) — чтобы не спамить его каждую ночь.
    expiry_reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
