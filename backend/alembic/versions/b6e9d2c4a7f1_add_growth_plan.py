"""add growth plan (тир «Team» 9 900 ₽ между Starter и Pro)

Тарифная сетка 2026-07-09 по рыночному исследованию: между Starter 4 900 и
Pro 16 900 зияла дыра ×4,3 ровно в коридоре self-serve 5–10 тыс ₽, где сидят
Coldy Про/Expert и Компас-месяц. Enum-значение `growth` (отображается как
«Team»), т.к. значение `team` исторически занято тиром Business.

Revision ID: b6e9d2c4a7f1
Revises: a8d3f6e2c9b7
Create Date: 2026-07-09
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "b6e9d2c4a7f1"
down_revision = "a8d3f6e2c9b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ADD VALUE не работает внутри транзакции на PG < 12; на 12+ работает,
    # но IF NOT EXISTS делает миграцию идемпотентной при гонке реплик
    # (наши миграции сериализованы advisory-lock'ом в env.py).
    op.execute("ALTER TYPE plantype ADD VALUE IF NOT EXISTS 'growth' AFTER 'starter'")


def downgrade() -> None:
    # PG не умеет удалять значения из enum; безопасный откат — переселить
    # организации с growth на starter и оставить значение в типе. Лимиты-колонки
    # тоже приводим к Starter-шаблону (5000/5/3, AI 100 ₽, Яндекс 0) — иначе
    # переименованные организации оставались бы с growth-квотами вдвое выше.
    op.execute(
        "UPDATE organizations SET plan = 'starter', leads_limit_per_month = 5000, "
        "projects_limit = 5, users_limit = 3, ai_cost_limit_kopecks_per_month = 10000, "
        "yandex_requests_limit_per_month = 0 WHERE plan = 'growth'"
    )
