"""add outreach open/click tracking + replies inbox

outreach_messages: track_token, opened_at, opens_count, clicked_at, clicks_count.
New table outreach_replies.

Revision ID: c5f9a2e7b1d8
Revises: b8e3d1f6a2c4
Create Date: 2026-06-19 20:30:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "c5f9a2e7b1d8"
down_revision: Union[str, Sequence[str], None] = "b8e3d1f6a2c4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("outreach_messages")}
    if "track_token" not in cols:
        op.add_column("outreach_messages", sa.Column("track_token", sa.String(64), nullable=False, server_default=""))
        op.create_index("ix_outreach_messages_track_token", "outreach_messages", ["track_token"])
    if "opened_at" not in cols:
        op.add_column("outreach_messages", sa.Column("opened_at", sa.DateTime(), nullable=True))
    if "opens_count" not in cols:
        op.add_column("outreach_messages", sa.Column("opens_count", sa.Integer(), nullable=False, server_default="0"))
    if "clicked_at" not in cols:
        op.add_column("outreach_messages", sa.Column("clicked_at", sa.DateTime(), nullable=True))
    if "clicks_count" not in cols:
        op.add_column("outreach_messages", sa.Column("clicks_count", sa.Integer(), nullable=False, server_default="0"))

    if "outreach_replies" not in set(insp.get_table_names()):
        op.create_table(
            "outreach_replies",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("organization_id", UUID(as_uuid=True),
                      sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("enrollment_id", UUID(as_uuid=True),
                      sa.ForeignKey("sequence_enrollments.id", ondelete="SET NULL"), nullable=True),
            sa.Column("lead_id", UUID(as_uuid=True),
                      sa.ForeignKey("leads.id", ondelete="SET NULL"), nullable=True),
            sa.Column("from_email", sa.String(255), nullable=False, server_default=""),
            sa.Column("subject", sa.String(300), nullable=False, server_default=""),
            sa.Column("snippet", sa.Text(), nullable=False, server_default=""),
            sa.Column("received_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_outreach_replies_org_received", "outreach_replies", ["organization_id", "received_at"])


def downgrade() -> None:
    op.drop_table("outreach_replies")
    op.drop_index("ix_outreach_messages_track_token", table_name="outreach_messages")
    op.drop_column("outreach_messages", "clicks_count")
    op.drop_column("outreach_messages", "clicked_at")
    op.drop_column("outreach_messages", "opens_count")
    op.drop_column("outreach_messages", "opened_at")
    op.drop_column("outreach_messages", "track_token")
