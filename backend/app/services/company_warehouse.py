"""Company warehouse — cross-organization registry of discovered companies.

Two responsibilities:

  * upsert_companies()  — write-through. After a search finalizes its candidate
    list, every candidate is UPSERTed into the shared `companies` table keyed by
    `dedup_key`. Non-empty contact fields are merged (we never overwrite good
    data with empty), the niche/source are appended distinctly, `times_seen` is
    bumped and `best_score` is raised to the max ever observed.

  * search_warehouse() — warehouse-first read. Before/around a live search, we
    pull stored companies matching the same niche + geography and feed them back
    into the candidate set. These hits cost NO external API calls (no 2GIS /
    Yandex / rusprofile quota) and improve recall on repeat searches.

Both functions are BEST-EFFORT: any exception is swallowed and logged, never
raised to the caller. A broken/empty warehouse must never degrade normal
lead collection — callers treat a [] / 0 return as "nothing reused".
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import Text as TEXT_TYPE
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Company
from app.utils.url_tools import extract_domain, get_base_domain

logger = logging.getLogger("baza.company_warehouse")


def _norm_name(s: str) -> str:
    """Lowercased, whitespace-collapsed, trimmed company name.

    Used both as the stored `normalized_name` and (with city) as the dedup_key
    fallback when a company has no domain. ё→е so 'Алёнка' and 'Аленка' collapse.
    """
    if not s:
        return ""
    return " ".join(str(s).lower().replace("ё", "е").split()).strip()


def _dedup_key(domain: str, name: str, city: str) -> str:
    """Identity key for upsert dedupe.

    Lowercased base domain when present (so www./sub-domains collapse to one
    company), else f"{normalized_name}|{city_lower}". Returns "" only when there
    is neither a usable domain nor a name — caller must skip such candidates.
    """
    d = (domain or "").strip().lower()
    if d:
        # Be robust if a full URL (scheme/path) was passed instead of a bare
        # domain — strip it down before taking the registrable base domain.
        if "/" in d or ":" in d:
            d = extract_domain(d) or d
        base = get_base_domain(d) or d
        return base
    nn = _norm_name(name)
    if not nn:
        return ""
    city_lower = (city or "").strip().lower().replace("ё", "е")
    return f"{nn}|{city_lower}"


def _candidate_domain(c: dict) -> str:
    """Best domain for a candidate: explicit field, else derived from website."""
    domain = (c.get("domain") or "").strip().lower()
    if domain:
        return domain
    return (extract_domain(c.get("website") or "") or "").lower()


def _merge_distinct(existing: list | None, *values: str) -> list[str]:
    """Append non-empty *values* to *existing* preserving order, deduped."""
    out: list[str] = []
    seen: set[str] = set()
    for v in list(existing or []) + list(values):
        v = (v or "").strip()
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
    return out


def _clip(value: str, max_len: int) -> str:
    return (value or "")[:max_len]


def upsert_companies(db: Session, candidates: list[dict], *, niche: str) -> int:
    """UPSERT each candidate into `companies`, deduped by dedup_key.

    For each candidate we compute the dedup_key and INSERT … ON CONFLICT
    (dedup_key) DO UPDATE so that:
      * non-empty contact fields are filled in (never overwriting existing
        good data with an empty incoming value),
      * the `niche` is appended to niches[] and the source to sources[]
        (distinct),
      * times_seen is bumped by 1, last_seen_at is set to now,
      * best_score is raised to max(existing, incoming).

    Best-effort — wraps everything in try/except and never raises. Returns the
    number of candidates successfully upserted (insert or update).
    """
    if not candidates:
        return 0

    niche_norm = (niche or "").strip()
    upserted = 0

    # Collapse the incoming batch by dedup_key first, so two candidates for the
    # same company in one search become a single upsert (and merge cleanly).
    batched: dict[str, dict] = {}
    order: list[str] = []
    for c in candidates:
        domain = _candidate_domain(c)
        name = (c.get("company") or c.get("name") or "").strip()
        city = (c.get("city") or "").strip()
        key = _dedup_key(domain, name, city)
        if not key:
            # Neither domain nor name — nothing to identify this company by.
            continue
        key = _clip(key, 255)
        if key not in batched:
            batched[key] = c
            order.append(key)
        else:
            # Prefer the candidate carrying more contact signal as the base.
            if _signal_strength(c) > _signal_strength(batched[key]):
                batched[key] = c

    for key in order:
        c = batched[key]
        try:
            _upsert_one(db, key, c, niche_norm=niche_norm)
            db.commit()
            upserted += 1
        except Exception:
            logger.warning("warehouse upsert failed for one candidate", exc_info=True)
            # Roll back just this candidate so the session stays usable for the
            # rest of the batch. Never raise to the caller.
            try:
                db.rollback()
            except Exception:
                pass
            continue

    return upserted


def _signal_strength(c: dict) -> int:
    """Crude contact-completeness score, used to pick the better duplicate."""
    s = 0
    for k in ("email", "phone", "address", "website", "domain"):
        if (c.get(k) or "").strip():
            s += 1
    return s


def _upsert_one(db: Session, key: str, c: dict, *, niche_norm: str) -> None:
    """INSERT a new company or merge into the existing row matching *key*.

    Merge rules (apply only on UPDATE):
      * non-empty contact fields fill empties (never overwrite good with empty),
      * niche → niches[] and source → sources[] appended distinctly,
      * categories merged distinctly,
      * times_seen += 1, last_seen_at = now,
      * best_score = max(existing, incoming).
    """
    domain = _candidate_domain(c)
    name = (c.get("company") or c.get("name") or "").strip()
    city = (c.get("city") or "").strip()
    source = (c.get("source") or "").strip().lower()

    # external_id may carry a 2GIS firm_id or rusprofile id depending on source.
    firm_id = str(c.get("twogis_firm_id") or c.get("firm_id") or "").strip()
    if not firm_id and source == "2gis":
        firm_id = str(c.get("external_id") or "").strip()
    rusprofile_id = str(c.get("rusprofile_id") or "").strip()
    if not rusprofile_id and source == "rusprofile":
        rusprofile_id = str(c.get("external_id") or "").strip()
    inn = str(c.get("inn") or "").strip()

    categories = c.get("categories") or []
    if isinstance(categories, str):
        categories = [categories]
    categories = [str(x).strip() for x in categories if str(x).strip()]

    contacts_json = c.get("contacts_json") or {}
    if not isinstance(contacts_json, dict):
        contacts_json = {}

    score = int(c.get("score") or c.get("relevance_score") or 0)
    description = c.get("snippet") or c.get("description") or ""
    now = datetime.now(timezone.utc)

    existing = db.execute(
        select(Company).where(Company.dedup_key == key).with_for_update()
    ).scalar_one_or_none()

    if existing is None:
        company = Company(
            dedup_key=key,
            domain=_clip(domain, 255),
            normalized_name=_clip(_norm_name(name), 255),
            name=_clip(name, 255),
            website=_clip(c.get("website") or "", 400),
            email=_clip(c.get("email") or "", 255),
            phone=_clip(c.get("phone") or "", 120),
            address=_clip(c.get("address") or "", 400),
            city=_clip(city, 120),
            region=_clip(c.get("region") or "", 120),
            categories=_merge_distinct(None, *categories),
            niches=_merge_distinct(None, niche_norm) if niche_norm else [],
            sources=_merge_distinct(None, source) if source else [],
            twogis_firm_id=_clip(firm_id, 80),
            rusprofile_id=_clip(rusprofile_id, 80),
            inn=_clip(inn, 20),
            description=description,
            contacts_json=contacts_json,
            best_score=score,
            times_seen=1,
            first_seen_at=now,
            last_seen_at=now,
            raw_json={},
        )
        db.add(company)
        return

    # ── merge into existing ──────────────────────────────────────────────
    def _fill(attr: str, value: str, max_len: int) -> None:
        value = (value or "").strip()
        if value and not (getattr(existing, attr) or "").strip():
            setattr(existing, attr, _clip(value, max_len))

    _fill("domain", domain, 255)
    _fill("normalized_name", _norm_name(name), 255)
    _fill("name", name, 255)
    _fill("website", c.get("website") or "", 400)
    _fill("email", c.get("email") or "", 255)
    _fill("phone", c.get("phone") or "", 120)
    _fill("address", c.get("address") or "", 400)
    _fill("city", city, 120)
    _fill("region", c.get("region") or "", 120)
    _fill("twogis_firm_id", firm_id, 80)
    _fill("rusprofile_id", rusprofile_id, 80)
    _fill("inn", inn, 20)
    _fill("description", description, 100000)

    if niche_norm:
        existing.niches = _merge_distinct(existing.niches, niche_norm)
    if source:
        existing.sources = _merge_distinct(existing.sources, source)
    if categories:
        existing.categories = _merge_distinct(existing.categories, *categories)
    if contacts_json and not existing.contacts_json:
        existing.contacts_json = contacts_json

    existing.times_seen = (existing.times_seen or 0) + 1
    existing.last_seen_at = now
    existing.best_score = max(int(existing.best_score or 0), score)


def find_company_for_lead(db: Session, *, domain: str, company: str, city: str) -> Company | None:
    """Look up the warehouse Company matching a lead, by the same dedup_key rule.

    Used by the lead-detail endpoint to attach a cross-reference block. Returns
    None if not found or on any error (best-effort).
    """
    try:
        key = _dedup_key(domain or "", company or "", city or "")
        if not key:
            return None
        return db.execute(
            select(Company).where(Company.dedup_key == key)
        ).scalar_one_or_none()
    except Exception:
        logger.debug("warehouse lookup failed", exc_info=True)
        return None


def _case_variants(term: str) -> list[str]:
    """Distinct case variants of *term* for locale-independent matching.

    The local Postgres runs a C-locale collation, so ILIKE / lower() do NOT
    case-fold Cyrillic ('%томск%' won't match 'Томск'). We can't rely on the DB
    to fold case, so we fold in Python and OR a small set of realistic variants:
    the raw term, its lowercase, Title-Case, Capitalized and UPPERCASE forms.
    Real city/niche strings from 2GIS/Yandex/project config fall into one of
    these, so recall is preserved without a collation migration.
    """
    term = (term or "").strip()
    if not term:
        return []
    variants = {term, term.lower(), term.upper(), term.title(), term.capitalize()}
    return [v for v in variants if v]


def _ci_like(column, term: str):
    """OR of `column ILIKE %variant%` across the case variants of *term*."""
    return or_(*[column.ilike(f"%{v}%") for v in _case_variants(term)])


def _niches_contains_ci(term: str):
    """OR of jsonb `niches @> [variant]` across case variants of *term*.

    jsonb containment is exact-match (case-sensitive), so we test the same case
    variants. niches[] is stored as the niche string as-passed (usually the
    lowercase project niche), so the lowercase variant is the common hit.
    """
    return or_(*[Company.niches.contains([v]) for v in _case_variants(term)])


def search_warehouse(
    db: Session,
    *,
    niche: str,
    geography: str,
    segments: list[str] | None = None,
    limit: int = 100,
) -> list[dict]:
    """Return stored companies matching niche + geography as candidate dicts.

    Match rule (intentionally conservative — recall over precision, since the
    live pipeline re-scores everything afterwards):
      * niche: `niche` present in niches[] OR normalized_name/description ILIKE
        the niche OR any segment ILIKE-matches. (jsonb containment + ILIKE.)
      * geography: city/region/address ILIKE the geography. When geography is a
        region/oblast, we also accept rows whose city resolves into that region.

    The returned dicts use the SAME shape the search pipeline consumes, with
    source="warehouse", demo=False. These are FREE — no external API call.

    Best-effort: returns [] on any error.
    """
    if not (niche or "").strip() and not (geography or "").strip():
        return []
    try:
        niche_clean = (niche or "").strip()
        geo_clean = (geography or "").strip()
        seg_list = [s.strip() for s in (segments or []) if s and s.strip()]

        stmt = select(Company)

        # ── niche predicate ──────────────────────────────────────────────
        # NB: case folding is done in Python (_case_variants) because the local
        # Postgres C-locale does not case-fold Cyrillic in ILIKE/lower().
        niche_clauses = []
        if niche_clean:
            niche_clauses.append(_niches_contains_ci(niche_clean))
            niche_clauses.append(_ci_like(Company.normalized_name, niche_clean))
            niche_clauses.append(_ci_like(Company.description, niche_clean))
            # categories holds free-text strings — cast jsonb to text for ILIKE.
            niche_clauses.append(_ci_like(Company.categories.cast(TEXT_TYPE), niche_clean))
        for seg in seg_list[:24]:
            niche_clauses.append(_niches_contains_ci(seg))
            niche_clauses.append(_ci_like(Company.normalized_name, seg))
            niche_clauses.append(_ci_like(Company.description, seg))
            niche_clauses.append(_ci_like(Company.categories.cast(TEXT_TYPE), seg))
        if niche_clauses:
            stmt = stmt.where(or_(*niche_clauses))

        # ── geography predicate ──────────────────────────────────────────
        if geo_clean and geo_clean.lower() not in _NATIONWIDE_GEOS:
            geo_clauses = [
                _ci_like(Company.city, geo_clean),
                _ci_like(Company.region, geo_clean),
                _ci_like(Company.address, geo_clean),
            ]
            # If the geography is a federal subject (oblast/kray/...), also match
            # rows whose region column equals it, and rows whose city maps to it.
            region = _region_of(geo_clean)
            if region:
                geo_clauses.append(_ci_like(Company.region, region))
                for c_name in _cities_in_region(region):
                    geo_clauses.append(_ci_like(Company.city, c_name))
            stmt = stmt.where(or_(*geo_clauses))

        stmt = stmt.order_by(Company.best_score.desc(), Company.times_seen.desc()).limit(max(1, limit))
        rows = db.execute(stmt).scalars().all()
        return [_company_to_candidate(row) for row in rows]
    except Exception:
        logger.warning("warehouse search failed", exc_info=True)
        return []


def _company_to_candidate(row: Company) -> dict:
    """Render a Company row as a search-pipeline candidate dict.

    Shape mirrors what 2GIS/Yandex/searxng candidates carry so downstream
    scoring + dedup treat warehouse hits identically. source='warehouse',
    demo=False. external_id prefers the 2GIS firm_id, then rusprofile id.
    """
    external_id = row.twogis_firm_id or row.rusprofile_id or ""
    return {
        "company": row.name or row.normalized_name,
        "city": row.city or "",
        "website": row.website or "",
        "domain": row.domain or "",
        "email": row.email or "",
        "phone": row.phone or "",
        "address": row.address or "",
        "score": int(row.best_score or 0),
        "source": "warehouse",
        "source_url": row.website or "",
        "snippet": row.description or "",
        "categories": list(row.categories or []),
        "external_id": external_id,
        # firm_id / rusprofile_id mirror the originating-source identifiers so the
        # persist loop in collect_leads_task can rebuild external_id and the
        # "maps://2gis/{firm_id}" placeholder URL exactly as for a live result.
        "firm_id": row.twogis_firm_id or "",
        "rusprofile_id": row.rusprofile_id or "",
        "demo": False,
    }


# ─── Geo helpers (reused from lead_collection to keep region logic consistent) ──
# Imported at module load so region matching matches the live pipeline exactly.
from app.services.lead_collection import (  # noqa: E402
    _CITY_TO_REGION,
    _NATIONWIDE_GEOS,
    _region_of,
)


def _cities_in_region(region_lower: str) -> list[str]:
    """All known major cities whose federal subject equals *region_lower*."""
    region_lower = (region_lower or "").strip().lower()
    if not region_lower:
        return []
    return [city for city, reg in _CITY_TO_REGION.items() if reg.lower() == region_lower]
