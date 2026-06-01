"""add_companies_warehouse

Creates the `companies` table — a cross-organization registry of every company
ever discovered by the search pipeline. Future searches reuse stored companies
(cut 2GIS/Yandex/rusprofile API cost, improve recall) and lead cards can show
rich company cross-references (times_seen, niches, sources).

Identity is `dedup_key` (UNIQUE): lowercased domain when present, else
f"{normalized_name}|{city_lower}". Upsert dedupes on it via ON CONFLICT.

Revision ID: a8f2c4d6e1b9
Revises: f3b8c1d9e2a4
Create Date: 2026-06-02 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "a8f2c4d6e1b9"
down_revision: Union[str, Sequence[str], None] = "f3b8c1d9e2a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "companies" not in tables:
        op.create_table(
            "companies",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("dedup_key", sa.String(length=255), nullable=False),
            sa.Column("domain", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("normalized_name", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("name", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("website", sa.String(length=400), nullable=False, server_default=""),
            sa.Column("email", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("phone", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("address", sa.String(length=400), nullable=False, server_default=""),
            sa.Column("city", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("region", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("categories", JSONB, nullable=False, server_default="[]"),
            sa.Column("niches", JSONB, nullable=False, server_default="[]"),
            sa.Column("sources", JSONB, nullable=False, server_default="[]"),
            sa.Column("twogis_firm_id", sa.String(length=80), nullable=False, server_default=""),
            sa.Column("rusprofile_id", sa.String(length=80), nullable=False, server_default=""),
            sa.Column("inn", sa.String(length=20), nullable=False, server_default=""),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("contacts_json", JSONB, nullable=False, server_default="{}"),
            sa.Column("best_score", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("times_seen", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("first_seen_at", sa.DateTime(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False),
            sa.Column("raw_json", JSONB, nullable=False, server_default="{}"),
        )

    indexes = {idx["name"] for idx in inspector.get_indexes("companies")} if "companies" in set(
        sa.inspect(bind).get_table_names()
    ) else set()

    # UNIQUE index on the identity key — drives ON CONFLICT upsert dedupe.
    if "ix_companies_dedup_key" not in indexes:
        op.create_index("ix_companies_dedup_key", "companies", ["dedup_key"], unique=True)
    if "ix_companies_domain" not in indexes:
        op.create_index("ix_companies_domain", "companies", ["domain"], unique=False)
    if "ix_companies_normalized_name" not in indexes:
        op.create_index("ix_companies_normalized_name", "companies", ["normalized_name"], unique=False)
    if "ix_companies_city" not in indexes:
        op.create_index("ix_companies_city", "companies", ["city"], unique=False)
    if "ix_companies_twogis_firm_id" not in indexes:
        op.create_index("ix_companies_twogis_firm_id", "companies", ["twogis_firm_id"], unique=False)
    if "ix_companies_inn" not in indexes:
        op.create_index("ix_companies_inn", "companies", ["inn"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "companies" not in set(inspector.get_table_names()):
        return
    for ix in (
        "ix_companies_inn",
        "ix_companies_twogis_firm_id",
        "ix_companies_city",
        "ix_companies_normalized_name",
        "ix_companies_domain",
        "ix_companies_dedup_key",
    ):
        op.drop_index(ix, table_name="companies")
    op.drop_table("companies")
