"""add per-org Yandex Geosearch request meter

organizations: yandex_requests_used_current_month, yandex_requests_limit_per_month.

Revision ID: d7b3e4c81f92
Revises: c5f9a2e7b1d8
Create Date: 2026-06-25 22:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d7b3e4c81f92"
down_revision: Union[str, Sequence[str], None] = "c5f9a2e7b1d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("organizations")}
    if "yandex_requests_used_current_month" not in cols:
        op.add_column(
            "organizations",
            sa.Column("yandex_requests_used_current_month", sa.Integer(), nullable=False, server_default="0"),
        )
    if "yandex_requests_limit_per_month" not in cols:
        op.add_column(
            "organizations",
            sa.Column("yandex_requests_limit_per_month", sa.Integer(), nullable=False, server_default="0"),
        )
        # Backfill existing orgs by plan so live Pro/Business pilots keep their
        # Yandex access immediately (otherwise the 0 default would gate them off
        # until apply_plan_limits re-runs). Mirrors quota.PLAN_LIMITS.
        op.execute(
            "UPDATE organizations SET yandex_requests_limit_per_month = "
            "CASE plan::text WHEN 'pro' THEN 6000 WHEN 'team' THEN 20000 ELSE 0 END"
        )


def downgrade() -> None:
    op.drop_column("organizations", "yandex_requests_limit_per_month")
    op.drop_column("organizations", "yandex_requests_used_current_month")
