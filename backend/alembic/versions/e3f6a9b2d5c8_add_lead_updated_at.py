"""add leads.updated_at for activity-based GDPR retention

purge_old_leads (152-ФЗ ст.5 ч.7) must delete leads by *inactivity*, not by
creation date. Lead had no updated_at, so the purge silently used created_at —
deleting leads that were still being worked. This adds updated_at (bumped via
ORM onupdate on every write) and backfills existing rows to created_at.

Revision ID: e3f6a9b2d5c8
Revises: d2e5f8a1c4b7
Create Date: 2026-06-03 13:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e3f6a9b2d5c8"
down_revision: Union[str, Sequence[str], None] = "d2e5f8a1c4b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("leads")}
    if "updated_at" not in cols:
        # Add nullable first, backfill from created_at, then enforce NOT NULL.
        op.add_column("leads", sa.Column("updated_at", sa.DateTime(), nullable=True))
        op.execute("UPDATE leads SET updated_at = created_at WHERE updated_at IS NULL")
        op.alter_column(
            "leads",
            "updated_at",
            existing_type=sa.DateTime(),
            nullable=False,
            server_default=sa.text("now()"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("leads")}
    if "updated_at" in cols:
        op.drop_column("leads", "updated_at")
