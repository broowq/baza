"""leads.description — «О компании» в карточке лида

Раздел «О компании» существовал в карточке, но рендерил суррогат из
метаданных («категории. г. Томск. источник: 2ГИС. есть телефон») — реальное
описание деятельности не хранилось на лиде вовсе. Теперь: колонка +
бэкфилл существующих лидов из склада companies (совпадение по dedup_key =
домену), дальше наполняется сбором (описание кандидата) и обогащением
(meta-description с сайта компании).

Revision ID: f7c2e8a4d1b9
Revises: e2a7c9d4b6f8
Create Date: 2026-07-09
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f7c2e8a4d1b9"
down_revision = "e2a7c9d4b6f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
    )
    # Бэкфилл со склада: у companies dedup_key для доменных строк = базовый
    # домен — join по нему покрывает большинство собранных лидов. Обрезаем до
    # 2000 симв. (в складе description до 100k — карточке столько не нужно).
    op.execute(
        """
        UPDATE leads SET description = LEFT(c.description, 2000)
        FROM companies c
        WHERE leads.description = ''
          AND leads.domain != ''
          AND c.dedup_key = leads.domain
          AND COALESCE(c.description, '') != ''
        """
    )


def downgrade() -> None:
    op.drop_column("leads", "description")
