"""E2E: users putting their OWN leads into the platform.

Two paths, end to end through real HTTP + auth + DB (no dependency overrides):
  1. manual single-lead create  — POST /api/leads/project/{pid}
  2. bulk CSV/XLSX import        — POST /api/leads/project/{pid}/import

Asserts the business rules that matter for the user's-own-data feature:
  * no-website leads get a "manual://" placeholder (NOT NULL + unique survives),
  * source=="manual" and the AI-collection counter (leads_used_current_month)
    is NEVER incremented by manual/imported leads,
  * dedup mirrors the collector (website/domain OR company+city),
  * import dry_run previews without inserting; commit inserts,
  * the row-size cap (5000) is enforced.
"""
from __future__ import annotations

import io
import uuid

from app.db.session import SessionLocal
from app.models import Organization


def _used(org_id: str) -> int:
    """Read the org's AI-collection counter straight from the DB (a fresh
    session each call so we never see a stale identity-map value)."""
    db = SessionLocal()
    try:
        return db.get(Organization, org_id).leads_used_current_month
    finally:
        db.close()


def _table_total(acct, pid: str) -> int:
    r = acct.get(f"/api/leads/project/{pid}/table?per_page=200")
    assert r.status_code == 200, r.text
    return r.json()["total"]


# ── manual single-lead create ───────────────────────────────────────────────

def test_create_lead_without_website_uses_placeholder(paid_account, new_project):
    """A no-website lead → website starts "manual://", source=="manual", shows
    up in the table, and the AI-collection counter is untouched."""
    acct = paid_account
    pid = new_project(acct)["id"]

    before = _used(acct.org_id)

    r = acct.post(f"/api/leads/project/{pid}", json={"company": "ООО Тест"})
    assert r.status_code == 201, r.text
    lead = r.json()
    assert lead["company"] == "ООО Тест"
    assert lead["website"].startswith("manual://"), lead["website"]
    assert lead["domain"] == ""
    assert lead["source"] == "manual"

    # Appears in the project table.
    table = acct.get(f"/api/leads/project/{pid}/table?per_page=50")
    assert table.status_code == 200, table.text
    assert any(it["id"] == lead["id"] for it in table.json()["items"])

    # Manual lead must NOT consume the AI-collection quota.
    assert _used(acct.org_id) == before, "manual lead must not bump leads_used_current_month"


def test_create_lead_with_website_dedups(paid_account, new_project):
    """Creating the same website twice → second call 409s with the first id."""
    acct = paid_account
    pid = new_project(acct)["id"]

    first = acct.post(
        f"/api/leads/project/{pid}",
        json={"company": "Acme", "website": "https://acme.ru"},
    )
    assert first.status_code == 201, first.text
    first_id = first.json()["id"]
    assert first.json()["domain"] == "acme.ru"

    dup = acct.post(
        f"/api/leads/project/{pid}",
        json={"company": "Acme", "website": "https://acme.ru"},
    )
    assert dup.status_code == 409, dup.text
    detail = dup.json()["detail"]
    assert detail["existing_lead_id"] == first_id, detail


def test_create_lead_assign_to_non_member_is_422(paid_account, new_project):
    """An assignee that isn't a member of the org → 422 (not a silent assign)."""
    acct = paid_account
    pid = new_project(acct)["id"]

    r = acct.post(
        f"/api/leads/project/{pid}",
        json={"company": "ООО Назначение", "assigned_to_user_id": str(uuid.uuid4())},
    )
    assert r.status_code == 422, r.text


# ── bulk import ─────────────────────────────────────────────────────────────

