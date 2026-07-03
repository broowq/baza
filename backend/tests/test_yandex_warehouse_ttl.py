"""purge_yandex_warehouse_ttl — Yandex Geosearch 30-day retention sweep.

Yandex ToS: результаты работы API нельзя хранить дольше 30 дней (обычный
тариф). Задача чистит склад `companies` от Яндекс-происхождения у строк,
которых не видели > yandex_raw_ttl_days:
  • Яндекс — единственный источник → строка удаляется;
  • мульти-источник → снимается только метка 'yandex_maps', строка остаётся;
  • свежие Яндекс-строки и не-Яндекс строки не трогаются.

Как и остальные warehouse/periodic-тесты — бьёт реальный локальный Postgres
через SessionLocal и чистит свои строки по префиксу dedup_key.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.models import Company
from app.tasks.periodic import purge_yandex_warehouse_ttl

_PFX = "ttltest-"


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _mk(db, suffix: str, sources: list[str], days_old: int) -> Company:
    ts = datetime.now(timezone.utc) - timedelta(days=days_old)
    co = Company(
        dedup_key=f"{_PFX}{suffix}",
        normalized_name=f"{_PFX}{suffix}",
        name=f"{_PFX}{suffix}",
        phone="+7 999 000-00-00",
        city="Новосибирск",
        sources=list(sources),
        first_seen_at=ts,
        last_seen_at=ts,
    )
    db.add(co)
    return co


def test_purge_yandex_warehouse_ttl(db):
    # Clean any leftovers from a prior aborted run.
    db.execute(delete(Company).where(Company.dedup_key.like(f"{_PFX}%")))
    db.commit()

    _mk(db, "stale-yandex-only", ["yandex_maps"], 40)
    stale_multi = _mk(db, "stale-multi", ["2gis", "yandex_maps"], 40)
    fresh_yandex = _mk(db, "fresh-yandex", ["yandex_maps"], 5)
    stale_2gis = _mk(db, "stale-2gis", ["2gis"], 40)
    db.commit()
    multi_id, fresh_id, gis_id = stale_multi.id, fresh_yandex.id, stale_2gis.id

    try:
        purge_yandex_warehouse_ttl()  # opens its own session + commits
        db.expire_all()

        # Yandex-only + stale → row deleted.
        assert (
            db.execute(
                select(Company).where(Company.dedup_key == f"{_PFX}stale-yandex-only")
            ).scalar_one_or_none()
            is None
        )
        # Multi-source + stale → kept, but Yandex provenance stripped.
        m = db.get(Company, multi_id)
        assert m is not None
        assert "yandex_maps" not in m.sources
        assert "2gis" in m.sources
        # Fresh Yandex row → untouched (still within TTL).
        f = db.get(Company, fresh_id)
        assert f is not None and "yandex_maps" in f.sources
        # Non-Yandex stale row → untouched.
        g = db.get(Company, gis_id)
        assert g is not None and g.sources == ["2gis"]
    finally:
        db.execute(delete(Company).where(Company.dedup_key.like(f"{_PFX}%")))
        db.commit()
