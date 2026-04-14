"""Simulate 10 different business clients using БАЗА to find customers.

Flow per client:
1. Create project with business description (prompt)
2. Trigger lead collection (limit=30 for speed)
3. Wait for job completion
4. Fetch leads
5. Save results to JSON for analysis

Usage: python test_10_clients.py
"""
import json
import time
import sys
from pathlib import Path

import httpx

API_URL = "http://72.56.11.69/api"
EMAIL = "demo@baza.app"
PASSWORD = "password123"

# 10 diverse business scenarios
SCENARIOS = [
    {
        "name": "Кормовые добавки",
        "prompt": "Продаю кормовые добавки и премиксы для сельскохозяйственных животных в Томске и области",
    },
    {
        "name": "Стройматериалы оптом",
        "prompt": "Оптовая продажа строительных материалов: кирпич, цемент, арматура, утеплители в Москве и Подмосковье",
    },
    {
        "name": "Разработка сайтов",
        "prompt": "Разрабатываем сайты, интернет-магазины и мобильные приложения для бизнеса в Санкт-Петербурге",
    },
    {
        "name": "Бухгалтерские услуги",
        "prompt": "Оказываем бухгалтерские услуги и ведение налоговой отчётности для малого и среднего бизнеса в Казани",
    },
    {
        "name": "Оптовая продукты",
        "prompt": "Оптовая торговля продуктами питания: молочка, мясо, консервы — для ресторанов и магазинов в Новосибирске",
    },
    {
        "name": "Мебельное производство",
        "prompt": "Производим офисную и гостиничную мебель на заказ в Воронеже, ищем партнёров для B2B поставок",
    },
    {
        "name": "Клининг",
        "prompt": "Профессиональный клининг офисов, торговых центров и промышленных помещений в Екатеринбурге",
    },
    {
        "name": "Логистика",
        "prompt": "Грузоперевозки и логистические услуги по России, собственный автопарк, офис в Краснодаре",
    },
    {
        "name": "Оборудование HoReCa",
        "prompt": "Поставка и обслуживание оборудования для ресторанов, кафе, столовых и отелей в Ростове-на-Дону",
    },
    {
        "name": "Упаковка и тара",
        "prompt": "Производство гофрокартонной упаковки и полиэтиленовой тары для пищевых производств в Перми",
    },
]


