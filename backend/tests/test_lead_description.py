"""«О компании» в карточке лида: описание деятельности компании.

Раздел существовал, но рендерил суррогат из метаданных («категории. г. Томск.
источник: 2ГИС. есть телефон») — реального «чем занимается компания» не было
нигде. Теперь: leads.description наполняется сбором (описание кандидата),
обогащением (meta-description сайта, с дозаполнением склада) и бэкфиллом из
склада (миграция f7c2e8a4d1b9); карточка предпочитает реальный текст.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete

from app.api.routes.leads import _compose_lead_description
from app.db.session import SessionLocal
from app.models import CollectionJob, Company, JobStatus, Lead, LeadStatus, Organization, PlanType, Project
from app.services import company_warehouse as cw
from app.services.lead_collection import _extract_site_description
import app.tasks.jobs as jobs_mod

_PFX = "leaddesc-"


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


# ── _extract_site_description ────────────────────────────────────────────────

def test_extracts_meta_description():
    html = '<head><meta name="description" content="Оптовые поставки кедрового пиломатериала по Сибири, доставка от 1 куба."></head>'
    assert _extract_site_description(html).startswith("Оптовые поставки кедрового")


def test_extracts_og_description_and_reversed_attr_order():
    html = '<meta property="og:description" content="Производим срубы и дома из бруса под ключ в Томске.">'
    assert "срубы и дома из бруса" in _extract_site_description(html)
    # content ПЕРЕД name — второй паттерн
    html2 = '<meta content="Клининг для бизнес-центров и офисов, договор и закрывающие." name="description">'
    assert "Клининг для бизнес-центров" in _extract_site_description(html2)


def test_falls_back_to_title_and_unescapes():
    html = "<title>Кедр&nbsp;Томск &mdash; пиломатериалы оптом</title>"
    out = _extract_site_description(html)
    assert "пиломатериалы оптом" in out
    assert "&mdash;" not in out and "&nbsp;" not in out


def test_rejects_garbage_and_empty():
    assert _extract_site_description("") == ""
    assert _extract_site_description("<title>Главная</title>") == ""
    assert _extract_site_description('<meta name="description" content="ок">') == ""


# ── _compose_lead_description: приоритеты ────────────────────────────────────

def _lead(**kw) -> Lead:
    base = dict(
        company="Тест", city="Томск", website="https://t.ru", domain="t.ru",
        email="", phone="+7 999", address="", notes="", description="",
        source="2gis", status=LeadStatus.new,
    )
    base.update(kw)
    return Lead(**base)


def test_compose_prefers_lead_description():
    lead = _lead(description="Поставляем фанеру и ОСБ оптом.", notes="relevance=50; сниппет про другое")
    assert _compose_lead_description(lead, None) == "Поставляем фанеру и ОСБ оптом."


def test_compose_then_notes_snippet():
    lead = _lead(notes="relevance=50; Компания продаёт кровельные материалы.")
    assert _compose_lead_description(lead, None) == "Компания продаёт кровельные материалы."


def test_compose_then_warehouse_description():
    class _C:  # минимальный дублёр складской строки
        description = "Дистрибьютор электрики по СФО."
        categories = ["электротовары"]
    lead = _lead()
    assert _compose_lead_description(lead, _C()) == "Дистрибьютор электрики по СФО."


def test_compose_synthetic_last_resort():
    lead = _lead()
    out = _compose_lead_description(lead, None)
    assert "есть телефон" in out  # суррогат из метаданных, как раньше


# ── enrich task: site_description → lead + склад ────────────────────────────

def test_enrich_fills_lead_description_and_warehouse(db, monkeypatch):
    org = Organization(
        name=f"{_PFX}org-{uuid.uuid4().hex[:6]}", plan=PlanType.pro,
        leads_used_current_month=0, leads_limit_per_month=100000,
        projects_limit=100, users_limit=100,
    )
    db.add(org); db.flush()
    proj = Project(organization_id=org.id, name=f"{_PFX}proj",
                   niche=f"{_PFX}niche", geography="Томск", segments=[], prompt="")
    db.add(proj); db.flush()
    domain = f"{_PFX}{uuid.uuid4().hex[:6]}.ru"
    lead = Lead(
        organization_id=org.id, project_id=proj.id, company=f"{_PFX}Кедр",
        city="Томск", website=f"https://{domain}", domain=domain,
        email="", phone="", source="searxng", status=LeadStatus.new, enriched=False,
    )
    db.add(lead)
    # складская строка той же компании — без описания
    cw.upsert_companies(
        db, [{"company": f"{_PFX}Кедр", "domain": domain, "website": f"https://{domain}",
              "city": "Томск", "email": "", "phone": "", "address": "", "source": "searxng", "score": 10}],
        niche=f"{_PFX}niche",
    )
    db.commit()

    site_desc = "Заготовка и оптовая продажа кедра, пиломатериалы и погонаж."
    monkeypatch.setattr(
        jobs_mod, "enrich_website_contacts",
        lambda url: {"emails": [], "phones": ["+7 999 000-00-00"], "addresses": [],
                     "site_description": site_desc},
    )
    monkeypatch.setattr(jobs_mod, "enrich_2gis_lead",
                        lambda *a, **k: {"emails": [], "phones": [], "addresses": []})
    job = CollectionJob(organization_id=org.id, project_id=proj.id,
                        status=JobStatus.queued, kind="enrich", requested_limit=5)
    db.add(job); db.commit()
    try:
        jobs_mod.enrich_leads_task(str(job.id))
        db.expire_all()
        assert db.get(Lead, lead.id).description == site_desc
        wh = cw.find_company_for_lead(db, domain=domain, company=f"{_PFX}Кедр", city="Томск")
        assert wh is not None and wh.description == site_desc, "склад дозаполнен описанием"
        # и карточка теперь отдаёт реальный текст, а не суррогат
        assert _compose_lead_description(db.get(Lead, lead.id), wh) == site_desc
    finally:
        db.rollback()
        db.execute(delete(Lead).where(Lead.project_id == proj.id))
        db.execute(delete(CollectionJob).where(CollectionJob.project_id == proj.id))
        db.execute(delete(Project).where(Project.id == proj.id))
        db.execute(delete(Organization).where(Organization.id == org.id))
        db.commit()


def test_enrich_does_not_shorten_existing_description(db, monkeypatch):
    """Куцый title с сайта не должен перетирать длинное описание со сбора."""
    org = Organization(
        name=f"{_PFX}org-{uuid.uuid4().hex[:6]}", plan=PlanType.pro,
        leads_used_current_month=0, leads_limit_per_month=100000,
        projects_limit=100, users_limit=100,
    )
    db.add(org); db.flush()
    proj = Project(organization_id=org.id, name=f"{_PFX}proj2",
                   niche=f"{_PFX}niche2", geography="Томск", segments=[], prompt="")
    db.add(proj); db.flush()
    domain = f"{_PFX}{uuid.uuid4().hex[:6]}.ru"
    long_desc = "Полное описание деятельности компании с деталями ассортимента и условий поставки оптовикам."
    lead = Lead(
        organization_id=org.id, project_id=proj.id, company=f"{_PFX}Опт",
        city="Томск", website=f"https://{domain}", domain=domain,
        email="", phone="", source="searxng", status=LeadStatus.new,
        enriched=False, description=long_desc,
    )
    db.add(lead)
    job = CollectionJob(organization_id=org.id, project_id=proj.id,
                        status=JobStatus.queued, kind="enrich", requested_limit=5)
    db.add(job); db.commit()

    monkeypatch.setattr(
        jobs_mod, "enrich_website_contacts",
        lambda url: {"emails": [], "phones": [], "addresses": [], "site_description": "Опт Томск"},
    )
    monkeypatch.setattr(jobs_mod, "enrich_2gis_lead",
                        lambda *a, **k: {"emails": [], "phones": [], "addresses": []})
    try:
        jobs_mod.enrich_leads_task(str(job.id))
        db.expire_all()
        assert db.get(Lead, lead.id).description == long_desc
    finally:
        db.rollback()
        db.execute(delete(Lead).where(Lead.project_id == proj.id))
        db.execute(delete(CollectionJob).where(CollectionJob.project_id == proj.id))
        db.execute(delete(Project).where(Project.id == proj.id))
        db.execute(delete(Organization).where(Organization.id == org.id))
        db.commit()
