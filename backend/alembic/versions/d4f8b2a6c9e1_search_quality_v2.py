"""Батч «поиск v2» (21.07.2026): рейтинг/отзывы с карт, ЕГРЮЛ-статус (DaData),
сигнал найма hh.ru, кап попыток обогащения.

companies: rating, review_count, legal_status, okved, registered_at.
leads: rating, review_count, inn, legal_status, hiring_vacancies, enrich_attempts.

Все колонки либо nullable, либо с server_default — бэкфилл не нужен,
существующие строки означают «не проверяли».

Revision ID: d4f8b2a6c9e1
Revises: a3e9f1c7d2b4
"""
import sqlalchemy as sa
from alembic import op

revision = "d4f8b2a6c9e1"
down_revision = "a3e9f1c7d2b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("legal_status", sa.String(20), nullable=False, server_default=""))
    op.add_column("companies", sa.Column("okved", sa.String(160), nullable=False, server_default=""))
    op.add_column("companies", sa.Column("registered_at", sa.DateTime(), nullable=True))
    op.add_column("companies", sa.Column("rating", sa.Float(), nullable=True))
    op.add_column("companies", sa.Column("review_count", sa.Integer(), nullable=True))

    op.add_column("leads", sa.Column("rating", sa.Float(), nullable=True))
    op.add_column("leads", sa.Column("review_count", sa.Integer(), nullable=True))
    op.add_column("leads", sa.Column("inn", sa.String(20), nullable=False, server_default=""))
    op.add_column("leads", sa.Column("legal_status", sa.String(20), nullable=False, server_default=""))
    op.add_column("leads", sa.Column("hiring_vacancies", sa.Integer(), nullable=True))
    op.add_column("leads", sa.Column("enrich_attempts", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("leads", "enrich_attempts")
    op.drop_column("leads", "hiring_vacancies")
    op.drop_column("leads", "legal_status")
    op.drop_column("leads", "inn")
    op.drop_column("leads", "review_count")
    op.drop_column("leads", "rating")

    op.drop_column("companies", "review_count")
    op.drop_column("companies", "rating")
    op.drop_column("companies", "registered_at")
    op.drop_column("companies", "okved")
    op.drop_column("companies", "legal_status")
