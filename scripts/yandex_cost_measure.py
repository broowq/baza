"""Rigorous measurement: exact orgs-per-request, niche depth (API `found`),
req/lead distribution + contact-rate across a niche×geo matrix. Trial key."""
import os, statistics
import sys
if not os.environ.get("YANDEX_MAPS_API_KEY"):
    sys.exit("set YANDEX_MAPS_API_KEY (Yandex Geosearch key) before running")
os.environ.setdefault("YANDEX_MAPS_LANG", "ru_RU")

import httpx
from app.services import lead_collection as lc

# ── instrument: record per-request orgs returned + niche `found` total ───────
per_req_orgs = []          # features returned by each org-search request
found_by_query = {}        # query text -> total found reported by API
_req = {"n": 0}
_orig = httpx.Client.get
def _get(self, url, *a, **k):
    resp = _orig(self, url, *a, **k)
    if str(url).startswith(lc._YANDEX_SEARCH_URL):
        _req["n"] += 1
        try:
            d = resp.json()
            feats = d.get("features") or []
            per_req_orgs.append(len(feats))
            md = d["properties"]["ResponseMetaData"]["SearchResponse"]
            q = d["properties"]["ResponseMetaData"]["SearchRequest"]["request"]
            found_by_query[q] = md.get("found", 0)
        except Exception:
            pass
    return resp
httpx.Client.get = _get

MATRIX = [
    ("автосервис", "Москва"), ("стоматология", "Санкт-Петербург"),
    ("кафе", "Новосибирск"), ("салон красоты", "Екатеринбург"),
    ("автосервис", "Казань"), ("мебельная фабрика", "Москва"),
    ("клининговая компания", "Новосибирск"), ("типография", "Екатеринбург"),
    ("грузоперевозки", "Краснодар"), ("столярная мастерская", "Томск"),
    ("пилорама", "Кострома"), ("производство срубов", "Вологда"),
    ("кузница", "Тула"), ("лазерная резка металла", "Иваново"),
]

LIMIT = 60
rows = []
print(f"{'ниша':24}{'гео':18}{'found':>6}{'запр':>5}{'орг/запр':>9}{'лидов':>6}{'req/лид':>8}{'%тел':>5}{'%сайт':>6}")
for niche, geo in MATRIX:
    b_req, b_orgs = _req["n"], len(per_req_orgs)
    cands = lc._search_yandex_maps(niche, geo, [], LIMIT)
    reqs = _req["n"] - b_req
    orgs_this = per_req_orgs[b_orgs:]
    orgs_per_req = (sum(orgs_this) / len(orgs_this)) if orgs_this else 0
    leads = [c for c in cands if lc._candidate_relevance_score(c, niche, geo, []) >= lc._MIN_RELEVANCE_SCORE]
    n = len(leads)
    found = max((found_by_query.get(q, 0) for q in found_by_query), default=0)
    # depth: API found for the bare-niche query (best single signal)
    depth = found_by_query.get(niche, found)
    phone = sum(1 for c in leads if (c.get("phone") or "").strip())
    site = sum(1 for c in leads if (c.get("website") or c.get("domain") or "").strip())
    rpl = reqs / n if n else 0
    rows.append((niche, geo, depth, reqs, orgs_per_req, n, rpl,
                 100*phone/n if n else 0, 100*site/n if n else 0))
    print(f"{niche:24}{geo:18}{depth:6}{reqs:5}{orgs_per_req:9.1f}{n:6}{rpl:8.2f}"
          f"{(100*phone/n if n else 0):4.0f}%{(100*site/n if n else 0):5.0f}%")

print("=" * 88)
full_pages = [x for x in per_req_orgs if x >= 5]   # exclude tail/partial pages
rpls = [r[6] for r in rows if r[5] > 0]
tot_req = sum(r[3] for r in rows); tot_leads = sum(r[5] for r in rows)
tot_phone = sum(r[7]*r[5]/100 for r in rows); tot_site = sum(r[8]*r[5]/100 for r in rows)
print(f"ОРГ/ЗАПРОС:  среднее {statistics.mean(per_req_orgs):.1f}  медиана {statistics.median(per_req_orgs):.0f}  "
      f"max {max(per_req_orgs)}  (полные страницы: среднее {statistics.mean(full_pages):.1f})")
print(f"REQ/ЛИД:     среднее {statistics.mean(rpls):.3f}  медиана {statistics.median(rpls):.3f}  "
      f"p90 {sorted(rpls)[int(0.9*len(rpls))-1]:.3f}  max {max(rpls):.3f}")
print(f"СУММАРНО:    {tot_req} запросов → {tot_leads} лидов  → взвеш. req/лид = {tot_req/tot_leads:.3f}")
print(f"КОНТАКТЫ:    телефон {100*tot_phone/tot_leads:.0f}%   сайт {100*tot_site/tot_leads:.0f}%")
print(f"ГЛУБИНА:     медиана ниши {statistics.median([r[2] for r in rows]):.0f} компаний  "
      f"(min {min(r[2] for r in rows)}, max {max(r[2] for r in rows)})")
w = tot_req/tot_leads
print(f"\n₽/ЛИД (взвеш. req/лид {w:.3f}):")
for lab, rate in [("1k/сут без сохр. ₽0,69", 0.69), ("10k/сут без сохр. ₽0,195", 0.195),
                  ("1k/сут ×3 «с сохр.» ₽2,07", 2.07), ("10k/сут ×3 «с сохр.» ₽0,585", 0.585)]:
    print(f"   {lab:30} → {w*rate:.3f} ₽/лид")
print(f"\nВсего потрачено org-search запросов: {_req['n']}   ключ мёртв: {lc._YANDEX_DEAD_KEY}")
