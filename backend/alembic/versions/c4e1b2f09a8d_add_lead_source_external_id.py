"""add_lead_source_external_id

Revision ID: c4e1b2f09a8d
Revises: b3c9e1a5d72f
Create Date: 2026-04-24 20:45:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c4e1b2f09a8d"
down_revision: Union[str, Sequence[str], None] = "b3c9e1a5d72f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _col_exists(bind: sa.Connection, column: str) -> bool:
    return bool(
        bind.execute(
            sa.text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='leads' AND column_name=:col"
            ),
            {"col": column},
        ).first()
    )


def upgrade() -> None:
    bind = op.get_bind()
    if not _col_exists(bind, "source"):
        op.add_column(
            "leads",
            sa.Column("source", sa.String(length=24), nullable=False, server_default=""),
        )
        op.create_index("ix_leads_source", "leads", ["source"])
    if not _col_exists(bind, "external_id"):
        op.add_column(
            "leads",
            sa.Column("external_id", sa.String(length=80), nullable=False, server_default=""),
        )


def downgrade() -> None:
    op.drop_column("leads", "external_id")
    op.drop_index("ix_leads_source", table_name="leads")
    op.drop_column("leads", "source")
