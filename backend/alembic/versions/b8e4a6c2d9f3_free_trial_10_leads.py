"""Free = пробный доступ: 10 разовых лидов + 10 ₽ AI

Решение 13.07.2026: вместо «Free без лидов» (первый сбор умирал в пейволл
без пробы продукта) — разовый триал: 10 лидов Starter-уровня (2ГИС/веб/склад,
без Яндекса) и 10 ₽ AI-бюджета на качество первого сбора. Разовость
обеспечивает reset_monthly_quotas, который больше НЕ сбрасывает счётчики
free-оргов. Это не «Free-50»: лиды не возобновляются.

Бэкфилл: существующим free-оргам выставляем лимиты (использованное НЕ
трогаем: бывшие платники с used>10 триал не получают — правильно).

Revision ID: b8e4a6c2d9f3
Revises: a4d8f2c6e9b1
Create Date: 2026-07-13
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "b8e4a6c2d9f3"
down_revision = "a4d8f2c6e9b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE organizations
        SET leads_limit_per_month = 10,
            ai_cost_limit_kopecks_per_month = 1000
        WHERE plan = 'free'
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE organizations
        SET leads_limit_per_month = 0,
            ai_cost_limit_kopecks_per_month = 0
        WHERE plan = 'free'
        """
    )
