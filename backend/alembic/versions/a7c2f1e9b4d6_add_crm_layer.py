"""add CRM layer: pipeline stages, assignment, deal fields, tasks, activities

- extend leadstatus enum with 'proposal' and 'won' (additive, safe)
- leads: assigned_to_user_id, deal_value, expected_close_at
- new tables: lead_tasks, lead_activities

Revision ID: a7c2f1e9b4d6
Revises: f4a7b0c3e6d9
Create Date: 2026-06-16 09:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "a7c2f1e9b4d6"
down_revision: Union[str, Sequence[str], None] = "f4a7b0c3e6d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 1. Extend the native leadstatus enum (additive; ADD VALUE must run outside
    #    a transaction block on PG, hence autocommit_block).
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE leadstatus ADD VALUE IF NOT EXISTS 'proposal'")
        op.execute("ALTER TYPE leadstatus ADD VALUE IF NOT EXISTS 'won'")

    # 2. New columns on leads.
    lead_cols = {c["name"] for c in inspector.get_columns("leads")}
    if "assigned_to_user_id" not in lead_cols:
        op.add_column("leads", sa.Column("assigned_to_user_id", UUID(as_uuid=True), nullable=True))
        op.create_foreign_key(
            "fk_leads_assigned_to_user", "leads", "users",
            ["assigned_to_user_id"], ["id"], ondelete="SET NULL",
        )
        op.create_index("ix_leads_assigned_to_user_id", "leads", ["assigned_to_user_id"])
    if "deal_value" not in lead_cols:
        op.add_column("leads", sa.Column("deal_value", sa.Integer(), nullable=False, server_default="0"))
    if "expected_close_at" not in lead_cols:
        op.add_column("leads", sa.Column("expected_close_at", sa.DateTime(), nullable=True))

    tables = set(inspector.get_table_names())

    # 3. lead_tasks
    if "lead_tasks" not in tables:
        op.create_table(
            "lead_tasks",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("organization_id", UUID(as_uuid=True),
                      sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("lead_id", UUID(as_uuid=True),
                      sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
            sa.Column("assigned_to_user_id", UUID(as_uuid=True),
                      sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_by_user_id", UUID(as_uuid=True),
                      sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("title", sa.String(length=300), nullable=False),
            sa.Column("due_at", sa.DateTime(), nullable=True),
            sa.Column("done", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("done_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_lead_tasks_organization_id", "lead_tasks", ["organization_id"])
        op.create_index("ix_lead_tasks_org_done_due", "lead_tasks", ["organization_id", "done", "due_at"])
        op.create_index("ix_lead_tasks_assignee_done", "lead_tasks", ["assigned_to_user_id", "done"])
        op.create_index("ix_lead_tasks_lead", "lead_tasks", ["lead_id"])

    # 4. lead_activities
    if "lead_activities" not in tables:
        op.create_table(
            "lead_activities",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("organization_id", UUID(as_uuid=True),
                      sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("lead_id", UUID(as_uuid=True),
                      sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", UUID(as_uuid=True),
                      sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("user_name", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("kind", sa.String(length=32), nullable=False),
            sa.Column("text", sa.Text(), nullable=False, server_default=""),
            sa.Column("meta", JSONB(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_lead_activities_organization_id", "lead_activities", ["organization_id"])
        op.create_index("ix_lead_activities_lead_created", "lead_activities", ["lead_id", "created_at"])


def downgrade() -> None:
    op.drop_table("lead_activities")
    op.drop_table("lead_tasks")
    op.drop_index("ix_leads_assigned_to_user_id", table_name="leads")
    op.drop_constraint("fk_leads_assigned_to_user", "leads", type_="foreignkey")
    op.drop_column("leads", "expected_close_at")
    op.drop_column("leads", "deal_value")
    op.drop_column("leads", "assigned_to_user_id")
    # Note: enum values are not removed (PG can't DROP enum values).
