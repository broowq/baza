"""add_lead_email_status

Revision ID: b3c9e1a5d72f
Revises: a7b8c9d0e1f2
Create Date: 2026-04-24 20:30:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b3c9e1a5d72f"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add leads.email_status column (default empty, indexed)."""
    bind = op.get_bind()
    # Idempotent: only add if missing.
    col_exists = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='leads' AND column_name='email_status'"
        )
    ).first()
    if not col_exists:
        op.add_column(
            "leads",
            sa.Column(
                "email_status",
                sa.String(length=20),
                nullable=False,
                server_default="",
            ),
        )
        op.create_index(
            "ix_leads_email_status",
            "leads",
            ["email_status"],
        )


def downgrade() -> None:
    op.drop_index("ix_leads_email_status", table_name="leads")
    op.drop_column("leads", "email_status")
