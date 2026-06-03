"""add projects.search_query

Caches the LLM-optimized search niche (enhance_prompt's search_queries_niche) on
the project so dosed collection reuses it instead of paying for an LLM
prompt-enhance on every dose. Reset to "" when the project prompt changes.

Revision ID: d2e5f8a1c4b7
Revises: c1d4e7f2a9b3
Create Date: 2026-06-03 12:30:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d2e5f8a1c4b7"
down_revision: Union[str, Sequence[str], None] = "c1d4e7f2a9b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("projects")}
    if "search_query" not in cols:
        op.add_column(
            "projects",
            sa.Column("search_query", sa.String(length=300), nullable=False, server_default=""),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("projects")}
    if "search_query" in cols:
        op.drop_column("projects", "search_query")
