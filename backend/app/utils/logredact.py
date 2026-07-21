"""Маскирование ПД для логов (152-ФЗ).

Логи — это хранилище данных: утечка лог-файла = утечка ПД со всеми штрафными
последствиями. Поэтому email в логах не пишем в открытом виде — маскируем так,
чтобы для отладки хватало (домен + первый символ), но восстановить адрес было
нельзя.
"""
from __future__ import annotations


def mask_email(email: str | None) -> str:
    """'ivan.petrov@example.com' → 'i***@example.com'. Пустое/битое → '<hidden>'."""
    if not email or "@" not in email:
        return "<hidden>"
    local, _, domain = email.partition("@")
    if not local:
        return f"***@{domain}"
    return f"{local[0]}***@{domain}"
