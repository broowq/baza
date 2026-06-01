"""Tests for the cross-org company warehouse.

Covers:
  * upsert_companies — dedup by domain and by name|city, distinct niche/source
    append, no-overwrite-with-empty, times_seen bump, best_score max,
    batch-collapse, best-effort (never raises).
  * search_warehouse — niche + geography match, city→region match, empty miss,
    candidate-dict shape, free (source='warehouse').
  * GET /leads/{lead_id} — full lead + computed description + warehouse
    cross-reference block, org scoping (404 across orgs).

These hit the real local Postgres (same DB the app uses). Each test cleans up
its own rows via unique dedup_key prefixes, so they're independent and rerunnable.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.api.deps import get_current_org, get_current_user
from app.db.session import SessionLocal, get_db  # SessionLocal used by the db fixture
from app.main import app
from app.models import Company, Lead, LeadStatus, Organization, Project, User
from app.services import company_warehouse as cw

# Unique-ish marker so parallel/other data never collides with test rows.
_PFX = "whtest-"

# Single shared client for the whole module. We deliberately do NOT use the
# `with TestClient(app)` form: the app declares no lifespan/startup, and the
# context-manager form opens+closes an event loop per use, which then errors
# ("Event loop is closed") when a second test reuses it in the same process.
_client = TestClient(app)


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    """Disable the rate-limit middleware for endpoint tests.

    The middleware uses a module-level `redis.asyncio` client whose connection
    pool binds to the first event loop it touches. TestClient spins a fresh loop
    per request, so the second request would hit a closed loop ("Event loop is
    closed"). Short-circuiting _get_rate_limit avoids the async-redis call
    entirely — rate limiting itself isn't under test here.
    """
    import app.main as main

    monkeypatch.setattr(main, "_get_rate_limit", lambda path: None)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        # Remove any warehouse rows this test created (domain- or name-keyed).
        session.rollback()
        session.execute(
            delete(Company).where(Company.dedup_key.like(f"%{_PFX}%"))
        )
        session.execute(
            delete(Company).where(Company.normalized_name.like(f"%{_PFX}%"))
        )
        session.commit()
        session.close()


# ── helpers ────────────────────────────────────────────────────────────────

def _cand(**kw):
    base = {
        "company": kw.pop("company", "Тест Компания"),
        "city": kw.pop("city", ""),
        "domain": kw.pop("domain", ""),
        "website": kw.pop("website", ""),
        "email": kw.pop("email", ""),
        "phone": kw.pop("phone", ""),
        "address": kw.pop("address", ""),
        "source": kw.pop("source", "2gis"),
        "score": kw.pop("score", 0),
    }
    base.update(kw)
    return base


# ── _norm_name / _dedup_key ──────────────────────────────────────────────────

def test_norm_name_lowercases_trims_collapses_and_folds_yo():
    assert cw._norm_name("  Фабрика   Окён  ") == "фабрика окен"
    assert cw._norm_name("") == ""


def test_dedup_key_prefers_base_domain():
    assert cw._dedup_key("https://www.Example-Co.RU/contacts", "X", "Y") == "example-co.ru"
    assert cw._dedup_key("example-co.ru", "X", "Y") == "example-co.ru"


def test_dedup_key_falls_back_to_name_city():
    assert cw._dedup_key("", "Окна Сибирь", "Томск") == "окна сибирь|томск"
    assert cw._dedup_key("", "Окна Сибирь", "") == "окна сибирь|"


def test_dedup_key_empty_when_no_domain_or_name():
    assert cw._dedup_key("", "", "Томск") == ""


# ── upsert: insert + dedup ───────────────────────────────────────────────────

def test_upsert_inserts_then_dedupes_by_domain(db):
    domain = f"{_PFX}okna.ru"
    n = cw.upsert_companies(
        db,
        [_cand(company="Окна 1", domain=domain, city="Томск", phone="+7 1", source="2gis", score=50)],
        niche="окна",
    )
    assert n == 1
    # Second upsert with SAME domain -> update, not a new row.
    cw.upsert_companies(
        db,
        [_cand(company="Окна 1", domain=domain, city="Томск", source="yandex_maps", score=70)],
        niche="остекление",
    )
    rows = db.execute(select(Company).where(Company.dedup_key == domain)).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.times_seen == 2
    assert row.best_score == 70  # raised to max
    assert set(row.niches) == {"окна", "остекление"}
    assert set(row.sources) == {"2gis", "yandex_maps"}


def test_upsert_dedupes_by_name_city_when_no_domain(db):
    name = f"{_PFX}СибирьТест"
    cw.upsert_companies(db, [_cand(company=name, city="Томск", source="rusprofile")], niche="окна")
    cw.upsert_companies(db, [_cand(company=name, city="Томск", source="2gis")], niche="окна")
    # Same name, DIFFERENT city -> a distinct company (city-scoped dedup).
    cw.upsert_companies(db, [_cand(company=name, city="Омск", source="2gis")], niche="окна")
    rows = db.execute(
        select(Company).where(Company.normalized_name == cw._norm_name(name))
    ).scalars().all()
    keys = sorted(r.dedup_key for r in rows)
    assert keys == [f"{cw._norm_name(name)}|омск", f"{cw._norm_name(name)}|томск"]
    tomsk = next(r for r in rows if r.dedup_key.endswith("|томск"))
    assert tomsk.times_seen == 2


def test_upsert_does_not_overwrite_good_contact_with_empty(db):
    domain = f"{_PFX}contacts.ru"
    cw.upsert_companies(
        db, [_cand(domain=domain, phone="+7 999 000 11 22", email="a@b.ru")], niche="окна"
    )
    # Second pass carries NO phone/email — must not wipe the stored ones.
    cw.upsert_companies(db, [_cand(domain=domain, phone="", email="")], niche="окна")
    row = db.execute(select(Company).where(Company.dedup_key == domain)).scalar_one()
    assert row.phone == "+7 999 000 11 22"
    assert row.email == "a@b.ru"


def test_upsert_fills_empty_field_on_later_pass(db):
    domain = f"{_PFX}fill.ru"
    cw.upsert_companies(db, [_cand(domain=domain, phone="")], niche="окна")
    cw.upsert_companies(db, [_cand(domain=domain, phone="+7 333")], niche="окна")
    row = db.execute(select(Company).where(Company.dedup_key == domain)).scalar_one()
    assert row.phone == "+7 333"


def test_upsert_collapses_duplicate_candidates_in_one_batch(db):
    domain = f"{_PFX}batch.ru"
    # Two candidates, same domain, in ONE call -> one row, times_seen == 1.
    cw.upsert_companies(
        db,
        [
            _cand(domain=domain, phone=""),
            _cand(domain=domain, phone="+7 1", address="ул. Тест 1"),
        ],
        niche="окна",
    )
    rows = db.execute(select(Company).where(Company.dedup_key == domain)).scalars().all()
    assert len(rows) == 1
    # The richer-signal duplicate is chosen as base, so phone/address are kept.
    assert rows[0].phone == "+7 1"
    assert rows[0].times_seen == 1


def test_upsert_records_twogis_firm_id_and_inn(db):
    domain = f"{_PFX}ids.ru"
    cw.upsert_companies(
        db,
        [_cand(domain=domain, source="2gis", firm_id="70000555", inn="7017123456")],
        niche="окна",
    )
    row = db.execute(select(Company).where(Company.dedup_key == domain)).scalar_one()
    assert row.twogis_firm_id == "70000555"
    assert row.inn == "7017123456"


def test_upsert_empty_list_and_unidentifiable_are_safe(db):
    assert cw.upsert_companies(db, [], niche="окна") == 0
    # Candidate with neither domain nor name -> skipped, returns 0, no raise.
    assert cw.upsert_companies(db, [{"company": "", "domain": ""}], niche="окна") == 0


# ── search_warehouse ─────────────────────────────────────────────────────────

def test_search_matches_niche_and_geography(db):
    domain = f"{_PFX}search.ru"
    cw.upsert_companies(
        db, [_cand(company="Поиск Тест", domain=domain, city="Томск", score=42)], niche="окна"
    )
    hits = cw.search_warehouse(db, niche="окна", geography="Томск", segments=[], limit=10)
    assert any(h["domain"] == domain for h in hits)
    hit = next(h for h in hits if h["domain"] == domain)
    # Candidate-dict shape used by the pipeline.
    assert hit["source"] == "warehouse"
    assert hit["demo"] is False
    assert hit["company"] == "Поиск Тест"
    assert hit["city"] == "Томск"
    assert "source_url" in hit and "snippet" in hit and "categories" in hit
    assert "external_id" in hit


def test_search_city_to_region_match(db):
    # Stored city = Томск; searching by the region 'Томская область' must hit it.
    domain = f"{_PFX}region.ru"
    cw.upsert_companies(db, [_cand(company="Регион Тест", domain=domain, city="Томск")], niche="окна")
    hits = cw.search_warehouse(db, niche="окна", geography="Томская область", segments=[], limit=10)
    assert any(h["domain"] == domain for h in hits)


def test_search_excludes_wrong_geography(db):
    domain = f"{_PFX}geo.ru"
    cw.upsert_companies(db, [_cand(company="Гео Тест", domain=domain, city="Москва")], niche="окна")
    hits = cw.search_warehouse(db, niche="окна", geography="Томск", segments=[], limit=10)
    assert all(h["domain"] != domain for h in hits)


def test_search_empty_warehouse_returns_empty(db):
    hits = cw.search_warehouse(
        db, niche="несуществующаяниша-zzz", geography="Атлантида", segments=[], limit=10
    )
    assert hits == []


def test_search_nationwide_ignores_geo_filter(db):
    domain = f"{_PFX}nation.ru"
    cw.upsert_companies(db, [_cand(company="Нац Тест", domain=domain, city="Пермь")], niche="окна")
    hits = cw.search_warehouse(db, niche="окна", geography="Россия", segments=[], limit=50)
    assert any(h["domain"] == domain for h in hits)


def test_search_matches_segment(db):
    domain = f"{_PFX}seg.ru"
    # niche stored = 'добавки'; the search niche differs but a segment matches the name.
    cw.upsert_companies(
        db, [_cand(company="Птицефабрика Сибири", domain=domain, city="Томск")], niche="добавки"
    )
    hits = cw.search_warehouse(
        db, niche="кормовые добавки", geography="Томск", segments=["птицефабрика"], limit=10
    )
    assert any(h["domain"] == domain for h in hits)


# ── GET /leads/{lead_id} ─────────────────────────────────────────────────────

@pytest.fixture
def api_env(db):
    """Create an org/project/lead + matching warehouse row, wired to the API.

    Yields (client, org_id, lead_id, other_org_id). Overrides get_db (shared
    session) and get_current_org (this org). Cleans up all created rows.
    """
    org = Organization(name=f"{_PFX}org-{uuid.uuid4().hex[:8]}")
    other_org = Organization(name=f"{_PFX}org2-{uuid.uuid4().hex[:8]}")
    db.add_all([org, other_org])
    db.flush()
    project = Project(
        organization_id=org.id, name=f"{_PFX}proj", niche="окна", geography="Томск", segments=[]
    )
    db.add(project)
    db.flush()
    lead = Lead(
        organization_id=org.id,
        project_id=project.id,
        company="Деталь Тест",
        city="Томск",
        website=f"https://{_PFX}detail.ru",
        domain=f"{_PFX}detail.ru",
        phone="+7 3822 11 22 33",
        source="2gis",
        status=LeadStatus.new,
        score=61,
        notes="relevance=55; demo=true; Производитель окон ПВХ в Томске",
    )
    db.add(lead)
    db.flush()
    # Warehouse cross-ref row keyed by the same dedup_key the lead resolves to.
    cw.upsert_companies(
        db,
        [
            _cand(
                company="Деталь Тест",
                domain=f"{_PFX}detail.ru",
                city="Томск",
                source="2gis",
                firm_id="70000777",
                score=61,
                categories=["Окна", "Остекление"],
            )
        ],
        niche="окна",
    )
    # Bump it under ANOTHER niche so 'other_niches' is non-empty in the detail.
    cw.upsert_companies(
        db, [_cand(company="Деталь Тест", domain=f"{_PFX}detail.ru", city="Томск")], niche="двери"
    )
    db.commit()

    lead_id = lead.id
    org_id = org.id
    other_org_id = other_org.id

    def _override_db():
        # Reuse the single fixture session for the whole request so test writes
        # are visible to the endpoint without cross-session isolation surprises.
        yield db

    # Default to the primary org; individual tests may re-point this override.
    state = {"org_id": org_id}

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_org] = lambda: db.get(Organization, state["org_id"])
    app.dependency_overrides[get_current_user] = lambda: User(
        id=uuid.uuid4(), email="t@t.ru", full_name="T", hashed_password="x"
    )
    try:
        yield _client, state, lead_id, other_org_id
    finally:
        app.dependency_overrides.clear()
        db.rollback()
        db.execute(delete(Lead).where(Lead.id == lead_id))
        db.execute(delete(Project).where(Project.id == project.id))
        db.execute(delete(Organization).where(Organization.id.in_([org_id, other_org_id])))
        db.commit()


def test_lead_detail_returns_full_lead_with_warehouse_and_description(api_env):
    client, state, lead_id, _ = api_env
    resp = client.get(f"/api/leads/{lead_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Full lead fields present.
    assert body["company"] == "Деталь Тест"
    assert body["phone"] == "+7 3822 11 22 33"
    assert body["score"] == 61
    # Computed description recovers the snippet from notes (prefixes stripped).
    assert body["description"] == "Производитель окон ПВХ в Томске"
    # Warehouse cross-ref block.
    wh = body["warehouse"]
    assert wh["found"] is True
    assert wh["times_seen"] >= 2
    assert wh["twogis_firm_id"] == "70000777"
    assert "Окна" in wh["categories"]
    # 'двери' surfaced elsewhere; 'окна' (this project's niche) is excluded.
    assert "двери" in wh["other_niches"]
    assert "окна" not in [n.lower() for n in wh["other_niches"]]


def test_lead_detail_description_composed_when_no_notes(api_env, db):
    client, state, lead_id, _ = api_env
    # Wipe the notes (via the same shared session the endpoint reads) so the
    # description must be composed from fields rather than the stored snippet.
    lead = db.get(Lead, lead_id)
    lead.notes = ""
    db.commit()
    resp = client.get(f"/api/leads/{lead_id}")
    assert resp.status_code == 200, resp.text
    desc = resp.json()["description"]
    # Composed from city + source + contact availability + warehouse categories.
    assert "Томск" in desc
    assert "телефон" in desc  # the lead has a phone


def test_lead_detail_404_for_other_org(api_env):
    client, state, lead_id, other_org_id = api_env
    # Re-point the org override at the OTHER org — lead must be invisible (404).
    state["org_id"] = other_org_id
    resp = client.get(f"/api/leads/{lead_id}")
    assert resp.status_code == 404


def test_lead_detail_404_for_unknown_id(api_env):
    client, state, lead_id, _ = api_env
    resp = client.get(f"/api/leads/{uuid.uuid4()}")
    assert resp.status_code == 404
