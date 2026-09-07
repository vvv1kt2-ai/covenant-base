import json
with open("results.json", encoding="utf-8") as f:
    data = json.load(f)
for r in data:
    if r["isin"] in ("RU000A10BFP3", "RU000A10C5J1"):
        print(f"=== {r['isin']} ({r['issuer']}) ===")
        for c in r.get("covenants", []):
            if "e-disclosure" in c.get("document", ""):
                print(f"  cat: {c['category']}")
                print(f"  essence: {c['essence']}")
                print(f"  doc: {c['document']}")
                print(f"  section: {c['section']}")
                print(f"  quote: {c['quote'][:400]}")
                print()
