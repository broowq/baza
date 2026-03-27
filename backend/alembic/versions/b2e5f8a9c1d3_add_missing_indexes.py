"""add_missing_indexes

Revision ID: b2e5f8a9c1d3
Revises: 006_add_indexes
Create Date: 2026-03-24 12:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2e5f8a9c1d3"
down_revision: Union[str, Sequence[str], None] = "006_add_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # --- memberships indexes ---
    if "memberships" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("memberships")}

        if "ix_memberships_organization_id" not in indexes:
            op.create_index("ix_memberships_organization_id", "memberships", ["organization_id"], unique=False)

        if "ix_memberships_user_id" not in indexes:
            op.create_index("ix_memberships_user_id", "memberships", ["user_id"], unique=False)

    # --- leads indexes ---
    if "leads" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("leads")}

        if "ix_leads_organization_id" not in indexes:
            op.create_index("ix_leads_organization_id", "leads", ["organization_id"], unique=False)

        if "ix_leads_project_id" not in indexes:
            op.create_index("ix_leads_project_id", "leads", ["project_id"], unique=False)

        if "ix_leads_status" not in indexes:
            op.create_index("ix_leads_status", "leads", ["status"], unique=False)

        if "ix_leads_score" not in indexes:
            op.create_index("ix_leads_score", "leads", ["score"], unique=False)

    # --- collection_jobs indexes ---
    if "collection_jobs" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("collection_jobs")}

        if "ix_collection_jobs_organization_id" not in indexes:
            op.create_index("ix_collection_jobs_organization_id", "collection_jobs", ["organization_id"], unique=False)

        if "ix_collection_jobs_project_id" not in indexes:
            op.create_index("ix_collection_jobs_project_id", "collection_jobs", ["project_id"], unique=False)

        if "ix_collection_jobs_status" not in indexes:
            op.create_index("ix_collection_jobs_status", "collection_jobs", ["status"], unique=False)

    # --- projects indexes ---
    if "projects" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("projects")}

        if "ix_projects_organization_id" not in indexes:
            op.create_index("ix_projects_organization_id", "projects", ["organization_id"], unique=False)

    # --- action_logs indexes ---
    if "action_logs" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("action_logs")}

        if "ix_action_logs_user_id" not in indexes:
            op.create_index("ix_action_logs_user_id", "action_logs", ["user_id"], unique=False)

        if "ix_action_logs_organization_id" not in indexes:
            op.create_index("ix_action_logs_organization_id", "action_logs", ["organization_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "action_logs" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("action_logs")}
        if "ix_action_logs_organization_id" in indexes:
            op.drop_index("ix_action_logs_organization_id", table_name="action_logs")
        if "ix_action_logs_user_id" in indexes:
            op.drop_index("ix_action_logs_user_id", table_name="action_logs")

    if "projects" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("projects")}
        if "ix_projects_organization_id" in indexes:
            op.drop_index("ix_projects_organization_id", table_name="projects")

    if "collection_jobs" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("collection_jobs")}
        if "ix_collection_jobs_status" in indexes:
            op.drop_index("ix_collection_jobs_status", table_name="collection_jobs")
        if "ix_collection_jobs_project_id" in indexes:
            op.drop_index("ix_collection_jobs_project_id", table_name="collection_jobs")
        if "ix_collection_jobs_organization_id" in indexes:
            op.drop_index("ix_collection_jobs_organization_id", table_name="collection_jobs")

    if "leads" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("leads")}
        if "ix_leads_score" in indexes:
            op.drop_index("ix_leads_score", table_name="leads")
        if "ix_leads_status" in indexes:
            op.drop_index("ix_leads_status", table_name="leads")
        if "ix_leads_project_id" in indexes:
            op.drop_index("ix_leads_project_id", table_name="leads")
        if "ix_leads_organization_id" in indexes:
            op.drop_index("ix_leads_organization_id", table_name="leads")

    if "memberships" in tables:
        indexes = {idx["name"] for idx in inspector.get_indexes("memberships")}
        if "ix_memberships_user_id" in indexes:
            op.drop_index("ix_memberships_user_id", table_name="memberships")
        if "ix_memberships_organization_id" in indexes:
            op.drop_index("ix_memberships_organization_id", table_name="memberships")
