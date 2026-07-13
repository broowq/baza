"""Анти-мультиакк: users.email_normalized + registration_ip + trial_grants (14.07.2026).

Идёт в паре с включением подтверждения почты: триал (10 разовых лидов)
без канонической identity почты фермится plus-алиасами и точками Gmail,
а через удаление аккаунта (ФЗ-152) — повторными регистрациями того же ящика.

Нормализация и пепер здесь — ЗАМОРОЖЕННАЯ КОПИЯ app/services/registration_guard.py
на дату миграции, намеренно НЕ импорт живого кода: исторический бэкфилл не должен
мутировать вместе с приложением (иначе повторный прогон на свежей среде даёт не те
хэши, что получил прод). Конвенция репо: миграции не импортируют app.*.

Индекс email_normalized неуникальный: коллизии среди исторических юзеров
(один человек, два алиаса) допустимы, дубль при регистрации ловит app.

Revision ID: d4f7b9e1c5a8
Revises: b8e4a6c2d9f3
"""
import hashlib

import sqlalchemy as sa
from alembic import op

revision = "d4f7b9e1c5a8"
down_revision = "b8e4a6c2d9f3"
branch_labels = None
depends_on = None

# ── замороженный снапшот registration_guard (14.07.2026) ────────────────────
_PEPPER = "baza-trial-book-v1"  # дубль литерала из registration_guard — не менять

_ALIASES = {
    "googlemail.com": "gmail.com",
    "ya.ru": "yandex.ru", "yandex.com": "yandex.ru", "yandex.by": "yandex.ru",
    "yandex.kz": "yandex.ru", "yandex.ua": "yandex.ru", "yandex.com.tr": "yandex.ru",
    "yandex.fr": "yandex.ru", "yandex.eu": "yandex.ru", "yandex.az": "yandex.ru",
    "yandex.uz": "yandex.ru", "yandex.com.ge": "yandex.ru",
    "me.com": "icloud.com", "mac.com": "icloud.com",
}


def _normalize(email: str) -> str:
    e = (email or "").lower().strip()
    local, _, domain = e.partition("@")
    if not domain:
        return e
    domain = _ALIASES.get(domain, domain)
    local = local.split("+", 1)[0]
    if domain == "gmail.com":
        local = local.replace(".", "")
    elif domain == "yandex.ru":
        local = local.replace(".", "-")
    return f"{local}@{domain}"


def _identity_hash(identity: str) -> str:
    return hashlib.sha256(f"{_PEPPER}:{identity}".encode()).hexdigest()


def _domain_hash(email: str) -> str:
    domain = (email or "").lower().strip().rpartition("@")[2]
    domain = _ALIASES.get(domain, domain)
    return hashlib.sha256(f"{_PEPPER}:domain:{domain}".encode()).hexdigest()


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("email_normalized", sa.String(255), nullable=False, server_default=""),
    )
    op.add_column(
        "users",
        sa.Column("registration_ip", sa.String(45), nullable=False, server_default=""),
    )
    op.create_index("ix_users_email_normalized", "users", ["email_normalized"])

    # Книга выданных триалов — переживает удаление аккаунта (ФЗ-152),
    # хранит только солёные хэши identity/домена, не ПД.
    op.create_table(
        "trial_grants",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email_identity_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("domain_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_trial_grants_domain_hash", "trial_grants", ["domain_hash"])

    # Бэкфилл: existing identity уже видели → нормализованная форма в users
    # и запись в книге (повторный триал через «удалить → зарегистрироваться
    # заново» им не положен). Таблица маленькая, построчно — дешевле, чем
    # дублировать нормализацию в SQL.
    conn = op.get_bind()
    for user_id, email in conn.execute(sa.text("SELECT id, email FROM users")).fetchall():
        identity = _normalize(email or "")
        conn.execute(
            sa.text("UPDATE users SET email_normalized = :n WHERE id = :i"),
            {"n": identity, "i": user_id},
        )
        conn.execute(
            sa.text(
                "INSERT INTO trial_grants (id, email_identity_hash, domain_hash) "
                "VALUES (gen_random_uuid(), :h, :d) ON CONFLICT (email_identity_hash) DO NOTHING"
            ),
            {"h": _identity_hash(identity), "d": _domain_hash(email or "")},
        )


def downgrade() -> None:
    op.drop_index("ix_trial_grants_domain_hash", table_name="trial_grants")
    op.drop_table("trial_grants")
    op.drop_index("ix_users_email_normalized", table_name="users")
    op.drop_column("users", "registration_ip")
    op.drop_column("users", "email_normalized")
