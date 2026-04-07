"""Add prompt field to projects

Revision ID: d8a3f1b7c9e5
Revises: b2e5f8a9c1d3
Create Date: 2026-04-07
"""
from alembic import op
import sqlalchemy as sa

revision = "d8a3f1b7c9e5"
down_revision = "b2e5f8a9c1d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("prompt", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "prompt")
