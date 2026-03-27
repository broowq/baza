"""security_audit_subscription

Revision ID: a1d4e9c3f8b2
Revises: 7f3c8e12bb2b
Create Date: 2026-03-05 03:40:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1d4e9c3f8b2"
down_revision: Union[str, Sequence[str], None] = "7f3c8e12bb2b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "users" in tables:
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        if "email_verified" not in user_columns:
            op.add_column("users", sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.false()))

    if "invites" in tables:
        invite_columns = {column["name"] for column in inspector.get_columns("invites")}
        if "expires_at" not in invite_columns:
            op.add_column("invites", sa.Column("expires_at", sa.DateTime(), nullable=True))
            op.execute("UPDATE invites SET expires_at = created_at + interval '7 day'")
            op.alter_column("invites", "expires_at", nullable=False)

    if "action_logs" not in tables:
        op.create_table(
            "action_logs",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("action", sa.String(length=120), nullable=False),
            sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_action_logs_org_created_at", "action_logs", ["organization_id", "created_at"], unique=False)

    if "subscriptions" not in tables:
        op.create_table(
            "subscriptions",
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("plan_id", sa.String(length=32), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("current_period_start", sa.DateTime(), nullable=True),
            sa.Column("current_period_end", sa.DateTime(), nullable=True),
            sa.Column("provider_subscription_id", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_subscriptions_org_created_at", "subscriptions", ["organization_id", "created_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "subscriptions" in tables:
        indexes = {index["name"] for index in inspector.get_indexes("subscriptions")}
        if "ix_subscriptions_org_created_at" in indexes:
            op.drop_index("ix_subscriptions_org_created_at", table_name="subscriptions")
        op.drop_table("subscriptions")

    if "action_logs" in tables:
        indexes = {index["name"] for index in inspector.get_indexes("action_logs")}
        if "ix_action_logs_org_created_at" in indexes:
            op.drop_index("ix_action_logs_org_created_at", table_name="action_logs")
        op.drop_table("action_logs")

    if "invites" in tables:
        invite_columns = {column["name"] for column in inspector.get_columns("invites")}
        if "expires_at" in invite_columns:
            op.drop_column("invites", "expires_at")

    if "users" in tables:
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        if "email_verified" in user_columns:
            op.drop_column("users", "email_verified")
