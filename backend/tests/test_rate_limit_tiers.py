"""Регресс на метод-осознанные тиры рейт-лимитера (app/main.py).

Баг, который закрываем: платящий пользователь на Pro, просто листая таблицу
лидов, ловил «Слишком много запросов». Страница шлёт GET .../table + .../stats
на каждое действие (+ поллинг при живом сборе), а тир /api/leads/project стоял
20/мин в расчёте на «внешние API» — но чтения из БД под тот же префикс.

Фикс: GET-чтения под /leads/project идут по щедрому лимиту, а дорогой
POST /collect|/enrich остаётся жёстким. Тест пинит именно это разделение,
не завязываясь на конкретные числа (dev/prod различаются).
"""
from __future__ import annotations

from app.main import _get_rate_limit


def _rl(path: str, method: str):
    r = _get_rate_limit(path, method)
    assert r is not None, f"{method} {path} должен матчить какой-то тир"
    max_req, _window, prefix = r
    return max_req, prefix


def test_lead_table_reads_are_generous():
    """GET table/stats/export/get не должны сидеть в узком collect-бакете."""
    table, _ = _rl("/api/leads/project/abc/table", "GET")
    stats, _ = _rl("/api/leads/project/abc/stats", "GET")
    collect, _ = _rl("/api/leads/project/abc/collect", "POST")
    # Чтения ЗАМЕТНО щедрее, чем дорогой сбор.
    assert table > collect
    assert stats > collect
    assert table == stats  # оба под общим read-бюджетом


def test_collect_and_enrich_stay_throttled():
    """POST /collect и /enrich (внешние API + очередь) — жёсткий тир."""
    collect, cprefix = _rl("/api/leads/project/abc/collect", "POST")
    enrich, _ = _rl("/api/leads/project/abc/enrich", "POST")
    generic, _ = _rl("/api/organizations/me", "GET")
    assert cprefix == "/api/leads/project"
    # Сбор строго жёстче обычного API-чтения.
    assert collect < generic
    assert enrich < generic


def test_read_budget_matches_generic_api():
    """GET-чтения лидов должны получать тот же бюджет, что и остальной API —
    активный юзер не должен упираться в лимит на простом листании."""
    table, _ = _rl("/api/leads/project/abc/table", "GET")
    generic, _ = _rl("/api/organizations/me", "GET")
    assert table == generic


def test_method_filter_falls_through_correctly():
    """POST-тир не должен перехватывать GET того же префикса (порядок важен)."""
    _, get_prefix = _rl("/api/leads/project/abc/table", "GET")
    # GET матчит generic-хвост тира leads/project (не POST-only), но префикс тот же.
    assert get_prefix == "/api/leads/project"
    # А enhance-prompt (дорогой LLM) остаётся самым жёстким из перечисленных.
    llm, _ = _rl("/api/projects/enhance-prompt", "POST")
    collect, _ = _rl("/api/leads/project/abc/collect", "POST")
    assert llm <= collect
