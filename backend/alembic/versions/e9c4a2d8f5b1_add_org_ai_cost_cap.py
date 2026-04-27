"""add_org_ai_cost_cap

Adds two BIGINT columns to `organizations` for the per-org AI/LLM monthly
spend cap. Stored in kopecks (₽ × 100) so all accounting stays integer.

  ai_cost_used_kopecks_current_month  — running spend, reset on the 1st
  ai_cost_limit_kopecks_per_month     — hard cap, refilled per plan

Existing rows get sensible defaults — 0 for usage, plan-derived for the
limit (we backfill via apply_plan_limits at app startup if you prefer; the
migration itself just zeroes both fields).

Revision ID: e9c4a2d8f5b1
Revises: d5f3a1c7b896
Create Date: 2026-04-28 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "e9c4a2d8f5b1"
down_revision: Union[str, Sequence[str], None] = "d5f3a1c7b896"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "organizations" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("organizations")}

    if "ai_cost_used_kopecks_current_month" not in columns:
        op.add_column(
            "organizations",
            sa.Column(
                "ai_cost_used_kopecks_current_month",
                sa.BigInteger(),
                nullable=False,
                server_default="0",
            ),
        )

    if "ai_cost_limit_kopecks_per_month" not in columns:
        op.add_column(
            "organizations",
            sa.Column(
                "ai_cost_limit_kopecks_per_month",
                sa.BigInteger(),
                nullable=False,
                server_default="0",
            ),
        )

    # Backfill the limit from each org's plan. Mirrors the canonical values
    # in app.services.quota.PLAN_LIMITS — kept here as literals so the
    # migration is self-contained and replayable on any environment.
    op.execute(
        """
        UPDATE organizations SET ai_cost_limit_kopecks_per_month = CASE plan
            WHEN 'starter' THEN 30000
            WHEN 'pro'     THEN 300000
            WHEN 'team'    THEN 1500000
            ELSE 0
        END
        WHERE ai_cost_limit_kopecks_per_month = 0
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "organizations" not in set(inspector.get_table_names()):
        return
    columns = {c["name"] for c in inspector.get_columns("organizations")}
    if "ai_cost_limit_kopecks_per_month" in columns:
        op.drop_column("organizations", "ai_cost_limit_kopecks_per_month")
    if "ai_cost_used_kopecks_current_month" in columns:
        op.drop_column("organizations", "ai_cost_used_kopecks_current_month")
