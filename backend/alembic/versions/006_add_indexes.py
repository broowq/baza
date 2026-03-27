"""add_indexes_and_soft_delete

Revision ID: 006_add_indexes
Revises: a1d4e9c3f8b2
Create Date: 2026-03-19 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "006_add_indexes"
down_revision: Union[str, Sequence[str], None] = "a1d4e9c3f8b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # --- Add deleted_at column to projects ---
    if "projects" in tables:
        columns = {col["name"] for col in inspector.get_columns("projects")}
        if "deleted_at" not in columns:
            op.add_column("projects", sa.Column("deleted_at", sa.DateTime(), nullable=True))

    # --- Add indexes on leads ---
    if "leads" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("leads")}

        if "ix_leads_project_id_status" not in indexes:
            op.create_index("ix_leads_project_id_status", "leads", ["project_id", "status"], unique=False)

        if "ix_leads_organization_id_created_at" not in indexes:
            op.create_index("ix_leads_organization_id_created_at", "leads", ["organization_id", "created_at"], unique=False)

        if "ix_leads_domain" not in indexes:
            op.create_index("ix_leads_domain", "leads", ["domain"], unique=False)

        if "ix_leads_website" not in indexes:
            op.create_index("ix_leads_website", "leads", ["website"], unique=False)

    # --- Add index on organizations(name) ---
    if "organizations" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("organizations")}
        if "ix_organizations_name" not in indexes:
            op.create_index("ix_organizations_name", "organizations", ["name"], unique=False)

    # --- Add index on users(email) if not already present ---
    if "users" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("users")}
        if "ix_users_email" not in indexes:
            op.create_index("ix_users_email", "users", ["email"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "users" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("users")}
        if "ix_users_email" in indexes:
            op.drop_index("ix_users_email", table_name="users")

    if "organizations" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("organizations")}
        if "ix_organizations_name" in indexes:
            op.drop_index("ix_organizations_name", table_name="organizations")

    if "leads" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("leads")}
        if "ix_leads_website" in indexes:
            op.drop_index("ix_leads_website", table_name="leads")
        if "ix_leads_domain" in indexes:
            op.drop_index("ix_leads_domain", table_name="leads")
        if "ix_leads_organization_id_created_at" in indexes:
            op.drop_index("ix_leads_organization_id_created_at", table_name="leads")
        if "ix_leads_project_id_status" in indexes:
            op.drop_index("ix_leads_project_id_status", table_name="leads")

    if "projects" in tables:
        columns = {col["name"] for col in inspector.get_columns("projects")}
        if "deleted_at" in columns:
            op.drop_column("projects", "deleted_at")
