"""add_lead_contact_columns

Revision ID: c2d9a7b31fd4
Revises: 95fa256a57e3
Create Date: 2026-03-04 12:10:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c2d9a7b31fd4"
down_revision: Union[str, Sequence[str], None] = "95fa256a57e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "leads" not in tables:
        return
    columns = {column["name"] for column in inspector.get_columns("leads")}
    if "email" not in columns:
        op.add_column("leads", sa.Column("email", sa.String(length=255), nullable=False, server_default=""))
    if "phone" not in columns:
        op.add_column("leads", sa.Column("phone", sa.String(length=80), nullable=False, server_default=""))
    if "address" not in columns:
        op.add_column("leads", sa.Column("address", sa.String(length=300), nullable=False, server_default=""))
    if "contacts_json" not in columns:
        op.add_column(
            "leads",
            sa.Column("contacts_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        )
        op.execute("UPDATE leads SET contacts_json = contacts")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "leads" not in tables:
        return
    columns = {column["name"] for column in inspector.get_columns("leads")}
    if "contacts_json" in columns:
        op.drop_column("leads", "contacts_json")
    if "address" in columns:
        op.drop_column("leads", "address")
    if "phone" in columns:
        op.drop_column("leads", "phone")
    if "email" in columns:
        op.drop_column("leads", "email")
