import json, sys
sys.stdout.reconfigure(encoding='utf-8')
with open("results.json", encoding="utf-8") as f:
    data = json.load(f)
for r in data:
    for c in r.get("covenants", []):
        if "e-disclosure" in c.get("document", ""):
            print(f"ISIN: {r['isin']} | {r['issuer']}")
            print(f"  section: {c['section']}")
            print(f"  essence: {c['essence'][:300]}")
            print()
