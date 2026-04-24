"""add_project_okved_codes

Revision ID: d5f3a1c7b896
Revises: c4e1b2f09a8d
Create Date: 2026-04-24 21:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "d5f3a1c7b896"
down_revision: Union[str, Sequence[str], None] = "c4e1b2f09a8d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    col_exists = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name='projects' AND column_name='okved_codes'"
        )
    ).first()
    if not col_exists:
        op.add_column(
            "projects",
            sa.Column(
                "okved_codes",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
        )


def downgrade() -> None:
    op.drop_column("projects", "okved_codes")
