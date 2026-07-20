"""users.marketing_consent + marketing_consent_at (20.07.2026).

Отдельное необязательное согласие на новостные/рекламные рассылки
(ст. 18 ФЗ «О рекламе»). Существующим юзерам — False (не подписаны):
согласие требует активного действия, ретроактивно его подразумевать нельзя.

Revision ID: a3e9f1c7d2b4
Revises: f2c8d5a7e3b9
"""
import sqlalchemy as sa
from alembic import op

revision = "a3e9f1c7d2b4"
down_revision = "f2c8d5a7e3b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("marketing_consent", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column("marketing_consent_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "marketing_consent_at")
    op.drop_column("users", "marketing_consent")
