"""Remove duplicate e-disclosure covenants from results.json."""
import json

with open("results.json", encoding="utf-8") as f:
    results = json.load(f)

fixed = 0
for r in results:
    covs = r.get("covenants", [])
    if not covs:
        continue

    # Deduplicate e-disclosure covenants by (section, essence[:50])
    seen = set()
    unique = []
    removed = 0
    for c in covs:
        if "e-disclosure" in c.get("document", ""):
            key = (c.get("section", ""), c.get("essence", "")[:80])
            if key in seen:
                removed += 1
                continue
            seen.add(key)
        unique.append(c)

    if removed:
        r["covenants"] = unique
        r["total_covenants"] = len(unique)
        fixed += removed

with open("results.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f"Removed {fixed} duplicate covenants")
print(f"Total covenants now: {sum(len(r.get('covenants', [])) for r in results)}")
