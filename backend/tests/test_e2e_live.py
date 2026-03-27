import os
import uuid

import httpx
import pytest


BASE_URL = os.getenv("E2E_BASE_URL", "http://localhost:8000/api")


@pytest.mark.e2e
@pytest.mark.skipif(os.getenv("RUN_E2E") != "1", reason="Set RUN_E2E=1 to run live E2E")
def test_live_flow_register_project_collect_enrich_export():
    suffix = uuid.uuid4().hex[:8]
    email = f"e2e-{suffix}@example.com"
    password = "password123"
    org_name = f"БАЗА E2E {suffix}"

    register = httpx.post(
        f"{BASE_URL}/auth/register",
        json={
            "email": email,
            "full_name": "E2E User",
            "password": password,
            "organization_name": org_name,
        },
        timeout=20,
    )
    assert register.status_code in (200, 201)
    access_token = register.json()["access_token"]

    me = httpx.get(f"{BASE_URL}/auth/me", headers={"Authorization": f"Bearer {access_token}"}, timeout=20)
    assert me.status_code == 200

    orgs = httpx.get(
        f"{BASE_URL}/orgs",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )
    assert orgs.status_code == 200
    org_id = orgs.json()[0]["id"]
    headers = {"Authorization": f"Bearer {access_token}", "X-Org-Id": org_id}

    create_project = httpx.post(
        f"{BASE_URL}/projects",
        headers=headers,
        json={
            "name": f"E2E Project {suffix}",
            "niche": "it",
            "geography": "ru",
            "segments": ["b2b"],
            "cron_schedule": "0 9 * * 1",
            "auto_collection_enabled": False,
        },
        timeout=20,
    )
    assert create_project.status_code == 200
    project_id = create_project.json()["id"]

    collect = httpx.post(
        f"{BASE_URL}/leads/project/{project_id}/collect",
        headers=headers,
        json={"lead_limit": 10},
        timeout=20,
    )
    assert collect.status_code == 200

    enrich = httpx.post(
        f"{BASE_URL}/leads/project/{project_id}/enrich",
        headers=headers,
        json={"lead_limit": 10},
        timeout=20,
    )
    assert enrich.status_code == 200

    table = httpx.get(
        f"{BASE_URL}/leads/project/{project_id}/table?page=1&per_page=25&sort=score&order=desc&min_score=0&max_score=100",
        headers=headers,
        timeout=20,
    )
    assert table.status_code == 200
    payload = table.json()
    assert "items" in payload
    if payload["items"]:
        assert "score" in payload["items"][0]

    export_csv = httpx.get(f"{BASE_URL}/leads/project/{project_id}/export", headers=headers, timeout=20)
    assert export_csv.status_code == 200
    assert "company,city,website,domain,email,phone,address,score,status,source_url,contacts_json" in export_csv.text
