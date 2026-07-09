"""Бэкфилл контактов из лидов в склад companies

Аудит 09.07: обогащение никогда не писало добытые контакты обратно в склад —
companies.email = 0 у всех 1661 строк при 456 email, уже добытых в лидах.
Актив не накапливался: warehouse-first раздавал строки без контактов, хотя
контакты для тех же компаний уже были найдены другими проектами.

Разовый перенос: лучший (свежайший, контактный) лид каждого домена заполняет
ПУСТЫЕ email/phone/address/website складской строки (fill-empty — непустое не
перетираем). Дальше актив пополняет write-back в enrich_leads_task.

ВАЖНО (ревью 09.07): companies.dedup_key — БАЗОВЫЙ домен (get_base_domain,
снимает поддомены), а leads.domain — extract_domain (снимает только www).
Джойн по сырому leads.domain промахивался бы на поддоменах (shop.foo.ru vs
foo.ru). Сводим leads.domain к последним двум лейблам (substring
'[^.]+\\.[^.]+$'): foo.ru→foo.ru, shop.foo.ru→foo.ru. Многосоставные TLD
(.co.uk→co.uk) — редкость на RU-рынке, fill-empty ничего не портит.

Revision ID: a4d8f2c6e9b1
Revises: f7c2e8a4d1b9
Create Date: 2026-07-09
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "a4d8f2c6e9b1"
down_revision = "f7c2e8a4d1b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE companies c SET
            email   = CASE WHEN COALESCE(c.email, '')   = '' AND s.email   != '' THEN LEFT(s.email, 255)   ELSE c.email END,
            phone   = CASE WHEN COALESCE(c.phone, '')   = '' AND s.phone   != '' THEN LEFT(s.phone, 80)    ELSE c.phone END,
            address = CASE WHEN COALESCE(c.address, '') = '' AND s.address != '' THEN LEFT(s.address, 300) ELSE c.address END,
            website = CASE WHEN COALESCE(c.website, '') = '' AND s.website != '' AND s.website NOT LIKE 'maps://%'
                           THEN LEFT(s.website, 300) ELSE c.website END
        FROM (
            SELECT DISTINCT ON (base_domain) base_domain, email, phone, address, website
            FROM (
                SELECT
                    COALESCE(substring(domain from '[^.]+\.[^.]+$'), domain) AS base_domain,
                    email, phone, address, website, created_at
                FROM leads
                WHERE domain != '' AND (email != '' OR phone != '' OR address != '')
            ) t
            ORDER BY base_domain, (email != '') DESC, (phone != '') DESC, created_at DESC
        ) s
        WHERE c.dedup_key = s.base_domain
          AND (COALESCE(c.email, '') = '' OR COALESCE(c.phone, '') = ''
               OR COALESCE(c.address, '') = '' OR COALESCE(c.website, '') = '')
        """
    )


def downgrade() -> None:
    # Данные-only бэкфилл: откат не восстанавливает прежние пустоты (и не должен).
    pass
