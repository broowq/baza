"""add email outreach: per-org SMTP settings, sequences, steps, enrollments, log

+ leads.email_opt_out suppression flag.

Revision ID: b8e3d1f6a2c4
Revises: a7c2f1e9b4d6
Create Date: 2026-06-19 19:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "b8e3d1f6a2c4"
down_revision: Union[str, Sequence[str], None] = "a7c2f1e9b4d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "email_opt_out" not in {c["name"] for c in insp.get_columns("leads")}:
        op.add_column("leads", sa.Column("email_opt_out", sa.Boolean(), nullable=False, server_default=sa.false()))

    if "org_email_settings" not in tables:
        op.create_table(
            "org_email_settings",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("organization_id", UUID(as_uuid=True),
                      sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, unique=True),
            sa.Column("from_name", sa.String(120), nullable=False, server_default=""),
            sa.Column("from_email", sa.String(255), nullable=False, server_default=""),
            sa.Column("smtp_host", sa.String(255), nullable=False, server_default=""),
            sa.Column("smtp_port", sa.Integer(), nullable=False, server_default="587"),
            sa.Column("smtp_user", sa.String(255), nullable=False, server_default=""),
            sa.Column("smtp_password_enc", sa.Text(), nullable=False, server_default=""),
            sa.Column("smtp_use_tls", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("imap_host", sa.String(255), nullable=False, server_default=""),
            sa.Column("imap_port", sa.Integer(), nullable=False, server_default="993"),
            sa.Column("imap_user", sa.String(255), nullable=False, server_default=""),
            sa.Column("imap_password_enc", sa.Text(), nullable=False, server_default=""),
            sa.Column("daily_limit", sa.Integer(), nullable=False, server_default="200"),
            sa.Column("sent_today", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("sent_today_date", sa.DateTime(), nullable=True),
            sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )

    if "email_sequences" not in tables:
        op.create_table(
            "email_sequences",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("organization_id", UUID(as_uuid=True),
                      sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", UUID(as_uuid=True),
                      sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=True),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="active"),
            sa.Column("created_by_user_id", UUID(as_uuid=True),
                      sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_email_sequences_org", "email_sequences", ["organization_id"])

    if "sequence_steps" not in tables:
        op.create_table(
            "sequence_steps",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("sequence_id", UUID(as_uuid=True),
                      sa.ForeignKey("email_sequences.id", ondelete="CASCADE"), nullable=False),
            sa.Column("organization_id", UUID(as_uuid=True),
                      sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("step_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("delay_days", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("subject", sa.String(300), nullable=False, server_default=""),
            sa.Column("body", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_sequence_steps_seq_order", "sequence_steps", ["sequence_id", "step_order"])

    if "sequence_enrollments" not in tables:
        op.create_table(
            "sequence_enrollments",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("organization_id", UUID(as_uuid=True),
                      sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("sequence_id", UUID(as_uuid=True),
                      sa.ForeignKey("email_sequences.id", ondelete="CASCADE"), nullable=False),
            sa.Column("lead_id", UUID(as_uuid=True),
                      sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="active"),
            sa.Column("current_step", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("next_send_at", sa.DateTime(), nullable=True),
            sa.Column("last_sent_at", sa.DateTime(), nullable=True),
            sa.Column("unsubscribe_token", sa.String(64), nullable=False, server_default=""),
            sa.Column("stop_reason", sa.String(64), nullable=False, server_default=""),
            sa.Column("enrolled_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("sequence_id", "lead_id", name="uq_sequence_lead"),
        )
        op.create_index("ix_seq_enr_due", "sequence_enrollments", ["status", "next_send_at"])
        op.create_index("ix_seq_enr_org", "sequence_enrollments", ["organization_id"])
        op.create_index("ix_seq_enr_lead", "sequence_enrollments", ["lead_id"])
        op.create_index("ix_sequence_enrollments_unsubscribe_token", "sequence_enrollments", ["unsubscribe_token"])

    if "outreach_messages" not in tables:
        op.create_table(
            "outreach_messages",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("organization_id", UUID(as_uuid=True),
                      sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("enrollment_id", UUID(as_uuid=True),
                      sa.ForeignKey("sequence_enrollments.id", ondelete="SET NULL"), nullable=True),
            sa.Column("lead_id", UUID(as_uuid=True),
                      sa.ForeignKey("leads.id", ondelete="SET NULL"), nullable=True),
            sa.Column("step_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("to_email", sa.String(255), nullable=False, server_default=""),
            sa.Column("subject", sa.String(300), nullable=False, server_default=""),
            sa.Column("status", sa.String(16), nullable=False, server_default="sent"),
            sa.Column("error", sa.String(300), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_outreach_msg_enr", "outreach_messages", ["enrollment_id"])
        op.create_index("ix_outreach_messages_created_at", "outreach_messages", ["created_at"])


def downgrade() -> None:
    op.drop_table("outreach_messages")
    op.drop_table("sequence_enrollments")
    op.drop_table("sequence_steps")
    op.drop_table("email_sequences")
    op.drop_table("org_email_settings")
    op.drop_column("leads", "email_opt_out")
