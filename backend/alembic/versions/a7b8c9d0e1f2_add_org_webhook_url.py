"""add_org_lead_webhook_url

Revision ID: a7b8c9d0e1f2
Revises: f1a2b3c4d5e6
Create Date: 2026-04-20 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "organizations" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("organizations")}
    if "lead_webhook_url" not in columns:
        op.add_column(
            "organizations",
            sa.Column("lead_webhook_url", sa.String(length=500), nullable=False, server_default=""),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "organizations" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("organizations")}
    if "lead_webhook_url" in columns:
        op.drop_column("organizations", "lead_webhook_url")
