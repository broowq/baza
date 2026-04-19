"""add_lead_workflow_fields

Revision ID: f1a2b3c4d5e6
Revises: e5f2a9c7d1b3
Create Date: 2026-04-19 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e5f2a9c7d1b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "leads" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("leads")}
    if "tags" not in columns:
        op.add_column(
            "leads",
            sa.Column(
                "tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
        )
    if "last_contacted_at" not in columns:
        op.add_column("leads", sa.Column("last_contacted_at", sa.DateTime(), nullable=True))
        op.create_index("ix_leads_last_contacted_at", "leads", ["last_contacted_at"])
    if "reminder_at" not in columns:
        op.add_column("leads", sa.Column("reminder_at", sa.DateTime(), nullable=True))
        op.create_index("ix_leads_reminder_at", "leads", ["reminder_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "leads" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("leads")}
    if "reminder_at" in columns:
        op.drop_index("ix_leads_reminder_at", table_name="leads")
        op.drop_column("leads", "reminder_at")
    if "last_contacted_at" in columns:
        op.drop_index("ix_leads_last_contacted_at", table_name="leads")
        op.drop_column("leads", "last_contacted_at")
    if "tags" in columns:
        op.drop_column("leads", "tags")