def _csv_with_dupe_and_missing(existing_website: str) -> bytes:
    """A ';'-delimited RU-header CSV: one good row, one duplicate of an existing
    lead, one row with a missing company (an error row)."""
    lines = [
        "Компания;Город;Сайт;Email;Телефон",
        "ООО Импорт;Казань;https://import-novel.ru;a@import-novel.ru;+7 900 000-00-01",
        f"Дубликат;Москва;{existing_website};b@dup.ru;+7 900 000-00-02",
        ";Самара;https://no-company.ru;c@nc.ru;+7 900 000-00-03",
    ]
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def test_import_csv_dry_run_then_commit(paid_account, new_project):
    """dry_run previews (created excludes the dupe + the error row) and inserts
    NOTHING; the real run inserts exactly the previewed count."""
    acct = paid_account
    pid = new_project(acct)["id"]

    # Seed one existing lead so the CSV can contain a duplicate-of-existing row.
    seed = acct.post(
        f"/api/leads/project/{pid}",
        json={"company": "Сид", "website": "https://seed-dup.ru"},
    )
    assert seed.status_code == 201, seed.text

    base_total = _table_total(acct, pid)
    before_used = _used(acct.org_id)

    content = _csv_with_dupe_and_missing("https://seed-dup.ru")

    # ── dry run: preview only, nothing persisted ──
    dry = acct.post(
        f"/api/leads/project/{pid}/import?dry_run=true",
        files={"file": ("leads.csv", io.BytesIO(content), "text/csv")},
    )
    assert dry.status_code == 200, dry.text
    body = dry.json()
    assert body["dry_run"] is True
    assert body["total"] == 3
    assert body["created"] == 1, body          # 1 good; dupe + missing excluded
    assert body["duplicates"] == 1, body
    # The missing-company row surfaces as an error.
    assert any("компани" in e["error"].lower() for e in body["errors"]), body["errors"]
    # The RU headers were auto-mapped onto canonical fields.
    assert body["detected_columns"].get("company") == "Компания"
    assert body["detected_columns"].get("phone") == "Телефон"

    # Nothing was inserted by the dry run.
    assert _table_total(acct, pid) == base_total, "dry_run must insert nothing"

    # ── real run: inserts exactly the created count ──
    commit = acct.post(
        f"/api/leads/project/{pid}/import?dry_run=false",
        files={"file": ("leads.csv", io.BytesIO(content), "text/csv")},
    )
    assert commit.status_code == 200, commit.text
    cbody = commit.json()
    assert cbody["dry_run"] is False
    assert cbody["created"] == 1, cbody
    assert cbody["duplicates"] == 1, cbody

    assert _table_total(acct, pid) == base_total + 1, "commit should add exactly created count"
    # Imported leads are the user's own data — counter untouched.
    assert _used(acct.org_id) == before_used, "import must not bump leads_used_current_month"


def test_import_xlsx(paid_account, new_project):
    """A tiny in-memory .xlsx with 2 valid rows imports both."""
    from openpyxl import Workbook

    acct = paid_account
    pid = new_project(acct)["id"]

    wb = Workbook()
    ws = wb.active
    ws.append(["Компания", "Город", "Сайт", "Email", "Телефон"])
    ws.append(["ООО Эксель Один", "Москва", "https://xlsx-one.ru", "1@x.ru", "+7 900 111-11-11"])
    ws.append(["ООО Эксель Два", "Питер", "https://xlsx-two.ru", "2@x.ru", "+7 900 222-22-22"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    r = acct.post(
        f"/api/leads/project/{pid}/import",
        files={
            "file": (
                "leads.xlsx",
                buf,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 2, body
    assert _table_total(acct, pid) == 2


def test_import_too_many_rows_is_422(paid_account, new_project):
    """Header + 5001 data rows exceeds the 5000-row cap → 422."""
    acct = paid_account
    pid = new_project(acct)["id"]

    lines = ["Компания;Сайт"]
    for i in range(5001):
        lines.append(f"ООО Строка {i};https://row{i}-cap.ru")
    content = ("\r\n".join(lines) + "\r\n").encode("utf-8")

    r = acct.post(
        f"/api/leads/project/{pid}/import",
        files={"file": ("big.csv", io.BytesIO(content), "text/csv")},
    )
    assert r.status_code == 422, r.text
