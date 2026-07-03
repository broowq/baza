"""add subscription auto-renew fields (YooKassa recurring)

Автопродление подписки: сохранённый способ оплаты ЮKassa + согласие на
автосписание + счётчик ретраев + отметка «напоминание отправлено».

Revision ID: a8d3f6e2c9b7
Revises: d7b3e4c81f92
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a8d3f6e2c9b7"
down_revision = "d7b3e4c81f92"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("auto_renew", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "subscriptions",
        sa.Column("payment_method_id", sa.String(length=120), nullable=False, server_default=""),
    )
    op.add_column(
        "subscriptions",
        sa.Column("renew_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "subscriptions",
        sa.Column("expiry_reminder_sent_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "expiry_reminder_sent_at")
    op.drop_column("subscriptions", "renew_attempts")
    op.drop_column("subscriptions", "payment_method_id")
    op.drop_column("subscriptions", "auto_renew")
