"""Contact-first выдача: дозы не должны наполняться пустышками.

Аудит 09.07: warehouse-first забивал дозу бесконтактными строками (склад
сортировал только по best_score), live-Яндекс не запускался месяц, 57%
июльских лидов ушли клиентам без телефона и email. Регрессы:
  • склад отдаёт контактные строки раньше бесконтактных;
  • при дефиците контактов в дозе запускается live-добор и пустышки
    заменяются контактными live-находками;
  • обогащение делает write-back контактов в склад (актив копится).
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete

import app.tasks.jobs as jobs_mod
from app.db.session import SessionLocal
from app.models import CollectionJob, Company, JobStatus, Lead, LeadStatus, Organization, PlanType, Project
from app.services import company_warehouse as cw

_PFX = "cfdose-"


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
        s.rollback()
        s.execute(delete(Company).where(Company.normalized_name.like(f"{_PFX}%")))
        s.commit()
    finally:
        s.close()


def _wh_cand(company, domain, *, phone="", email="", score=50):
    return {
        "company": company, "city": "Томск", "domain": domain,
        "website": f"https://{domain}", "email": email, "phone": phone,
        "address": "Томск", "source": "2gis", "score": score,
    }


def _mk_org_project(db, niche):
    org = Organization(
        name=f"{_PFX}org-{uuid.uuid4().hex[:6]}", plan=PlanType.pro,
        leads_used_current_month=0, leads_limit_per_month=100000,
        projects_limit=100, users_limit=100,
    )
    db.add(org); db.flush()
    proj = Project(organization_id=org.id, name=f"{_PFX}proj",
                   niche=niche, geography="Томск", segments=[], prompt="")
    db.add(proj); db.flush()
    db.commit()
    return org, proj


def _cleanup(db, org, proj):
    db.rollback()
    db.execute(delete(Lead).where(Lead.project_id == proj.id))
    db.execute(delete(CollectionJob).where(CollectionJob.project_id == proj.id))
    db.execute(delete(Project).where(Project.id == proj.id))
    db.execute(delete(Organization).where(Organization.id == org.id))
    db.commit()


# ── склад: контактные строки вперёд ──────────────────────────────────────────

def test_search_warehouse_orders_contactful_first(db):
    niche = f"{_PFX}окна-{uuid.uuid4().hex[:4]}"
    d_empty = f"{_PFX}{uuid.uuid4().hex[:6]}-empty.ru"
    d_phone = f"{_PFX}{uuid.uuid4().hex[:6]}-phone.ru"
    cw.upsert_companies(db, [
        # пустышка с ВЫСОКИМ score — раньше вышла бы первой и заняла слот дозы
        _wh_cand(f"{_PFX}Пустышка", d_empty, score=95),
        _wh_cand(f"{_PFX}С телефоном", d_phone, phone="+7 999 111-22-33", score=40),
    ], niche=niche)
    hits = cw.search_warehouse(db, niche=niche, geography="Томск", limit=10)
    ours = [h for h in hits if h["domain"] in (d_empty, d_phone)]
    assert [h["domain"] for h in ours] == [d_phone, d_empty], \
        "контактная строка обязана идти раньше пустышки, несмотря на меньший score"


# ── доза: live-добор при дефиците контактов + замена пустышек ────────────────

def test_contact_deficit_triggers_live_and_replaces_contactless(db, monkeypatch):
    niche = f"{_PFX}ниша-{uuid.uuid4().hex[:4]}"
    org, proj = _mk_org_project(db, niche)
    # Склад целиком из пустышек (адрес есть → строки saveable, контактов нет).
    for i in range(4):
        cw.upsert_companies(
            db, [_wh_cand(f"{_PFX}Пустой {i}", f"{_PFX}{uuid.uuid4().hex[:6]}-e{i}.ru", score=90)],
            niche=niche,
        )
    db.commit()

    live_rows = [
        {
            "company": f"{_PFX}Живой {i}", "city": "Томск",
            "domain": f"{_PFX}{uuid.uuid4().hex[:6]}-l{i}.ru",
            "website": f"https://{_PFX}l{i}.ru", "email": f"info@l{i}.ru",
            "phone": f"+7 999 000-00-0{i}", "address": "Томск",
            "source": "yandex_maps", "score": 60,
        }
        for i in range(4)
    ]
    live_calls = []

    def fake_search_leads(*a, **k):
        live_calls.append(1)
        return [dict(r) for r in live_rows]

    monkeypatch.setattr(jobs_mod, "search_leads", fake_search_leads)
    monkeypatch.setattr(jobs_mod, "filter_candidates_llm", lambda cands, *a, **k: cands)
    monkeypatch.setattr(jobs_mod, "enrich_website_contacts",
                        lambda *a, **k: {"emails": [], "phones": [], "addresses": []})
    monkeypatch.setattr(jobs_mod, "enrich_2gis_lead",
                        lambda *a, **k: {"emails": [], "phones": [], "addresses": []})

    job = CollectionJob(organization_id=org.id, project_id=proj.id,
                        status=JobStatus.queued, kind="collect", requested_limit=4)
    db.add(job); db.commit()
    try:
        jobs_mod.collect_leads_task(str(job.id))
        db.expire_all()
        assert live_calls, "дефицит контактов обязан запустить live-поиск, хотя доза была полна"
        saved = db.execute(
            __import__("sqlalchemy").select(Lead).where(Lead.project_id == proj.id)
        ).scalars().all()
        assert saved, "лиды сохранены"
        with_contact = [l for l in saved if l.phone or l.email]
        share = len(with_contact) / len(saved)
        assert share >= jobs_mod._DOSE_MIN_CONTACT_SHARE, \
            f"доля контактных лидов {share:.0%} ниже порога — замена пустышек не сработала: " \
            f"{[(l.company, l.phone, l.email) for l in saved]}"
    finally:
        _cleanup(db, org, proj)


def test_contactful_dose_does_not_trigger_live(db, monkeypatch):
    """Доза, полная контактными складскими строками, live НЕ дёргает —
    иначе каждая выдача жгла бы платный Яндекс без нужды."""
    niche = f"{_PFX}ниша2-{uuid.uuid4().hex[:4]}"
    org, proj = _mk_org_project(db, niche)
    for i in range(4):
        cw.upsert_companies(
            db, [_wh_cand(f"{_PFX}Полный {i}", f"{_PFX}{uuid.uuid4().hex[:6]}-f{i}.ru",
                          phone=f"+7 999 111-00-0{i}", score=70)],
            niche=niche,
        )
    db.commit()
    live_calls = []
    monkeypatch.setattr(jobs_mod, "search_leads", lambda *a, **k: live_calls.append(1) or [])
    monkeypatch.setattr(jobs_mod, "filter_candidates_llm", lambda cands, *a, **k: cands)
    monkeypatch.setattr(jobs_mod, "enrich_website_contacts",
                        lambda *a, **k: {"emails": [], "phones": [], "addresses": []})
    monkeypatch.setattr(jobs_mod, "enrich_2gis_lead",
                        lambda *a, **k: {"emails": [], "phones": [], "addresses": []})

    job = CollectionJob(organization_id=org.id, project_id=proj.id,
                        status=JobStatus.queued, kind="collect", requested_limit=4)
    db.add(job); db.commit()
    try:
        jobs_mod.collect_leads_task(str(job.id))
        assert not live_calls, "полная контактная доза не должна запускать live"
    finally:
        _cleanup(db, org, proj)


# ── обогащение: write-back контактов в склад ─────────────────────────────────

def test_enrich_writes_contacts_back_to_warehouse(db, monkeypatch):
    niche = f"{_PFX}ниша3-{uuid.uuid4().hex[:4]}"
    org, proj = _mk_org_project(db, niche)
    domain = f"{_PFX}{uuid.uuid4().hex[:6]}-wb.ru"
    cw.upsert_companies(db, [_wh_cand(f"{_PFX}БезКонтактов", domain, score=30)], niche=niche)
    lead = Lead(
        organization_id=org.id, project_id=proj.id, company=f"{_PFX}БезКонтактов",
        city="Томск", website=f"https://{domain}", domain=domain,
        email="", phone="", source="searxng", status=LeadStatus.new, enriched=False,
    )
    db.add(lead)
    job = CollectionJob(organization_id=org.id, project_id=proj.id,
                        status=JobStatus.queued, kind="enrich", requested_limit=5)
    db.add(job); db.commit()

    monkeypatch.setattr(
        jobs_mod, "enrich_website_contacts",
        lambda url: {"emails": ["sales@wb.ru"], "phones": ["+7 999 222-33-44"],
                     "addresses": ["Томск, пр. Ленина 1"]},
    )
    monkeypatch.setattr(jobs_mod, "enrich_2gis_lead",
                        lambda *a, **k: {"emails": [], "phones": [], "addresses": []})
    try:
        jobs_mod.enrich_leads_task(str(job.id))
        db.expire_all()
        wh = cw.find_company_for_lead(db, domain=domain, company=f"{_PFX}БезКонтактов", city="Томск")
        assert wh is not None
        assert wh.email == "sales@wb.ru", "email обязан прийти в склад"
        assert wh.phone == "+7 999 222-33-44", "телефон обязан прийти в склад"
        assert (wh.address or "").startswith("Томск"), "адрес обязан прийти в склад"
    finally:
        _cleanup(db, org, proj)
