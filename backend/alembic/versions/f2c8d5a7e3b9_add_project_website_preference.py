"""projects.website_preference — требование к сайту клиента (14.07.2026).

Инцидент: веб-студия просила «клиентов, у которых НЕТ сайтов» — констрейнт
не имел места в модели и молча терялся; выдача при этом систематически
дискриминирует бездоменных (+8 к скору за сайт). 'any' — исторический
дефолт для всех существующих проектов.

Revision ID: f2c8d5a7e3b9
Revises: d4f7b9e1c5a8
"""
import sqlalchemy as sa
from alembic import op

revision = "f2c8d5a7e3b9"
down_revision = "d4f7b9e1c5a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("website_preference", sa.String(16), nullable=False, server_default="any"),
    )


def downgrade() -> None:
    op.drop_column("projects", "website_preference")
