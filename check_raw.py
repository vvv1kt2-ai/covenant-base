import json
with open("edisclosure_pilot.json", encoding="utf-8") as f:
    data = json.load(f)
for r in data:
    for fname, events in r.get("program_covenants", {}).items():
        for ev in events:
            print(f"=== {r['emitter']} | {fname} ===")
            print(f"  title: {ev['title'][:200]}")
            print(f"  section: {ev['section']}")
            print(f"  full_text: {ev['full_text'][:500]}")
            print()
