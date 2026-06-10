"""add lead_call_notes

Call journal on a lead: who called (current user, name snapshotted), when,
and a free-form comment. Rows cascade with the lead/org; user deletion only
nulls user_id so the history keeps the name.

Revision ID: f4a7b0c3e6d9
Revises: e3f6a9b2d5c8
Create Date: 2026-06-10 23:40:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "f4a7b0c3e6d9"
down_revision: Union[str, Sequence[str], None] = "e3f6a9b2d5c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "lead_call_notes" in inspector.get_table_names():
        return
    op.create_table(
        "lead_call_notes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "lead_id",
            UUID(as_uuid=True),
            sa.ForeignKey("leads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("user_name", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("comment", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_lead_call_notes_organization_id", "lead_call_notes", ["organization_id"])
    op.create_index("ix_lead_call_notes_lead_id", "lead_call_notes", ["lead_id"])
    op.create_index("ix_lead_call_notes_created_at", "lead_call_notes", ["created_at"])


def downgrade() -> None:
    op.drop_table("lead_call_notes")
