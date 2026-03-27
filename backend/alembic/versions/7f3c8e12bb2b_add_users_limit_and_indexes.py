"""add_users_limit_and_indexes

Revision ID: 7f3c8e12bb2b
Revises: c2d9a7b31fd4
Create Date: 2026-03-04 14:35:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7f3c8e12bb2b"
down_revision: Union[str, Sequence[str], None] = "c2d9a7b31fd4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "organizations" in tables:
        columns = {column["name"] for column in inspector.get_columns("organizations")}
        if "users_limit" not in columns:
            op.add_column("organizations", sa.Column("users_limit", sa.Integer(), nullable=False, server_default="3"))
    if "leads" in tables:
        indexes = {index["name"] for index in inspector.get_indexes("leads")}
        if "ix_leads_project_score" not in indexes:
            op.create_index("ix_leads_project_score", "leads", ["project_id", "score"], unique=False)
        if "ix_leads_project_domain_company" not in indexes:
            op.create_index("ix_leads_project_domain_company", "leads", ["project_id", "domain", "company"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "leads" in tables:
        indexes = {index["name"] for index in inspector.get_indexes("leads")}
        if "ix_leads_project_domain_company" in indexes:
            op.drop_index("ix_leads_project_domain_company", table_name="leads")
        if "ix_leads_project_score" in indexes:
            op.drop_index("ix_leads_project_score", table_name="leads")
    if "organizations" in tables:
        columns = {column["name"] for column in inspector.get_columns("organizations")}
        if "users_limit" in columns:
            op.drop_column("organizations", "users_limit")
