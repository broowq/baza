"""org.yandex_requests_cap_override — персистентный grandfather-кап Яндекса

Сетка 2026-07-09 срезала шаблонный Яндекс-кап Pro 1 400 → 1 200; ранним
пилотам обещан 1 400 навсегда. Первая реализация («не срезать сохранённый
лимит при продлении того же плана») провалила адверсариал-ревью двумя
подтверждёнными дефектами:
  1) продление платного плана приваривало к нему кап более высокого тира,
     выданного админом без Subscription-строки (Business 2 800 на Pro →
     наценка ×6,4 — пробой инварианта ×10);
  2) обещание «навсегда» стиралось любым lapse: даунгрейд в free обнулял
     единственную запись 1 400, и повторная покупка Pro получала шаблон 1 200.
Персональная колонка-override чинит оба: в ней хранится именно ОБЕЩАНИЕ
(а не остаток прежнего плана), она переживает lapse и никогда не переносит
кап чужого тира. apply_plan_limits() берёт max(шаблон, override) только на
планах с ненулевым шаблонным капом.

Data-step: всем организациям, сидящим на Pro со старым капом 1 400 на момент
миграции (= пилоты дорегридовой сетки), override проставляется автоматически.

Revision ID: c7f1a3e5d9b2
Revises: b6e9d2c4a7f1
Create Date: 2026-07-09
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c7f1a3e5d9b2"
down_revision = "b6e9d2c4a7f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("yandex_requests_cap_override", sa.Integer(), nullable=True),
    )
    # Grandfather: все, кто СЕЙЧАС на Pro с капом старых сеток, получают
    # обещание 1 400 навсегда. Порог >= 1400, а не = 1400: колонка
    # переписывается только план-событиями, поэтому самые ранние пилоты всё
    # ещё держат 6 000 (сетка 25.06) или 3 000 (26.06) — WHERE = 1400 их
    # пропустил бы, и первое же продление срезало бы их в шаблонные 1 200
    # (найдено адверсариал-верификацией). Значение обещания при этом ровно
    # 1 400: старые 3 000/6 000 всегда были «до смены тарифа», навсегда
    # обещан именно кап сетки 29.06. Пилоты, уже lapsed в free на момент
    # миграции, сюда не попадают — правятся ручным UPDATE по обращению.
    op.execute(
        "UPDATE organizations SET yandex_requests_cap_override = 1400 "
        "WHERE plan = 'pro' AND yandex_requests_limit_per_month >= 1400"
    )


def downgrade() -> None:
    op.drop_column("organizations", "yandex_requests_cap_override")
