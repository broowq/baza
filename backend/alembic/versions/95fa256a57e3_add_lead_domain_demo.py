"""add_lead_domain_demo

Revision ID: 95fa256a57e3
Revises: 
Create Date: 2026-03-04 03:45:12.207832

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '95fa256a57e3'
down_revision: Union[str, Sequence[str], None] = "2b4f6d1a1c10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "leads" in tables:
        columns = {column["name"] for column in inspector.get_columns("leads")}
        if "domain" not in columns:
            op.add_column("leads", sa.Column("domain", sa.String(length=255), nullable=False, server_default=""))
        if "demo" not in columns:
            op.add_column("leads", sa.Column("demo", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "leads" in tables:
        columns = {column["name"] for column in inspector.get_columns("leads")}
        if "demo" in columns:
            op.drop_column("leads", "demo")
        if "domain" in columns:
            op.drop_column("leads", "domain")
