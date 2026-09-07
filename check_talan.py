import json, sys
sys.stdout.reconfigure(encoding='utf-8')
with open("edisclosure_pilot.json", encoding="utf-8") as f:
    data = json.load(f)
for r in data:
    if r["emitter"] == "ТАЛАН-ФИНАНС":
        for fname, events in r.get("program_covenants", {}).items():
            for ev in events:
                print(f"full_text ({len(ev['full_text'])} chars):")
                print(ev["full_text"])
