"""Analyze the quality of leads collected by test_10_clients.py.

Reads /tmp/client_test_results.json and outputs:
- Per-scenario: leads found, % with contact data, sample companies
- Overall: total leads, scenarios with 0 results, quality indicators
"""
import json
from pathlib import Path
from collections import Counter


def main() -> None:
    path = Path("/tmp/client_test_results.json")
    if not path.exists():
        print("❌ Results file not found. Run test_10_clients.py first.")
        return
    data = json.loads(path.read_text())

    print("=" * 80)
    print("📊 ОТЧЁТ О КАЧЕСТВЕ ПОИСКА — 10 СЦЕНАРИЕВ")
    print("=" * 80)

    total_leads = 0
    zero_scenarios = []
    quality_rows = []

    for idx, r in enumerate(data, 1):
        scenario = r.get("scenario", {})
        leads = r.get("leads", [])
        total_leads += len(leads)

        name = scenario.get("name", f"#{idx}")
        prompt = scenario.get("prompt", "")[:60]

        print(f"\n📦 [{idx}/{len(data)}] {name}")
        print(f"   Prompt: {prompt}")

        if "error" in r:
            print(f"   ❌ ERROR: {r['error']}")
            zero_scenarios.append(name)
            continue

        if len(leads) == 0:
            print(f"   ⚠️  0 лидов!")
            zero_scenarios.append(name)
            job = r.get("job", {})
            print(f"   Job: status={job.get('status')} found={job.get('found_count', 0)}")
            continue

        # Count quality indicators
        with_website = sum(1 for l in leads if l.get("website") and not l["website"].startswith("maps://"))
        with_phone = sum(1 for l in leads if l.get("phone"))
        with_email = sum(1 for l in leads if l.get("email"))
        with_address = sum(1 for l in leads if l.get("address"))
        avg_score = sum(l.get("score", 0) for l in leads) / len(leads) if leads else 0

        print(f"   ✅ Лидов: {len(leads)}")
        print(f"      с сайтом: {with_website} ({100*with_website//len(leads)}%)")
        print(f"      с телефоном: {with_phone} ({100*with_phone//len(leads)}%)")
        print(f"      с email: {with_email} ({100*with_email//len(leads)}%)")
        print(f"      с адресом: {with_address} ({100*with_address//len(leads)}%)")
        print(f"      средний score: {avg_score:.1f}")
        print(f"   Топ-5 лидов:")
        for l in leads[:5]:
            co = (l.get("company") or "?")[:50]
            site = (l.get("website") or "—")[:40]
            phone = l.get("phone") or "—"
            score = l.get("score", 0)
            print(f"      • {co} | {site} | {phone} | {score}")

        quality_rows.append({
            "name": name,
            "count": len(leads),
            "with_website_pct": 100*with_website//len(leads) if leads else 0,
            "with_phone_pct": 100*with_phone//len(leads) if leads else 0,
            "with_address_pct": 100*with_address//len(leads) if leads else 0,
            "avg_score": avg_score,
        })

    # Summary
    print("\n" + "=" * 80)
    print("📈 ИТОГО")
    print("=" * 80)
    print(f"Всего лидов собрано: {total_leads}")
    print(f"Сценариев с 0 лидов: {len(zero_scenarios)}/{len(data)}")
    if zero_scenarios:
        for n in zero_scenarios:
            print(f"   ❌ {n}")
    avg_per_scenario = total_leads / len(data) if data else 0
    print(f"Среднее лидов на сценарий: {avg_per_scenario:.1f}")

    if quality_rows:
        print("\n📋 Качество данных (для сценариев с лидами):")
        print(f"{'Сценарий':<25} {'Лидов':>6} {'Сайт%':>7} {'Тел%':>6} {'Адрес%':>8} {'Score':>7}")
        print("-" * 70)
        for row in quality_rows:
            print(f"{row['name']:<25} {row['count']:>6} {row['with_website_pct']:>6}% {row['with_phone_pct']:>5}% {row['with_address_pct']:>7}% {row['avg_score']:>7.1f}")


if __name__ == "__main__":
    main()
