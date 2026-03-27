"""initial_schema

Revision ID: 2b4f6d1a1c10
Revises:
Create Date: 2026-03-04 04:10:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "2b4f6d1a1c10"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    plan_type = postgresql.ENUM("starter", "pro", "team", name="plantype", create_type=False)
    job_status = postgresql.ENUM("queued", "running", "done", "failed", name="jobstatus", create_type=False)
    lead_status = postgresql.ENUM("new", "contacted", "qualified", "rejected", name="leadstatus", create_type=False)
    plan_type.create(bind, checkfirst=True)
    job_status.create(bind, checkfirst=True)
    lead_status.create(bind, checkfirst=True)

    if "organizations" not in tables:
        op.create_table(
            "organizations",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("plan", plan_type, nullable=False),
            sa.Column("leads_used_current_month", sa.Integer(), nullable=False),
            sa.Column("leads_limit_per_month", sa.Integer(), nullable=False),
            sa.Column("projects_limit", sa.Integer(), nullable=False),
            sa.Column("can_invite_members", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name"),
        )

    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("full_name", sa.String(length=120), nullable=False),
            sa.Column("hashed_password", sa.String(length=255), nullable=False),
            sa.Column("is_admin", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("email"),
        )
        op.create_index("ix_users_email", "users", ["email"], unique=False)

    if "memberships" not in tables:
        op.create_table(
            "memberships",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("role", sa.String(length=32), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("organization_id", "user_id", name="uq_org_user"),
        )

    if "projects" not in tables:
        op.create_table(
            "projects",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("name", sa.String(length=140), nullable=False),
            sa.Column("niche", sa.String(length=120), nullable=False),
            sa.Column("geography", sa.String(length=120), nullable=False),
            sa.Column("segments", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("cron_schedule", sa.String(length=120), nullable=False),
            sa.Column("auto_collection_enabled", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if "leads" not in tables:
        op.create_table(
            "leads",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("company", sa.String(length=180), nullable=False),
            sa.Column("city", sa.String(length=120), nullable=False),
            sa.Column("website", sa.String(length=300), nullable=False),
            sa.Column("domain", sa.String(length=255), nullable=False),
            sa.Column("contacts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
            sa.Column("score", sa.Integer(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=False),
            sa.Column("status", lead_status, nullable=False),
            sa.Column("source_url", sa.String(length=400), nullable=False),
            sa.Column("enriched", sa.Boolean(), nullable=False),
            sa.Column("demo", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("project_id", "website", name="uq_project_website"),
        )

    if "collection_jobs" not in tables:
        op.create_table(
            "collection_jobs",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("status", job_status, nullable=False),
            sa.Column("kind", sa.String(length=32), nullable=False),
            sa.Column("requested_limit", sa.Integer(), nullable=False),
            sa.Column("found_count", sa.Integer(), nullable=False),
            sa.Column("added_count", sa.Integer(), nullable=False),
            sa.Column("enriched_count", sa.Integer(), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if "invites" not in tables:
        op.create_table(
            "invites",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("role", sa.String(length=32), nullable=False),
            sa.Column("token", sa.String(length=120), nullable=False),
            sa.Column("accepted", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("token"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "invites" in tables:
        op.drop_table("invites")
    if "collection_jobs" in tables:
        op.drop_table("collection_jobs")
    if "leads" in tables:
        op.drop_table("leads")
    if "projects" in tables:
        op.drop_table("projects")
    if "memberships" in tables:
        op.drop_table("memberships")
    if "users" in tables:
        op.drop_table("users")
    if "organizations" in tables:
        op.drop_table("organizations")
