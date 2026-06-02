"""add projects.leads_exhausted_at

Adds a nullable timestamp to `projects`. It is set when a paid live seed found
0 new companies (sources exhausted for the project's niche+geo relative to what
is already collected), and gates live re-seeding for a cooldown window so repeat
dosed collections don't burn external API calls returning the same set.

Revision ID: c1d4e7f2a9b3
Revises: a8f2c4d6e1b9
Create Date: 2026-06-03 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c1d4e7f2a9b3"
down_revision: Union[str, Sequence[str], None] = "a8f2c4d6e1b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("projects")}
    if "leads_exhausted_at" not in cols:
        op.add_column(
            "projects",
            sa.Column("leads_exhausted_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("projects")}
    if "leads_exhausted_at" in cols:
        op.drop_column("projects", "leads_exhausted_at")
