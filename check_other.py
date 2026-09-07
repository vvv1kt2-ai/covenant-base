import json, sys
sys.stdout.reconfigure(encoding='utf-8')
with open("results.json", encoding="utf-8") as f:
    data = json.load(f)
for r in data:
    for c in r.get("covenants", []):
        if c.get("category") == "Иное":
            print(f"ISIN: {r['isin']} | {r['issuer']}")
            print(f"  doc: {c.get('document','')}")
            print(f"  essence: {c.get('essence','')[:200]}")
            print()
