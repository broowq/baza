"""Add free plan type

Revision ID: e5f2a9c7d1b3
Revises: d8a3f1b7c9e5
Create Date: 2026-04-10
"""
from alembic import op

revision = "e5f2a9c7d1b3"
down_revision = "d8a3f1b7c9e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add 'free' to the plantype enum
    op.execute("ALTER TYPE plantype ADD VALUE IF NOT EXISTS 'free' BEFORE 'starter'")


def downgrade() -> None:
    # Cannot remove enum values in PostgreSQL without recreating the type
    pass
