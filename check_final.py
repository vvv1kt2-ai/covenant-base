import json, sys
sys.stdout.reconfigure(encoding='utf-8')
with open("results.json", encoding="utf-8") as f:
    data = json.load(f)
for r in data:
    for c in r.get("covenants", []):
        doc = c.get("document", "")
        if "e-disclosure" in doc or "Программа" in doc:
            print(f"ISIN: {r['isin']} | {r['issuer']}")
            print(f"  category: {c['category']}")
            print(f"  section: {c['section']}")
            print(f"  essence: {c['essence'][:200]}")
            print()
