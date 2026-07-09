"""project.excluded_segments — жёсткие исключения из промпта пользователя

Клиентский кейс (прод, 09.07.2026): промпт «нужны только b2b компании»
превратился энхансером в 20 сегментов «все типы организаций» (включая КФХ,
розницу, НКО, отели), и warehouse-first сбор принёс фермерские магазины.
Ограничение из промпта не имело ни поля для хранения, ни точки применения.

Теперь энхансер извлекает противоречащие ограничениям типы компаний в
excluded_segments; их уважают складской SQL-отбор (NOT-клаузы), LLM-фильтр
дозы и live-фильтр.

Revision ID: e2a7c9d4b6f8
Revises: c7f1a3e5d9b2
Create Date: 2026-07-09
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "e2a7c9d4b6f8"
down_revision = "c7f1a3e5d9b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "excluded_segments",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "excluded_segments")
