"""add_org_leads_retention_days

Adds `leads_retention_days` column to `organizations` for 152-ФЗ ст. 5 ч. 7
compliance. Срок хранения ПД — обязательное свойство обработки. Лиды,
не получавшие изменения дольше этого срока, удаляются фоновым cron-таском
(periodic.purge_old_leads).

Default 730 (2 года) — мирится с требованием НК РФ ст. 23 о хранении
бухгалтерских документов.

Revision ID: f3b8c1d9e2a4
Revises: e9c4a2d8f5b1
Create Date: 2026-05-14 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f3b8c1d9e2a4"
down_revision: Union[str, Sequence[str], None] = "e9c4a2d8f5b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "organizations" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("organizations")}
    if "leads_retention_days" not in columns:
        op.add_column(
            "organizations",
            sa.Column(
                "leads_retention_days",
                sa.Integer(),
                nullable=False,
                server_default="730",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "organizations" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("organizations")}
    if "leads_retention_days" in columns:
        op.drop_column("organizations", "leads_retention_days")