def login(client: httpx.Client) -> tuple[str, str]:
    """Login and return (access_token, org_id)."""
    r = client.post(f"{API_URL}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    r.raise_for_status()
    data = r.json()
    token = data["access_token"]
    # Get org
    r2 = client.get(
        f"{API_URL}/organizations/my-list",
        headers={"Authorization": f"Bearer {token}"},
    )
    r2.raise_for_status()
    orgs = r2.json()
    org_id = orgs[0]["id"]
    return token, org_id


def _headers(token: str, org_id: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "X-Org-Id": org_id,
        "Content-Type": "application/json",
    }


def delete_existing_projects(client: httpx.Client, token: str, org_id: str) -> None:
    """Delete all existing projects to start clean."""
    r = client.get(f"{API_URL}/projects", headers=_headers(token, org_id))
    r.raise_for_status()
    for p in r.json():
        pid = p["id"]
        client.delete(f"{API_URL}/projects/{pid}", headers=_headers(token, org_id))
        print(f"  Deleted old project: {p['name']}")


def create_project(client: httpx.Client, token: str, org_id: str, scenario: dict) -> dict:
    """Create a project using the enhance-prompt flow."""
    # Step 1: enhance the raw prompt via AI
    r_enhance = client.post(
        f"{API_URL}/projects/enhance-prompt",
        json={"prompt": scenario["prompt"]},
        headers=_headers(token, org_id),
        timeout=30.0,
    )
    r_enhance.raise_for_status()
    enhanced = r_enhance.json()

    # Step 2: create project with enhanced data
    payload = {
        "name": enhanced.get("project_name") or scenario["name"],
        "prompt": scenario["prompt"],
        "niche": enhanced.get("niche", scenario["prompt"][:120]),
        "geography": enhanced.get("geography", "Россия"),
        "segments": enhanced.get("segments", [])[:20],
    }
    r = client.post(
        f"{API_URL}/projects",
        json=payload,
        headers=_headers(token, org_id),
    )
    r.raise_for_status()
    project = r.json()
    project["_enhanced"] = enhanced
    return project


def start_collection(client: httpx.Client, token: str, org_id: str, project_id: str, limit: int = 30) -> str:
    r = client.post(
        f"{API_URL}/leads/project/{project_id}/collect",
        json={"lead_limit": limit},
        headers=_headers(token, org_id),
    )
    r.raise_for_status()
    return r.json()["id"]


def wait_for_job(client: httpx.Client, token: str, org_id: str, project_id: str, job_id: str, timeout: int = 180) -> dict:
    """Poll job status until done or timeout."""
    start = time.time()
    while time.time() - start < timeout:
        r = client.get(
            f"{API_URL}/leads/jobs/project/{project_id}",
            headers=_headers(token, org_id),
        )
        if r.status_code == 200:
            jobs = r.json()
            # Find our job
            for j in jobs:
                if j["id"] == job_id:
                    if j["status"] in ("done", "failed"):
                        return j
                    break
        time.sleep(3)
    return {"status": "timeout"}


def get_leads(client: httpx.Client, token: str, org_id: str, project_id: str) -> list[dict]:
    r = client.get(
        f"{API_URL}/leads/project/{project_id}",
        headers=_headers(token, org_id),
    )
    r.raise_for_status()
    return r.json()


def main() -> None:
    results = []

    with httpx.Client(timeout=60.0) as client:
        print("🔐 Logging in...")
        token, org_id = login(client)
        print(f"   Org ID: {org_id}")

        print("\n🗑️  Cleaning up old projects...")
        delete_existing_projects(client, token, org_id)

        for i, scenario in enumerate(SCENARIOS, 1):
            print(f"\n📦 [{i}/10] {scenario['name']}")
            print(f"   Prompt: {scenario['prompt']}")
            try:
                project = create_project(client, token, org_id, scenario)
                enhanced = project.get("_enhanced", {})
                print(f"   ✅ Project created: {project['name']}")
                print(f"   Niche: {project['niche']}")
                print(f"   Geography: {project['geography']}")
                print(f"   Segments: {project['segments']}")
                print(f"   Target types: {enhanced.get('target_customer_types', [])}")

                job_id = start_collection(client, token, org_id, project["id"], limit=30)
                print(f"   🚀 Collection started: job {job_id[:8]}...")

                job = wait_for_job(client, token, org_id, project["id"], job_id, timeout=180)
                print(f"   ⏱️  Job: {job.get('status')} | found={job.get('found_count', 0)} added={job.get('added_count', 0)}")

                leads = get_leads(client, token, org_id, project["id"])
                print(f"   📊 Leads: {len(leads)}")

                results.append({
                    "scenario": scenario,
                    "project": {
                        "id": project["id"],
                        "name": project["name"],
                        "niche": project["niche"],
                        "geography": project["geography"],
                        "segments": project["segments"],
                    },
                    "enhanced": enhanced,
                    "job": job,
                    "leads_count": len(leads),
                    "leads": [
                        {
                            "company": l.get("company"),
                            "city": l.get("city"),
                            "website": l.get("website"),
                            "domain": l.get("domain"),
                            "phone": l.get("phone"),
                            "email": l.get("email"),
                            "address": l.get("address"),
                            "score": l.get("score"),
                        }
                        for l in leads
                    ],
                })
            except Exception as e:
                print(f"   ❌ ERROR: {e}")
                results.append({"scenario": scenario, "error": str(e)})

    output = Path("/tmp/client_test_results.json")
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"\n💾 Results saved: {output}")
    print(f"📈 Total scenarios: {len(results)}")
    total_leads = sum(r.get("leads_count", 0) for r in results)
    print(f"📈 Total leads collected: {total_leads}")


if __name__ == "__main__":
    main()
